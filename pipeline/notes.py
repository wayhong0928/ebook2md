"""
Phase 2: Chapter-by-chapter book note generation.

Workflow:
  1. prepare_notes(book_id) → writes pending_notes.json with chapter content
     (uses EPUB directly for accurate chapter structure; MD is fallback)
  2. Claude Code reads pending_notes.json, generates notes_results.json
  3. apply_notes() → fills 10_Books/ note, creates 20_Concepts/ concept cards
"""
import json
import re
from datetime import date
from pathlib import Path

from config import PIPELINE_DIR, VAULT_ROOT
from logger import get_logger
from activity import record_book_action
from manifest import load_manifest, update_book

log = get_logger("notes")

PENDING_NOTES_FILE = PIPELINE_DIR / "pending_notes.json"
NOTES_RESULTS_FILE = PIPELINE_DIR / "notes_results.json"
MIN_CHAPTER_CHARS = 200
MAX_CHARS_PER_CHAPTER = 40000


def _safe_title(title: str) -> str:
    """Filename-safe concept title. Must be used for BOTH the card's filename
    and every wikilink that points at it — using the raw title for one and
    this for the other silently produces a broken link (e.g. "TCP/IP..." ->
    file "TCPIP....md" but link text still "[[TCP/IP...]]")."""
    return re.sub(r'[\\/:*?"<>|]', "", title)


# ---------------------------------------------------------------------------
# Chapter slicing
# ---------------------------------------------------------------------------

def _slice_from_epub(epub_path: Path) -> list[dict]:
    """Parse EPUB directly using spine order + TOC titles."""
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(epub_path))

        # Build filename → title map from TOC
        title_map: dict[str, str] = {}

        def _walk_toc(nodes):
            for node in nodes:
                if isinstance(node, tuple) and len(node) == 2:
                    link, children = node
                    if hasattr(link, "href") and hasattr(link, "title") and link.title:
                        fname = link.href.split("#")[0].split("/")[-1]
                        if fname and fname not in title_map:
                            title_map[fname] = link.title.strip()
                    _walk_toc(children)

        _walk_toc(book.toc)

        chapters, num = [], 0
        for spine_id, _ in book.spine:
            item = book.get_item_with_id(spine_id)
            if not item or item.media_type != "application/xhtml+xml":
                continue
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if len(text) < MIN_CHAPTER_CHARS:
                continue

            fname = Path(item.get_name()).name
            title = title_map.get(fname)
            if not title:
                heading = soup.find(["h1", "h2", "h3"])
                title = heading.get_text(strip=True) if heading else f"第 {num + 1} 節"

            num += 1
            chapters.append({
                "chapter_num": num,
                "title": title,
                "char_count": len(text),
                "content": text[:MAX_CHARS_PER_CHAPTER],
            })
        return chapters
    except Exception as e:
        log.error("EPUB parsing failed: %s", e)
        return []


def _slice_from_md(md_text: str) -> list[dict]:
    """Fallback: slice converted MD file by --- separators."""
    raw = re.split(r"\n---+\n", md_text)
    chapters, num = [], 0
    for section in raw:
        section = section.strip()
        if not section:
            continue
        if re.match(r"^#\s*[書作轉]", section):
            continue
        clean = re.sub(r"\[圖片[^\]]*\]", "", section).strip()
        if len(clean) < MIN_CHAPTER_CHARS:
            continue
        m = re.match(r"^#{1,6}\s+(.+)", section, re.MULTILINE)
        title = m.group(1).strip() if m else f"第 {num + 1} 節"
        num += 1
        chapters.append({
            "chapter_num": num,
            "title": title,
            "char_count": len(section),
            "content": section[:MAX_CHARS_PER_CHAPTER],
        })
    return chapters


# ---------------------------------------------------------------------------
# prepare_notes
# ---------------------------------------------------------------------------

def prepare_notes(book_id: str, max_chapters: int | None = None) -> Path | None:
    manifest = load_manifest()
    entry = manifest["books"].get(book_id)
    if not entry:
        log.error("book_id not found: %s", book_id)
        return None

    classification = entry.get("classification", {})
    md_path = Path(entry["md_path"]) if entry.get("md_path") else None
    epub_path = Path(entry["epub_path"]) if entry.get("epub_path") else None

    chapters, source_used = [], "epub"

    # EPUB first: accurate chapter structure from spine + TOC
    if epub_path and epub_path.exists():
        chapters = _slice_from_epub(epub_path)
        log.info("Sliced %d chapters from EPUB: %s", len(chapters), epub_path.name)

    # Fall back to MD if EPUB yields too few chapters
    if len(chapters) < 2 and md_path and md_path.exists():
        log.info("EPUB yielded %d chapter(s) — falling back to MD", len(chapters))
        chapters = _slice_from_md(md_path.read_text(encoding="utf-8", errors="ignore"))
        source_used = "md"

    if not chapters:
        log.error("No chapters found for: %s", book_id)
        return None

    if max_chapters:
        chapters = chapters[:max_chapters]

    payload = {
        "book_id": book_id,
        "title": classification.get("title") or book_id,
        "author": classification.get("author") or entry.get("author", ""),
        "category": classification.get("category") or entry.get("category", ""),
        "core_premise": classification.get("core_premise", ""),
        "total_chapters": len(chapters),
        "source_used": source_used,
        "chapters": chapters,
    }

    PENDING_NOTES_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_book_action("notes_prepared", book_id, {
        "chapters": len(chapters), "source": source_used,
    })

    print(f"\nReady: {PENDING_NOTES_FILE}")
    print(f"  {len(chapters)} chapters ({source_used})")
    print("\nAsk Claude Code:")
    print('  "請讀 pipeline/pending_notes.json，幫我生成書籍筆記，輸出到 pipeline/notes_results.json"')
    return PENDING_NOTES_FILE


# ---------------------------------------------------------------------------
# split_pending_notes / merge_notes_results — for books too large for one
# subagent context window. prepare_notes() no longer truncates chapters by
# default (whole book, every chapter); when the raw content is large, split
# into batches here, hand each batch to its own subagent, then merge their
# partial notes_results back into one file before apply_notes().
# ---------------------------------------------------------------------------

DEFAULT_MAX_CHARS_PER_BATCH = 150_000


def split_pending_notes(
    pending_path: Path = PENDING_NOTES_FILE,
    max_chars_per_batch: int = DEFAULT_MAX_CHARS_PER_BATCH,
) -> list[Path]:
    """
    Split a prepared pending_notes.json into N batch files
    (pending_notes_batch1.json, batch2.json, ...) if its total content
    exceeds max_chars_per_batch. Each batch keeps chapters contiguous
    (never splits a chapter across batches) and carries the same book-level
    metadata plus batch_num/total_batches for traceability.

    Returns the list of batch file paths (length 1 if no split was needed —
    the single path is still pending_notes.json itself, unchanged).
    """
    data = json.loads(pending_path.read_text(encoding="utf-8"))
    chapters = data["chapters"]
    total_chars = sum(c["char_count"] for c in chapters)

    if total_chars <= max_chars_per_batch:
        return [pending_path]

    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for ch in chapters:
        n = ch["char_count"]
        # an oversized single chapter gets its own batch rather than blocking others
        if cur and cur_chars + n > max_chars_per_batch:
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(ch)
        cur_chars += n
    if cur:
        batches.append(cur)

    paths = []
    for i, batch_chapters in enumerate(batches, 1):
        batch_payload = {
            **{k: v for k, v in data.items() if k != "chapters"},
            "batch_num": i,
            "total_batches": len(batches),
            "chapters": batch_chapters,
        }
        batch_path = PIPELINE_DIR / f"pending_notes_batch{i}.json"
        batch_path.write_text(
            json.dumps(batch_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        paths.append(batch_path)

    log.info(
        "Split pending_notes into %d batch(es) (total %d chars, budget %d/batch)",
        len(batches), total_chars, max_chars_per_batch,
    )
    print(f"\nSplit into {len(batches)} batch(es):")
    for i, p in enumerate(paths, 1):
        n_ch = len(batches[i - 1])
        n_chars = sum(c["char_count"] for c in batches[i - 1])
        print(f"  {p.name}: {n_ch} chapters, {n_chars} chars")
    print("\nAsk Claude Code to generate each batch (parallel subagents OK, cap ~3 at once),")
    print('each writing to notes_results_batch{N}.json, then run:')
    print("  python pipeline/run_pipeline.py merge-notes --book-id \"<id>\" --batches " + str(len(batches)))
    return paths


def merge_notes_results(book_id: str, num_batches: int) -> Path:
    """
    Merge notes_results_batch1.json..batchN.json (each in the same
    {book_id, book_summary, chapters, concept_cards} shape as a normal
    notes_results.json) into a single NOTES_RESULTS_FILE ready for
    apply_notes(). Chapters are concatenated and sorted by chapter_num.
    Concept cards are deduped by title (first occurrence wins — later
    batches redefining the same concept are dropped, not overwritten,
    since parallel subagents can't see each other's output while working).
    """
    all_chapters: list[dict] = []
    all_cards: list[dict] = []
    seen_titles: set[str] = set()
    summaries: list[str] = []
    dropped_duplicate_cards = 0

    for i in range(1, num_batches + 1):
        batch_result_path = PIPELINE_DIR / f"notes_results_batch{i}.json"
        if not batch_result_path.exists():
            raise FileNotFoundError(f"Missing batch result: {batch_result_path}")
        d = json.loads(batch_result_path.read_text(encoding="utf-8"))
        all_chapters.extend(d.get("chapters", []))
        if d.get("book_summary"):
            summaries.append(d["book_summary"])
        for c in d.get("concept_cards", []):
            if c["title"] in seen_titles:
                dropped_duplicate_cards += 1
                continue
            seen_titles.add(c["title"])
            all_cards.append(c)

    all_chapters.sort(key=lambda c: c["chapter_num"])
    merged = {
        "book_id": book_id,
        # if no single batch wrote a whole-book summary, concatenate the
        # per-batch summaries as a stand-in; a human/Claude can tighten it later
        "book_summary": summaries[0] if len(summaries) == 1 else " ".join(summaries),
        "chapters": all_chapters,
        "concept_cards": all_cards,
    }
    NOTES_RESULTS_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(
        "Merged %d batch(es) for %s: %d chapters, %d concept cards (%d duplicate titles dropped)",
        num_batches, book_id, len(all_chapters), len(all_cards), dropped_duplicate_cards,
    )
    print(f"\nMerged {num_batches} batch(es) -> {NOTES_RESULTS_FILE}")
    print(f"  {len(all_chapters)} chapters, {len(all_cards)} concept cards ({dropped_duplicate_cards} duplicate titles dropped)")
    return NOTES_RESULTS_FILE


# ---------------------------------------------------------------------------
# apply_notes
# ---------------------------------------------------------------------------

def apply_notes(results_path: Path = NOTES_RESULTS_FILE) -> bool:
    if not results_path.exists():
        log.error("Notes results not found: %s", results_path)
        return False

    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("Cannot parse notes results: %s", e)
        return False

    book_id = data.get("book_id")
    manifest = load_manifest()
    entry = manifest["books"].get(book_id)
    if not entry:
        log.error("book_id not in manifest: %s", book_id)
        return False

    classification = entry.get("classification", {})
    chapters_data = data.get("chapters", [])
    concepts_dir = VAULT_ROOT / "20_Concepts"
    concepts_dir.mkdir(exist_ok=True)

    # Concepts that will actually have a card (this run's new cards, plus any
    # already existing from prior books) — used to avoid wikilinking chapter
    # key_concepts that were never turned into a card (a recurring source of
    # broken links, since key_concepts often includes people/places that this
    # pipeline deliberately doesn't card).
    new_card_titles = {_safe_title(c["title"]) for c in data.get("concept_cards", [])}
    known_concepts = new_card_titles | {p.stem for p in concepts_dir.glob("*.md")}

    # Re-apply guard: if this book already went through Phase 2 before (status
    # already notes_generated), a prior run may have left concept cards behind
    # that this run's notes_results.json no longer produces — e.g. an earlier
    # partial/truncated run (old chapter cap, batch failure) generated cards
    # under slightly different titles that a later full run doesn't repeat.
    # apply_notes() only ever creates/overwrites cards, it never deletes, so
    # these silently pile up as orphaned near-duplicates (see 2026-08 vault
    # audit: 9 books double-applied, 44 concept cards for one book alone).
    # We don't auto-delete — a human may have hand-edited an old card — but we
    # surface the list loudly, both on stdout and in the activity log, so the
    # gap is visible the moment it's created instead of months later.
    if entry.get("status") == "notes_generated":
        source_pat = re.compile(r'source_book:\s*"\[\[(.*?)\]\]"')
        book_title_guess = classification.get("title") or book_id
        existing_for_book = []
        for p in concepts_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            m = source_pat.search(text)
            if m and m.group(1) == book_title_guess:
                existing_for_book.append(p.stem)
        stale = sorted(set(existing_for_book) - new_card_titles)
        if stale:
            print(f"  [warn]     re-applying to a book already marked notes_generated;")
            print(f"             {len(stale)} existing concept card(s) are NOT in this run's output")
            print(f"             (may be orphans from a prior partial/duplicate run — review manually):")
            for t in stale:
                print(f"               - {t}")
            record_book_action("stale_concepts_on_reapply", book_id, {"titles": stale})

    # 1. Update 書籍筆記 in 10_Books/ (create if deleted or missing)
    if entry.get("obsidian_card"):
        card_path = Path(entry["obsidian_card"])
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_text(
            _render_book_notes(entry, classification, chapters_data, data.get("book_summary", ""), known_concepts),
            encoding="utf-8",
        )
        action = "Created" if not card_path.exists() else "Updated"
        print(f"  [notes]    {action}: {card_path.name}")

    # 2. Concept cards in 20_Concepts/ (no separate book card)
    # Use the book note's actual filename (not book_id) for the source_book
    # wikilink target — book_id can diverge from the real book_id when the
    # original filename contained spaces that got normalised in the manifest key.
    book_title = card_path.stem if entry.get("obsidian_card") else book_id
    created = 0
    for c in data.get("concept_cards", []):
        safe_title = _safe_title(c["title"])
        cc_path = concepts_dir / f"{safe_title}.md"
        if not cc_path.exists():
            cc_path.write_text(_render_concept_card(c, book_title, known_concepts), encoding="utf-8")
            created += 1
    if created:
        print(f"  [concepts]  {created} concept card(s) created")

    # 3. Manifest update
    update_book(book_id, {"status": "notes_generated"})
    record_book_action("notes_applied", book_id, {
        "chapters": len(chapters_data), "concepts": created,
    })
    print(f"  [ok] {book_id}: notes_generated")
    return True


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_book_notes(entry: dict, classification: dict, chapters: list[dict], book_summary: str, known_concepts: set[str] | None = None) -> str:
    title = classification.get("title") or Path(entry.get("epub_path", "")).stem
    author = classification.get("author") or entry.get("author", "")
    category = classification.get("category") or entry.get("category", "")
    sub_cat_yaml = json.dumps(classification.get("sub_categories", []), ensure_ascii=False)
    series = classification.get("series", "")
    volume = classification.get("volume")
    core_premise = classification.get("core_premise", "")
    tags = ["#type/book"] + classification.get("tags", [])
    tags_yaml = "\n".join(f'  - "{t}"' for t in tags)
    today = date.today().isoformat()

    series_line = f'series: "{series}"\n' if series else ""
    volume_line = f"volume: {volume}\n" if volume is not None else ""

    # Use Phase 2 book_summary as primary; fall back to Phase 1 toc_summary
    summary_text = book_summary or classification.get("toc_summary", "")

    # Only concepts that actually have (or will have) a card get wikilinked;
    # everything else renders as plain text so it can't become a broken link.
    def _link_or_plain(name: str) -> str:
        safe = _safe_title(name)
        return f"[[{safe}]]" if known_concepts is None or safe in known_concepts else name

    chapter_sections = []
    seen_concepts: set[str] = set()
    all_concepts: list[str] = []
    for ch in chapters:
        quotes_raw = ch.get("key_quotes", [])
        quotes = "\n".join(
            "\n".join(f"> {line}" for line in q.split("\n")) for q in quotes_raw
        )
        concepts_raw = ch.get("key_concepts", [])
        concepts = "\n".join(f"- {_link_or_plain(c)}" for c in concepts_raw)
        chapter_sections.append(
            f"### {ch['title']}\n\n"
            f"#### 摘要\n{ch.get('summary', '')}\n\n"
            f"#### 重點擷取\n{quotes if quotes else '*（無）*'}\n\n"
            f"#### 關鍵概念\n{concepts if concepts else '*（無）*'}\n\n"
            f"#### 我的想法\n\n\n---"
        )
        for c in concepts_raw:
            if c not in seen_concepts:
                all_concepts.append(c)
                seen_concepts.add(c)

    concepts_links = "\n".join(f"- {_link_or_plain(c)}" for c in all_concepts) or "*（無）*"
    linkable_concepts = [_safe_title(c) for c in all_concepts if known_concepts is None or _safe_title(c) in known_concepts]

    return (
        f"---\n"
        f'title: "{title}"\n'
        f'author: "{author}"\n'
        f'category: "{category}"\n'
        f"sub_categories: {sub_cat_yaml}\n"
        f"{series_line}"
        f"{volume_line}"
        f"tags:\n{tags_yaml}\n"
        f'core_premise: "{core_premise}"\n'
        f'source_epub: "{entry.get("epub_path", "")}"\n'
        f'source_md: "{entry.get("md_path", "")}"\n'
        f'date_added: "{today}"\n'
        f'status: "notes_generated"\n'
        f"---\n\n"
        f"## 核心前提\n{core_premise}\n\n"
        f"## 目錄摘要\n{summary_text}\n\n"
        f"---\n\n"
        f"## 章節筆記\n\n"
        + "\n\n".join(chapter_sections)
        + f"\n\n## 全書概念連結\n{concepts_links}\n\n"
        + f"## MOC 連結建議\n- 可加入：[[_{category}_MOC]]\n- 相關概念：{'、'.join(f'[[{c}]]' for c in linkable_concepts[:5]) or '*（無）*'}\n\n"
        + "## 整體心得\n"
    )


def _render_concept_card(concept: dict, book_id: str, known_concepts: set[str] | None = None) -> str:
    title = concept.get("title", "")
    definition = concept.get("definition", "")
    source_quote = concept.get("source_quote", "")
    quote_block = "\n".join(f"> {line}" for line in source_quote.split("\n"))
    related_raw = concept.get("related_concepts", [])
    related = "\n".join(
        f"- [[{_safe_title(r)}]]" if known_concepts is None or _safe_title(r) in known_concepts else f"- {r}"
        for r in related_raw
    )
    today = date.today().isoformat()

    return (
        f"---\n"
        f'title: "{title}"\n'
        f"tags:\n"
        f'  - "#type/concept"\n'
        f'source_book: "[[{book_id}]]"\n'
        f'date_added: "{today}"\n'
        f"---\n\n"
        f"## 定義\n{definition}\n\n"
        f"## 原文\n{quote_block}\n\n"
        f"## 相關概念\n{related or '*（無）*'}\n\n"
        f"## 我的理解\n"
    )
