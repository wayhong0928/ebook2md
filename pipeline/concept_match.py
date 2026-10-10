"""
Cross-book concept matching (read-only).

Phase 2 used to create every concept card in isolation, so the same idea
explained by two books ended up as two unrelated cards. This module lists,
for each card of one book, the most similar cards that come from *other*
books, so a human (or Claude) can decide: reuse the existing card (rename the
new card to the existing title; apply-notes then appends the new source), or
keep both and link them via related_concepts.

Two inputs:
  - a notes_results JSON (cards about to be created by apply-notes), or
  - a book id (cards already in 20_Concepts for that book; used for old books).

Similarity: half title score (see _title_score), half TF-IDF weighted
character-bigram cosine over title + definition + quote (scaled, capped at 1).
Bigrams suit CJK text without a tokenizer; IDF keeps filler bigrams such as
"一種" from dominating. A high score is only a candidate — read both cards.

Never writes to the vault.
"""
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from config import VAULT_ROOT

_SOURCE_INLINE = re.compile(r'^source_book:\s*"\[\[(.*?)\]\]"\s*$', re.M)
_SOURCE_BLOCK = re.compile(r'^source_book:[ \t]*\n((?:[ \t]+-[ \t]*"\[\[.*?\]\]"[ \t]*\n)+)', re.M)
_DEF = re.compile(r'## 定義\s*\n(.*?)(?=\n## |\Z)', re.S)
_QUOTE = re.compile(r'## 原文\s*\n(.*?)(?=\n## |\Z)', re.S)
_TITLE = re.compile(r'^title:\s*"(.*?)"\s*$', re.M)
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
TEXT_SCALE = 4.0


def card_sources(text: str) -> list[str]:
    """Book titles in a concept card's source_book field.

    Accepts the single form  source_book: "[[A]]"  and the list form
    source_book:\\n  - "[[A]]"\\n  - "[[B]]"  (written once a second book
    reuses the card)."""
    m = _SOURCE_INLINE.search(text)
    if m:
        return [m.group(1)]
    m = _SOURCE_BLOCK.search(text)
    if m:
        return re.findall(r'"\[\[(.*?)\]\]"', m.group(1))
    return []


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)  # blockquote markers
    text = re.sub(r"（\[\[.*?\]\]）", "", text)         # source tags under 原文
    return _NON_WORD.sub("", text)


def _bigrams(text: str) -> list[str]:
    s = _norm(text)
    if len(s) < 2:
        return [s] if s else []
    return [s[i:i + 2] for i in range(len(s) - 1)]


def _title_score(a: str, b: str, idf: dict | None = None) -> float:
    """1.0 for the same title; 0.5–1.0 when one title contains the other
    (scaled by length, so 醫療傷害/醫療傷害學 beats 性/可選擇性); otherwise
    IDF-weighted bigram Dice, so shared generic suffixes such as 效應 or
    症候群 count for little."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    short, long_ = sorted((na, nb), key=len)
    if len(short) >= 2 and short in long_:
        return 0.5 + 0.5 * len(short) / len(long_)
    ga, gb = set(_bigrams(a)), set(_bigrams(b))
    if not ga or not gb:
        return 0.0
    w = (lambda t: idf.get(t, 1.0)) if idf else (lambda t: 1.0)
    shared = sum(w(t) for t in ga & gb)
    return 2 * shared / (sum(w(t) for t in ga) + sum(w(t) for t in gb))


def load_cards(concepts_dir: Path) -> list[dict]:
    cards = []
    for p in sorted(concepts_dir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        tm, dm, qm = _TITLE.search(text), _DEF.search(text), _QUOTE.search(text)
        cards.append({
            "title": tm.group(1) if tm else p.stem,
            "file": p.stem,
            "sources": card_sources(text),
            "definition": dm.group(1).strip() if dm else "",
            "quote": qm.group(1).strip() if qm else "",
        })
    return cards


class _Index:
    """TF-IDF vectors of character bigrams for a fixed corpus of cards."""

    def __init__(self, docs: list[str]):
        grams = [Counter(_bigrams(d)) for d in docs]
        df = Counter()
        for g in grams:
            df.update(g.keys())
        n = len(docs)
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self.vecs = [self.vector_from_counts(g) for g in grams]

    def vector_from_counts(self, counts: Counter) -> dict:
        idf_default = math.log(len(self.idf) + 1) + 1
        v = {t: c * self.idf.get(t, idf_default) for t, c in counts.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def vector(self, text: str) -> dict:
        return self.vector_from_counts(Counter(_bigrams(text)))


def _cos(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def match(queries: list[dict], book_title: str, concepts_dir: Path | None = None,
          top_n: int = 5, min_score: float = 0.3) -> list[dict]:
    """For each query card, the top cards from other books.

    queries: dicts with title / definition / quote (or source_quote).
    book_title: the query book; cards that already list it are excluded.
    """
    concepts_dir = concepts_dir or (VAULT_ROOT / "20_Concepts")
    corpus = [c for c in load_cards(concepts_dir) if book_title not in c["sources"]]
    if not corpus:
        return []
    index = _Index([f'{c["title"]} {c["definition"]} {c["quote"]}' for c in corpus])
    title_df = Counter(t for c in corpus for t in set(_bigrams(c["title"])))
    title_idf = {t: math.log((len(corpus) + 1) / (n + 1)) + 1 for t, n in title_df.items()}

    out = []
    for q in queries:
        q_quote = q.get("quote") or q.get("source_quote", "")
        qv = index.vector(f'{q["title"]} {q.get("definition", "")} {q_quote}')
        scored = []
        for c, cv in zip(corpus, index.vecs):
            text = _cos(qv, cv)
            title = _title_score(q["title"], c["title"], title_idf)
            # bigram cosine of short definitions rarely exceeds 0.3; on real
            # cards 0.12+ already marks the same idea under another name
            score = 0.5 * title + 0.5 * min(1.0, TEXT_SCALE * text)
            if score >= min_score:
                scored.append({"score": round(score, 3), "title_score": round(title, 3),
                               "text_score": round(text, 3), "title": c["title"],
                               "file": c["file"], "sources": c["sources"],
                               "definition": c["definition"]})
        scored.sort(key=lambda s: s["score"], reverse=True)
        out.append({"title": q["title"], "definition": q.get("definition", ""),
                    "candidates": scored[:top_n]})
    out.sort(key=lambda r: r["candidates"][0]["score"] if r["candidates"] else 0, reverse=True)
    return out


def queries_from_results(results_path: Path) -> tuple[str, list[dict]]:
    data = json.loads(results_path.read_text(encoding="utf-8"))
    return data.get("book_id", ""), data.get("concept_cards", [])


def queries_from_book(book_title: str, concepts_dir: Path | None = None) -> list[dict]:
    concepts_dir = concepts_dir or (VAULT_ROOT / "20_Concepts")
    return [c for c in load_cards(concepts_dir) if book_title in c["sources"]]


def print_matches(rows: list[dict], book_title: str) -> None:
    hit = [r for r in rows if r["candidates"]]
    print(f"\n=== 跨書概念比對：{book_title}（{len(rows)} 張，{len(hit)} 張有其他書的候選）===")
    print("分數 = 標題相似與內文相似（定義＋原文，×4 封頂 1）各半。分數高只是候選，要讀兩張卡再決定沿用、連結或不理。\n")
    for r in hit:
        print(f"[本書] {r['title']}：{r['definition'][:70]}")
        for c in r["candidates"]:
            src = "、".join(c["sources"]) or "?"
            print(f"    {c['score']:.2f}（標題 {c['title_score']:.2f}／內文 {c['text_score']:.2f}）"
                  f"{c['title']}《{src}》：{c['definition'][:50]}")
        print()
