"""
Phase 2: Chapter-by-chapter book note generation.

Workflow:
  1. prepare_notes(book_id) → writes pending_notes.json with chapter content
     (uses EPUB directly for accurate chapter structure; MD is fallback)
  2. Claude Code reads pending_notes.json, generates notes_results.json
  3. apply_notes() → fills 10_Books/ note, creates 20_Concepts/ concept cards
"""
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

from config import PIPELINE_DIR, VAULT_ROOT
from logger import get_logger
from activity import record_book_action
from manifest import load_manifest, update_book

# The converter's EPUB reader tolerates missing manifest files and resolves
# nested/relative TOC entries; slicing reuses it instead of a second reader.
_SRC_DIR = PIPELINE_DIR.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

log = get_logger("notes")

PENDING_NOTES_FILE = PIPELINE_DIR / "pending_notes.json"
NOTES_RESULTS_FILE = PIPELINE_DIR / "notes_results.json"
MIN_CHAPTER_CHARS = 200
# Not a cut-off: a chapter longer than this is split again (TOC sub-entries,
# then headings, then paragraph boundaries). No text is ever dropped.
MAX_CHARS_PER_CHAPTER = 40000
# Re-split pieces smaller than this are packed together with their neighbours.
PACK_MIN = 3000
# Text before the first TOC sub-entry shorter than this means the file's own
# TOC entry is a part title ('第一部' + an epigraph), not a chapter.
PART_TITLE_MAX = 500


def _safe_title(title: str) -> str:
    """Filename-safe concept title. Must be used for BOTH the card's filename
    and every wikilink that points at it — using the raw title for one and
    this for the other silently produces a broken link (e.g. "TCP/IP..." ->
    file "TCPIP....md" but link text still "[[TCP/IP...]]")."""
    return re.sub(r'[\\/:*?"<>|]', "", title)


# ---------------------------------------------------------------------------
# Chapter slicing
# ---------------------------------------------------------------------------

# Each source document (an EPUB spine file, or an MD section between '---'
# lines) becomes text lines plus split points {line index: (rank, title)}.
# rank is the TOC depth for TOC entries and _HEADING_RANK + level for
# headings, so a lower rank is a bigger boundary. Pieces are only ever cut at
# line boundaries and re-joined with "\n"; every document is checked to come
# back whole (the old slicer silently kept the first 40000 characters).

_HEADING_RANK = 100
_FILE_RANK = 200  # start of an untitled file joined to the previous chapter
_SPLIT_MARK = "\x00SPLIT{}\x00"

# Notes / bibliography / index at the back of a book: kept out of the chapters
# to summarise, listed in the report instead.
# The whole title must be made of these words ('參考書目及注釋', '附錄2：網路資源與延伸
# 閱讀'); '參考文獻的寫法' or '延伸閱讀 某人的自傳' are chapters.
_BM_WORD = (r"(注釋|註釋|注解|註解|附註|附注|追記|注|註|參考文獻|參考書目|參考資料|參考材料|參考資源|參考書籍"
            r"|徵引書目|引文出處|人名索引|中文索引|英文索引|名詞索引|參考|書目|索引"
            r"|延伸閱讀|進階閱讀|推薦閱讀|推薦書單|資料來源|引用書目|引用文獻|引用資料|資料"
            r"|網路資源|研究|縮寫說明)")
_BACK_MATTER_TITLE = re.compile(
    rf"^(附錄[\d０-９一二三四五六七八九十]*[：:]?)?(主要|章節)?{_BM_WORD}((與|及|和|、|之)?{_BM_WORD})*(精選)?$"
)
_BACK_MATTER_TITLE_EN = re.compile(
    r"^(selected )?(notes|endnotes|bibliography|references|index|sources|further reading)$", re.I)
_BACK_MATTER_FROM = 0.5  # only in the second half of the book


def _is_back_matter(title: str | None, start_ratio: float) -> bool:
    if not title or start_ratio < _BACK_MATTER_FROM:
        return False
    zh = re.sub(r"[\s∣|｜【】\[\]（）()]", "", title)
    en = re.sub(r"[^a-z ]", "", title.lower()).strip()
    return bool(_BACK_MATTER_TITLE.match(zh) or _BACK_MATTER_TITLE_EN.match(en))


# Notes at the end of a chapter file ('<p class="footnote">' blocks after the
# body). Bare class 'note' and <aside> are not signals: books use them for
# sidebars and pull quotes.
_NOTE_MARK = "\x00NOTES\x00"
_NOTE_TYPE = re.compile(r"\b(footnotes?|endnotes?|rearnotes?)\b")
_NOTE_ROLE = re.compile(r"\bdoc-(footnote|endnotes?)\b")
_NOTE_CLASS = re.compile(r"(foot|end|rear)notes?|^fn(\d+)?$|^fn[-_]\d+$|^zhu(shi|si)", re.I)
_NOTE_ID = re.compile(r"^(foot|fn|note|footnote|endnote)[-_]?\d+$", re.I)
_NOTE_BLOCKS = ["p", "div", "li", "dt", "dd", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "td"]


def _is_note_block(tag, root) -> bool:
    """tag or an ancestor (below root) carries a footnote/endnote signal."""
    while tag is not None and tag is not root:
        attrs = getattr(tag, "attrs", None) or {}
        et = attrs.get("epub:type") or ""
        role = attrs.get("role") or ""
        cls = attrs.get("class") or []
        if isinstance(et, list):
            et = " ".join(et)
        if isinstance(cls, str):
            cls = cls.split()
        if (_NOTE_TYPE.search(et) or _NOTE_ROLE.search(role)
                or any(_NOTE_CLASS.search(c) for c in cls) or _NOTE_ID.match(attrs.get("id") or "")):
            return True
        tag = tag.parent
    return False


def _mark_note_tail(root) -> int | None:
    """Insert _NOTE_MARK before the run of note blocks that ends the file and
    return how many characters those blocks hold (None: no such run). Only a
    run reaching the end counts: a note block followed by body text is left
    alone."""
    leaves = [b for b in root.find_all(_NOTE_BLOCKS)
              if b.get_text(strip=True) and not any(x.get_text(strip=True) for x in b.find_all(_NOTE_BLOCKS))]
    k = len(leaves)
    while k > 0 and _is_note_block(leaves[k - 1], root):
        k -= 1
    if k == len(leaves):
        return None
    from bs4 import NavigableString
    leaves[k].insert_before(NavigableString(_NOTE_MARK))
    return sum(len(b.get_text("\n", strip=True)) + 1 for b in leaves[k:])


def _chars(lines: list[str], a: int, b: int) -> int:
    return sum(len(l) for l in lines[a:b]) + max(b - a - 1, 0)


def _ends_sentence(line: str) -> bool:
    from cleaner import _ends_sentence as ends
    return ends(line)


def _epub_doc_lines(doc):
    """(lines, points, lead_entry, original_text) for one spine document."""
    from bs4 import NavigableString
    from cleaner import EpubCleaner, HEADING_TAGS, CONTAINER_TAGS, NO_HEADING_INSIDE

    cleaner = EpubCleaner(doc.content)
    soup = cleaner.soup
    for tag in soup(["script", "style"]):
        tag.decompose()
    root = soup.body or soup
    original = root.get_text("\n", strip=True)

    marks: dict[str, tuple[int, str]] = {}
    used: set[int] = set()

    def heading_run_start(h):
        # '### 第一章' + '# 章名' is one title: cut before the first of the run
        while True:
            prev = h.find_previous_sibling()
            if prev is None or prev.name not in HEADING_TAGS:
                return h
            between = h.previous_sibling
            while between is not None and between is not prev:
                if isinstance(between, NavigableString) and between.strip():
                    return h
                between = between.previous_sibling
            h = prev

    def mark(node, rank, title):
        if node is root or id(node) in used:
            return node is root
        used.add(id(node))
        key = _SPLIT_MARK.format(len(marks))
        marks[key] = (rank, title)
        node.insert_before(NavigableString(key))
        return True

    lead = next((e for e in doc.toc_entries if not e.fragment), None)
    for i, entry in enumerate(doc.toc_entries):
        if not entry.fragment:
            continue
        anchor = soup.find(id=entry.fragment) or soup.find(attrs={"name": entry.fragment})
        if anchor is None:
            if lead is None and i == 0:
                lead = entry  # same rule as epub2md: points at the file itself
            continue
        heading = anchor if anchor.name in HEADING_TAGS else anchor.find_parent(HEADING_TAGS)
        if heading is not None:
            point = heading_run_start(heading)
        elif anchor.name in NO_HEADING_INSIDE or anchor.find_parent(NO_HEADING_INSIDE):
            continue
        elif anchor.name in CONTAINER_TAGS and anchor.get_text(strip=True):
            point = anchor
        elif cleaner._has_text_before(anchor) or not cleaner._previous_text_ends_sentence(anchor):
            continue  # mid-sentence anchor: cutting here would split a sentence
        else:
            point = anchor
        if mark(point, max(entry.depth, 1), entry.title) and point is root and lead is None:
            lead = entry

    for h in root.find_all(HEADING_TAGS):
        if h.find_parent(NO_HEADING_INSIDE):
            continue
        start = heading_run_start(h)
        title = start.get_text(strip=True)
        if title:
            mark(start, _HEADING_RANK + int(start.name[1]) if start.name[1:].isdigit() else _HEADING_RANK + 6, title)

    note_chars = _mark_note_tail(root)
    lines: list[str] = []
    points: dict[int, tuple[int, str]] = {}
    note_start = None
    for line in root.get_text("\n", strip=True).split("\n"):
        if line == _NOTE_MARK:
            note_start = len(lines)
        elif line in marks:
            idx, (rank, title) = len(lines), marks[line]
            if idx not in points or rank < points[idx][0]:
                points[idx] = (rank, title)
        else:
            lines.append(line)
    points = {i: p for i, p in points.items() if i < len(lines)}
    if note_start is not None:
        if _chars(lines, note_start, len(lines)) + 1 > note_chars + 50:
            note_start = None  # body text outside the note blocks follows them
        else:
            # the '注釋' heading right above the notes goes with them
            if note_start > 0 and _is_back_matter(lines[note_start - 1], 1.0):
                note_start -= 1
            if _chars(lines, 0, note_start) < MIN_CHAPTER_CHARS:
                note_start = 0  # a notes file with a short heading on top
    return lines, points, lead, original, note_start


def _md_section_lines(section: str):
    lines = section.split("\n")
    points = {}
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            points[i] = (_HEADING_RANK + len(m.group(1)), m.group(2).strip())
    return lines, points


def _top_cuts(lines, points, lead_title, base_rank):
    """Chapter starts in one document: [(line index, title)].
    The document start is a chapter start only when it has a title (its own
    TOC entry, or a heading at the top). Text with no title is the rest of the
    previous chapter (books often split one chapter over several files)."""
    if not lines:
        return []
    toc_inner = sorted(i for i, (r, _) in points.items() if r < _HEADING_RANK and i > 0)
    if base_rank is not None and toc_inner and _chars(lines, 0, toc_inner[0]) < PART_TITLE_MAX:
        # the file's own entry is only a part title ('第一部') over the chapters inside
        base_rank = max(base_rank, min(points[i][0] for i in toc_inner))
    cuts = [(i, points[i][1]) for i in toc_inner
            if base_rank is not None and points[i][0] <= base_rank]
    if cuts and _chars(lines, 0, len(lines)) / (len(cuts) + 1) < PACK_MIN:
        # A flat TOC of many short entries (a quick-reference book): keep the
        # file as one chapter rather than hundreds of 200-character ones.
        cuts = []
    title = lead_title
    if title is None and 0 in points:
        title = points[0][1]
    if title is None:
        end0 = cuts[0][0] if cuts else len(lines)
        heads = [i for i in sorted(points) if i < end0 and _chars(lines, 0, i) < MIN_CHAPTER_CHARS]
        title = points[heads[0]][1] if heads else None
    return ([(0, title)] if title is not None else []) + cuts


def _merge_short(lines, segs):
    """Pieces under MIN_CHAPTER_CHARS (a part title page, a one-line intro)
    are joined to the next piece, or the previous one if last. A short
    bibliography stays back matter, and a short body piece right before the
    back matter goes to the previous chapter, not into the back matter. The
    last piece of the book (a colophon after the bibliography) still goes
    with whatever comes before it."""
    if len(segs) < 2:
        return segs
    total = _chars(lines, 0, len(lines)) or 1

    def back(seg):
        return _is_back_matter(seg[0], _chars(lines, 0, seg[1]) / total)

    out = []
    pending = None
    for seg in segs:
        if pending is not None:
            if back(seg) and not back(pending):
                if out:
                    out[-1] = [out[-1][0], out[-1][1], pending[2]] + out[-1][3:]
                else:
                    out.append(pending)
            else:
                title = pending[0] if seg[0] and pending[0] and seg[0].startswith(pending[0] + "／") else (seg[0] or pending[0])
                seg = [title, pending[1], seg[2]] + seg[3:]
            pending = None
        if _chars(lines, seg[1], seg[2]) < MIN_CHAPTER_CHARS and not back(seg):
            pending = seg
            continue
        out.append(seg)
    if pending is not None:
        if out:
            out[-1] = [out[-1][0], out[-1][1], pending[2]] + out[-1][3:]
        else:
            out.append(pending)
    return out


def _paragraph_split(lines, a, b, limit):
    """Cut [a, b) at line boundaries into pieces of at most `limit` chars,
    preferring a line that ends a sentence once a piece reaches its share."""
    n = math.ceil(_chars(lines, a, b) / limit)
    target = _chars(lines, a, b) / n
    bounds, start, size = [a], a, 0
    for i in range(a, b):
        size += len(lines[i]) + (1 if i > start else 0)
        if i + 1 >= b:
            break
        nxt = size + 1 + len(lines[i + 1])
        if (size >= target and _ends_sentence(lines[i])) or nxt > limit:
            bounds.append(i + 1)
            start, size = i + 1, 0
    bounds.append(b)
    return list(zip(bounds, bounds[1:]))


def _pack(lines, points, title, spans, limit):
    """Group consecutive spans until a group reaches PACK_MIN (never past
    `limit`). Titles: 'parent／sub', or 'parent／first～last' for a group."""
    groups, cur = [], []
    for span in spans:
        # a group under MIN_CHAPTER_CHARS (a lone heading before a long
        # section) goes with the next span even past `limit`; _refine splits
        # that group again
        if cur and (_chars(lines, cur[0][0], cur[-1][1]) >= PACK_MIN
                    or (_chars(lines, cur[0][0], span[1]) > limit
                        and _chars(lines, cur[0][0], cur[-1][1]) >= MIN_CHAPTER_CHARS)):
            groups.append(cur)
            cur = []
        cur.append(span)
    if cur:
        if groups and _chars(lines, cur[0][0], cur[-1][1]) < MIN_CHAPTER_CHARS \
                and _chars(lines, groups[-1][0][0], cur[-1][1]) <= limit:
            groups[-1] += cur
        else:
            groups.append(cur)

    a = spans[0][0]
    def sub(x):
        return None if x == a else points[x][1]
    out = []
    for g in groups:
        first, last = sub(g[0][0]), sub(g[-1][0])
        # a group that opens with the chapter's own intro keeps the chapter title
        name = first if len(g) == 1 or first is None or last is None else f"{first}～{last}"
        if name is None:
            t = title
        else:
            t = f"{title}／{name}" if title else name
        out.append([t, g[0][0], g[-1][1]])
    return out


def _refine(lines, points, title, a, b, limit, how=None):
    """Split [a, b) further while it is longer than `limit`.
    Returns [[title, start, end, how]] where how is None (not split) or
    'toc_sub' / 'heading' / 'paragraph'."""
    if _chars(lines, a, b) <= limit:
        return [[title, a, b, how]]
    inner = {i: p for i, p in points.items() if a < i < b}
    for rank in sorted({r for r, _ in inner.values()}):
        cuts = sorted(i for i, (r, _) in inner.items() if r == rank)
        bounds = [a] + cuts + [b]
        pieces = _pack(lines, points, title, list(zip(bounds, bounds[1:])), limit)
        if len(pieces) < 2:
            continue  # every cut at this rank only made tiny pieces: try the next rank
        sub_how = "toc_sub" if rank < _HEADING_RANK else "heading"
        out = []
        for t, x, y in pieces:
            out += _refine(lines, points, t, x, y, limit, sub_how)
        return out
    parts = _paragraph_split(lines, a, b, limit)
    if len(parts) == 1:
        return [[title, a, b, how]]  # one line longer than the limit: left whole
    return [[f"{title}（{k}/{len(parts)}）" if title else None, x, y, "paragraph"]
            for k, (x, y) in enumerate(parts, 1)]


def _cut_out_notes(lines, segs, notes, total, limit):
    """Take trailing-note ranges out of the chapters: [(title, ranges, is_notes)].
    A chapter spread over several files, each ending in notes, keeps its body
    pieces together as one chapter of several ranges (as long as they fit in
    `limit`). A body piece under MIN_CHAPTER_CHARS next to notes (an image
    caption) goes with the notes."""
    out = []
    for title, a, b in segs:
        parts, x = [], a
        if not _is_back_matter(title, _chars(lines, 0, a) / total):
            for na, nb in notes:
                na, nb = max(na, a), min(nb, b)
                if na >= nb:
                    continue
                if x < na:
                    parts.append([x, na, False])
                parts.append([na, nb, True])
                x = nb
        if not parts:
            out.append((title, [(a, b)], False))
            continue
        if x < b:
            parts.append([x, b, False])
        for p in parts:
            if not p[2] and _chars(lines, p[0], p[1]) < MIN_CHAPTER_CHARS:
                p[2] = True
        merged = []
        for p in parts:  # join neighbours of the same kind
            if merged and merged[-1][2] == p[2]:
                merged[-1][1] = p[1]
            else:
                merged.append(p)
        groups, cur, size = [], [], 0
        for x, y, is_notes in merged:
            if is_notes:
                out.append((title, [(x, y)], True))
                continue
            n = _chars(lines, x, y)
            if cur and size + 1 + n > limit:
                groups.append(cur)
                cur, size = [], 0
            size += n + (1 if cur else 0)
            cur.append((x, y))
        if cur:
            groups.append(cur)
        for k, g in enumerate(groups, 1):
            out.append((f"{title}（{k}/{len(groups)}）" if title and len(groups) > 1 else title, g, False))
    return out


def _assemble(docs, limit=MAX_CHARS_PER_CHAPTER, source="epub"):
    """docs: [(lines, points, lead_title, base_rank, original_text[, note_start])].
    note_start: line index where the file's trailing notes begin (None: none).
    Returns (chapters, report)."""
    report = {
        "source": source, "documents": len(docs),
        "skipped_empty_documents": 0, "note_tails": 0, "note_tail_chars": 0,
        "toc_resplit_documents": 0, "toc_resplit_chapters": 0,
        "oversize_chapters": 0,
        "oversize_split": {"toc_sub": 0, "heading": 0, "paragraph": 0},
        "still_oversize": [], "back_matter": [], "self_check": True,
        "original_chars": 0, "chapter_chars": 0, "back_matter_chars": 0,
    }
    # The whole book as one run of lines, so a chapter can span files.
    lines: list[str] = []
    points: dict[int, tuple[int, str]] = {}
    starts: list[tuple[int, str | None]] = []
    kept: list[str] = []
    notes: list[tuple[int, int]] = []  # trailing-note line ranges
    pending_title = None  # TOC title of an empty chapter-title page (an image)
    absorb = False  # previous kept file was a short titled page
    for d, (doc_lines, doc_points, lead_title, base_rank, original, *rest) in enumerate(docs):
        note_start = rest[0] if rest else None
        report["original_chars"] += len(original)
        if "\n".join(doc_lines) != original:
            report["self_check"] = False
            log.error("slice self-check: document %d text changed while marking split points", d)
        if not original.strip():
            # Only empty files are skipped; a short one (a part title page, a
            # 150-character section of an illustrated book) is book text too.
            report["skipped_empty_documents"] += 1
            if lead_title:
                pending_title = lead_title
            continue
        off = len(lines)
        cuts = _top_cuts(doc_lines, doc_points, lead_title or pending_title, base_rank)
        if absorb and lead_title is None and cuts and cuts[0][0] == 0:
            cuts = cuts[1:]  # body of the title page before it: same chapter
        # A titled page this short is the chapter's title page (title +
        # epigraph); the next untitled file is that chapter's body. A short
        # untitled file in between (an image caption) does not end that.
        absorb = (bool(lead_title) and len(original) < PART_TITLE_MAX) or (
            absorb and lead_title is None and not cuts and len(original) < MIN_CHAPTER_CHARS)
        pending_title = None
        if note_start is not None and note_start < len(doc_lines):
            notes.append((off + note_start, off + len(doc_lines)))
        if sum(1 for i, _ in cuts if i > 0) > 0:
            report["toc_resplit_documents"] += 1
            report["toc_resplit_chapters"] += len(cuts)
        lines += doc_lines
        points.update({off + i: p for i, p in doc_points.items()})
        if off > 0 and not (cuts and cuts[0][0] == 0) and off not in points:
            points[off] = (_FILE_RANK, None)
        starts += [(off + i, t) for i, t in cuts]
        kept.append(original)

    if not lines:
        return [], report
    if not starts or starts[0][0] != 0:
        starts.insert(0, (0, None))
    bounds = [i for i, _ in starts] + [len(lines)]
    segs = _merge_short(lines, [[t, a, b] for (a, t), b in zip(starts, bounds[1:])])

    total = _chars(lines, 0, len(lines)) or 1
    chapters, pieces = [], []
    for title, ranges, is_notes in _cut_out_notes(lines, segs, notes, total, limit):
        a, b = ranges[0][0], ranges[-1][1]
        size = _chars(lines, a, b)
        if is_notes:
            report["back_matter"].append({"title": f"{title or '（無標題）'}：章末注釋", "char_count": size,
                                          "kind": "chapter_notes"})
            report["back_matter_chars"] += size
            report["note_tails"] += 1
            report["note_tail_chars"] += size
            pieces.append((a, b))
            continue
        if _is_back_matter(title, _chars(lines, 0, a) / total):
            report["back_matter"].append({"title": title, "char_count": size})
            report["back_matter_chars"] += size
            pieces.append((a, b))
            continue
        if len(ranges) > 1:
            # body pieces around notes, already packed under `limit`
            refined = [[title, ranges, None]]
        else:
            refined = [[t, [(x, y)], how] for t, x, y, how in _refine(lines, points, title, a, b, limit)]
        if len(refined) > 1:
            report["oversize_chapters"] += 1
            same = [r[0] for r in refined]
            if len(set(same)) < len(same):  # cut at untitled file starts
                for k, r in enumerate(refined):
                    if same.count(r[0]) > 1 and r[0]:
                        nth = same[:k + 1].count(r[0])
                        r[0] = f"{r[0]}（{nth}/{same.count(r[0])}）"
        for t, rs, how in refined:
            if how:
                report["oversize_split"][how] += 1
            content = "\n".join("\n".join(lines[x:y]) for x, y in rs)
            pieces += rs
            ch = {
                "chapter_num": len(chapters) + 1,
                "title": t or f"第 {len(chapters) + 1} 節",
                "char_count": len(content),
                "content": content,
            }
            if how:
                ch["split"] = how
            if len(content) > limit:
                report["still_oversize"].append({"title": ch["title"], "char_count": len(content)})
            chapters.append(ch)
            report["chapter_chars"] += len(content)

    # Chapters + back matter must tile the book exactly. A chapter can hold
    # several ranges (its notes taken out), so check in position order.
    pieces.sort()
    edges = [p for ab in pieces for p in ab]
    if not pieces or edges[0] != 0 or edges[-1] != len(lines) or any(
            edges[k] != edges[k + 1] for k in range(1, len(edges) - 1, 2)):
        report["self_check"] = False
        log.error("slice self-check: chapters do not cover the book contiguously")
    if "\n".join("\n".join(lines[x:y]) for x, y in pieces) != "\n".join(kept):
        report["self_check"] = False
        log.error("slice self-check: chapters do not re-join to the source text")
    return chapters, report


def _slice_from_epub(epub_path: Path) -> tuple[list[dict], dict]:
    """Slice an EPUB in spine order. A file holding several TOC chapters is cut
    at their anchors; a chapter over MAX_CHARS_PER_CHAPTER is split again."""
    try:
        from extractor import EpubExtractor
        extractor = EpubExtractor(str(epub_path))
        docs = []
        for doc in extractor.get_spine_documents():
            lines, points, lead, original, note_start = _epub_doc_lines(doc)
            toc_ranks = [r for r, _ in points.values() if r < _HEADING_RANK]
            base_rank = lead.depth if lead else (min(toc_ranks) if toc_ranks else None)
            docs.append((lines, points, lead.title if lead else None, base_rank, original, note_start))
        return _assemble(docs, source="epub")
    except Exception as e:
        log.error("EPUB parsing failed: %s", e)
        return [], {}


def _slice_from_md(md_text: str) -> tuple[list[dict], dict]:
    """Fallback: slice converted MD file by --- separators; a section over
    MAX_CHARS_PER_CHAPTER is split at its headings, then paragraphs."""
    docs = []
    for section in re.split(r"\n---+\n", md_text):
        section = section.strip()
        # only the converter's own front matter block ('# 書名：…'); a chapter
        # titled '書名頁' or '作者序' is book text
        if not section or re.match(r"^#\s*(書名|作者|轉換日期)[：:]", section):
            continue
        if not re.sub(r"\[圖片[^\]]*\]", "", section).strip():
            continue  # image placeholders only
        lines, points = _md_section_lines(section)
        docs.append((lines, points, None, None, section))
    return _assemble(docs, source="md")


def _print_slice_report(report: dict, chapters: list[dict]) -> None:
    o = report["oversize_split"]
    print(f"  切片自檢：{'通過' if report['self_check'] else '失敗'}"
          f"（原文 {report['original_chars']:,} 字 = 章節 {report['chapter_chars']:,}"
          f" + 書末附屬 {report['back_matter_chars']:,}，換行另計；空白檔略過 {report['skipped_empty_documents']} 個）")
    if report.get("note_tails"):
        print(f"  章末注釋移出章節（列在書末附屬）：{report['note_tails']} 段，共 {report['note_tail_chars']:,} 字")
    if report["toc_resplit_documents"]:
        print(f"  依 TOC 錨點重新分章：{report['toc_resplit_documents']} 個檔切成 {report['toc_resplit_chapters']} 章")
    if report["oversize_chapters"]:
        print(f"  超過 {MAX_CHARS_PER_CHAPTER:,} 字的 {report['oversize_chapters']} 章再拆，拆出：依 TOC 小節 {o['toc_sub']} 章、依標題 {o['heading']} 章、依段落 {o['paragraph']} 章")
    titled = [b for b in report["back_matter"] if b.get("kind") != "chapter_notes"]
    if titled:
        print(f"  書末附屬（不寫摘要，不放進 chapters）：{len(titled)} 段")
        for b in titled:
            print(f"    - {b['title']}（{b['char_count']:,} 字）")
    if report["still_oversize"]:
        print(f"  [warn] 仍超過上限（單一段落就超過，沒有可切的位置）：")
        for s in report["still_oversize"]:
            print(f"    - {s['title']}（{s['char_count']:,} 字）")


# ---------------------------------------------------------------------------
# prepare_notes
# ---------------------------------------------------------------------------

def prepare_notes(book_id: str, max_chapters: int | None = None, tag: str | None = None) -> Path | None:
    """tag: optional namespace so multiple books can run prepare-notes/split-notes/
    merge-notes in parallel without overwriting each other's fixed-name files
    (pending_notes.json etc). Omit for the original single-book behavior."""
    manifest = load_manifest()
    entry = manifest["books"].get(book_id)
    if not entry:
        log.error("book_id not found: %s", book_id)
        return None

    classification = entry.get("classification", {})
    md_path = Path(entry["md_path"]) if entry.get("md_path") else None
    epub_path = Path(entry["epub_path"]) if entry.get("epub_path") else None

    chapters, report, source_used = [], {}, "epub"

    # EPUB first: accurate chapter structure from spine + TOC
    if epub_path and epub_path.exists() and epub_path.suffix.lower() == ".epub":
        chapters, report = _slice_from_epub(epub_path)
        log.info("Sliced %d chapters from EPUB: %s", len(chapters), epub_path.name)

    # Fall back to MD if EPUB yields too few chapters
    if len(chapters) < 2 and md_path and md_path.exists():
        log.info("EPUB yielded %d chapter(s) — falling back to MD", len(chapters))
        chapters, report = _slice_from_md(md_path.read_text(encoding="utf-8", errors="ignore"))
        source_used = "md"

    if not chapters:
        log.error("No chapters found for: %s", book_id)
        return None
    if not report.get("self_check", False):
        log.error("Slice self-check failed for %s: chapters don't re-join to the source text; not writing", book_id)
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
        # back matter (notes, bibliography, index) is not summarised; titles
        # and sizes only, so the batches stay small
        "back_matter": report.get("back_matter", []),
        "slice_report": {k: v for k, v in report.items() if k != "back_matter"},
        "chapters": chapters,
    }

    out_path = PIPELINE_DIR / f"pending_notes_{tag}.json" if tag else PENDING_NOTES_FILE
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_book_action("notes_prepared", book_id, {
        "chapters": len(chapters), "source": source_used,
        "back_matter": len(report.get("back_matter", [])),
        "oversize_chapters": report.get("oversize_chapters", 0),
    })

    print(f"\nReady: {out_path}")
    print(f"  {len(chapters)} chapters ({source_used})")
    _print_slice_report(report, chapters)
    print("\nAsk Claude Code:")
    print(f'  "請讀 {out_path.relative_to(PIPELINE_DIR.parent)}，幫我生成書籍筆記，輸出到 pipeline/notes_results{"_" + tag if tag else ""}.json"')
    return out_path


# ---------------------------------------------------------------------------
# split_pending_notes / merge_notes_results — for books too large for one
# subagent context window. prepare_notes() no longer truncates chapters by
# default (whole book, every chapter); when the raw content is large, split
# into batches here, hand each batch to its own subagent, then merge their
# partial notes_results back into one file before apply_notes().
# ---------------------------------------------------------------------------

DEFAULT_MAX_CHARS_PER_BATCH = 150_000


def split_pending_notes(
    pending_path: Path | None = None,
    max_chars_per_batch: int = DEFAULT_MAX_CHARS_PER_BATCH,
    tag: str | None = None,
) -> list[Path]:
    """
    Split a prepared pending_notes.json into N batch files
    (pending_notes_batch1.json, batch2.json, ... or, with tag, the
    pending_notes_{tag}_batch{N}.json equivalents) if its total content
    exceeds max_chars_per_batch. Each batch keeps chapters contiguous
    (never splits a chapter across batches) and carries the same book-level
    metadata plus batch_num/total_batches for traceability.

    tag: same namespacing as prepare_notes()'s tag — lets multiple books run
    split-notes/merge-notes in parallel without clobbering each other's
    fixed-name batch files. Omit for the original single-book behavior.

    Returns the list of batch file paths (length 1 if no split was needed —
    the single path is still the (possibly tagged) pending_notes file itself,
    unchanged).
    """
    if pending_path is None:
        pending_path = (PIPELINE_DIR / f"pending_notes_{tag}.json") if tag else PENDING_NOTES_FILE
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
            **{k: v for k, v in data.items() if k not in ("chapters", "back_matter", "slice_report")},
            "batch_num": i,
            "total_batches": len(batches),
            "chapters": batch_chapters,
        }
        suffix = f"_{tag}_batch{i}" if tag else f"_batch{i}"
        batch_path = PIPELINE_DIR / f"pending_notes{suffix}.json"
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
    result_suffix = f"_{tag}_batch" if tag else "_batch"
    print("\nAsk Claude Code to generate each batch (parallel subagents OK, cap ~3 at once),")
    print(f'each writing to notes_results{result_suffix}{{N}}.json, then run:')
    tag_flag = f' --tag "{tag}"' if tag else ""
    print(f'  python pipeline/run_pipeline.py merge-notes --book-id "<id>" --batches {len(batches)}{tag_flag}')
    return paths


def merge_notes_results(book_id: str, num_batches: int, tag: str | None = None) -> Path:
    """
    Merge notes_results_batch1.json..batchN.json (or, with tag, the
    notes_results_{tag}_batch{N}.json equivalents — each in the same
    {book_id, book_summary, chapters, concept_cards} shape as a normal
    notes_results.json) into a single merged file ready for apply_notes().
    Chapters are concatenated and sorted by chapter_num. Concept cards are
    deduped by title (first occurrence wins — later batches redefining the
    same concept are dropped, not overwritten, since parallel subagents
    can't see each other's output while working).

    tag: same namespacing as prepare_notes()/split_pending_notes() — reads
    the tagged batch files and writes notes_results_{tag}.json instead of
    the fixed NOTES_RESULTS_FILE, so parallel books don't collide. Pass the
    returned path to `apply-notes --input <path>`. Omit tag for the original
    single-book behavior (writes NOTES_RESULTS_FILE, as before).
    """
    all_chapters: list[dict] = []
    all_cards: list[dict] = []
    seen_titles: set[str] = set()
    summaries: list[str] = []
    dropped_duplicate_cards = 0

    batch_suffix = f"_{tag}_batch" if tag else "_batch"
    for i in range(1, num_batches + 1):
        batch_result_path = PIPELINE_DIR / f"notes_results{batch_suffix}{i}.json"
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
    out_path = (PIPELINE_DIR / f"notes_results_{tag}.json") if tag else NOTES_RESULTS_FILE
    out_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(
        "Merged %d batch(es) for %s: %d chapters, %d concept cards (%d duplicate titles dropped)",
        num_batches, book_id, len(all_chapters), len(all_cards), dropped_duplicate_cards,
    )
    print(f"\nMerged {num_batches} batch(es) -> {out_path}")
    print(f"  {len(all_chapters)} chapters, {len(all_cards)} concept cards ({dropped_duplicate_cards} duplicate titles dropped)")
    if tag:
        print(f'  Apply with: python pipeline/run_pipeline.py apply-notes --input "{out_path}"')
    return out_path


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
# stale_review — companion to apply_notes()'s stale-concept-card warning.
# Ranks each pre-existing "orphan" card (title not in this run's output)
# against every card this run *did* produce, by textual similarity of both
# definition and source_quote. Exact-title matching alone misses reworded
# duplicates (see CLAUDE.md 孤兒卡review lesson, 2026-08-09) — this makes that
# comparison a reusable command instead of a hand-rolled script each time.
# Read-only: never edits or deletes any file. Merge/redirect decisions stay
# with a human (or Claude) reading the actual card content, not this script.
# ---------------------------------------------------------------------------

def stale_review(book_id: str, results_path: Path = NOTES_RESULTS_FILE, top_n: int = 3) -> list[dict]:
    from difflib import SequenceMatcher

    manifest = load_manifest()
    entry = manifest["books"].get(book_id, {})
    classification = entry.get("classification", {})
    book_title_guess = classification.get("title") or book_id

    data = json.loads(results_path.read_text(encoding="utf-8"))
    new_cards = {
        _safe_title(c["title"]): (c.get("definition", ""), c.get("source_quote", ""))
        for c in data.get("concept_cards", [])
    }

    concepts_dir = VAULT_ROOT / "20_Concepts"
    source_pat = re.compile(r'source_book:\s*"\[\[(.*?)\]\]"')
    def_pat = re.compile(r'## 定義\s*\n(.*?)(?=\n##|\Z)', re.S)
    quote_pat = re.compile(r'## 原文\s*\n>\s*(.*?)(?=\n##|\Z)', re.S)

    results = []
    for p in concepts_dir.glob("*.md"):
        if p.stem in new_cards:
            continue  # this run itself (re)wrote it — not a stale candidate
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = source_pat.search(text)
        if not (m and m.group(1) == book_title_guess):
            continue

        dm, qm = def_pat.search(text), quote_pat.search(text)
        old_def = dm.group(1).strip() if dm else ""
        old_quote = qm.group(1).strip() if qm else ""

        scored = []
        for nt, (ndef, nquote) in new_cards.items():
            r_def = SequenceMatcher(None, old_def, ndef).ratio()
            r_quote = SequenceMatcher(None, old_quote, nquote).ratio() if old_quote and nquote else 0.0
            scored.append({"score": max(r_def, r_quote), "def_score": r_def, "quote_score": r_quote,
                           "candidate_title": nt, "candidate_definition": ndef})
        scored.sort(key=lambda s: s["score"], reverse=True)

        results.append({
            "stale_title": p.stem,
            "stale_definition": old_def,
            "top_candidates": scored[:top_n],
        })

    results.sort(key=lambda r: r["top_candidates"][0]["score"] if r["top_candidates"] else 0, reverse=True)
    return results


def print_stale_review(book_id: str, results_path: Path = NOTES_RESULTS_FILE) -> None:
    rows = stale_review(book_id, results_path)
    if not rows:
        print(f"\n沒有找到《{book_id}》的孤兒卡候選（可能這本書不是重跑，或這次輸出涵蓋了全部既有標題）。")
        return
    print(f"\n=== 孤兒卡review候選：{book_id}（{len(rows)}張既有卡不在這次輸出中）===")
    print("依最高相似度分數排序，分數高不代表一定是重複，仍需人工讀原文確認再決定合併／保留。\n")
    for r in rows:
        print(f"[舊卡] {r['stale_title']}")
        print(f"  定義: {r['stale_definition'][:80]}")
        for c in r["top_candidates"]:
            print(f"    候選[def={c['def_score']:.2f} quote={c['quote_score']:.2f}] "
                  f"{c['candidate_title']}: {c['candidate_definition'][:60]}")
        print()


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
