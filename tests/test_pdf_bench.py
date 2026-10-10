"""pdf2md on real book pages: present / absent / line / order checks.

The idea follows olmOCR-Bench (allenai/olmocr, olmocr/bench): instead of a
full reference text, each check states one fact a human read off the page
image, e.g. "this sentence is there, in one paragraph" or "the running head
is gone". The checks quote the owner's books, so they live in
tests/local_pdf_bench/cases.json, which is gitignored; without that file
every test here is skipped.

cases.json:
    {"books": {"<name>": {"pdf": "<path>", "checks": [
        {"id": "...", "type": "present", "text": "..."},         # inside one paragraph
        {"id": "...", "type": "absent", "text": "..."},          # nowhere in the book
        {"id": "...", "type": "line", "text": "..."},            # a whole line (heading or paragraph) of its own
        {"id": "...", "type": "no_line", "text": "..."},         # no line equal to it (page numbers, running heads)
        {"id": "...", "type": "order", "before": "...", "after": "..."},
        {"id": "...", "type": "max_lines", "regex": "...", "max": 0}  # whole-book count of lines matching
    ]}}}
Optional on present: "max_diffs" (edit distance allowed, default 0).
Text is compared after NFKC; whitespace is ignored except a single space
between two ASCII characters, so "Herbert Simon" must keep its space.

Run alone for a per-book summary: python tests/test_pdf_bench.py
"""
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

CASES = Path(__file__).with_name("local_pdf_bench") / "cases.json"


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"^#+ ", "", s.strip())
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"(?<![\x21-\x7e]) | (?![\x21-\x7e])", "", s)


def lines_of(md):
    return [n for n in (norm(l) for l in md.splitlines()) if n and n != "---"]


def within(hay, needle, k):
    """Smallest edit distance of needle to any substring of hay (Sellers), early exit at k."""
    prev = [0] * (len(hay) + 1)
    for i, c in enumerate(needle, 1):
        cur = [i] + [0] * len(hay)
        for j, h in enumerate(hay, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (c != h))
        prev = cur
    return min(prev) <= k


def check(md_lines, c):
    """(ok, detail)"""
    t = c["type"]
    if t == "present":
        needle, k = norm(c["text"]), c.get("max_diffs", 0)
        if any(needle in l for l in md_lines):
            return True, ""
        if k and any(within(l, needle, k) for l in md_lines if len(l) >= len(needle) - k):
            return True, ""
        whole = "".join(md_lines)
        return False, "found, but split across paragraphs" if needle in whole else "not found"
    if t == "absent":
        needle = norm(c["text"])
        whole = "".join(md_lines)
        at = whole.find(needle)
        return at < 0, "" if at < 0 else f"found: ...{whole[max(0, at - 15):at + len(needle) + 15]}..."
    if t == "line":
        needle = norm(c["text"])
        return needle in md_lines, "" if needle in md_lines else "no line equal to it"
    if t == "no_line":
        needle = norm(c["text"])
        n = md_lines.count(needle)
        return n == 0, "" if n == 0 else f"{n} lines equal to it"
    if t == "order":
        whole = "".join(md_lines)
        a, b = whole.find(norm(c["before"])), whole.find(norm(c["after"]))
        if a < 0 or b < 0:
            return False, f"missing: {'before' if a < 0 else 'after'}"
        return a < b, "" if a < b else "wrong order"
    if t == "max_lines":
        hits = [l for l in md_lines if re.search(c["regex"], l)]
        return len(hits) <= c["max"], "" if len(hits) <= c["max"] else f"{len(hits)} lines, e.g. {hits[0][:30]}"
    raise ValueError(f"unknown check type {t}")


_converted = {}


def converted(name, pdf):
    if name not in _converted:
        from ebook2md.pdf import pdf2md
        out = Path(tempfile.mkdtemp(prefix="pdf_bench_"))
        path, _ = pdf2md.convert(pdf, out, out_name="book.md")
        _converted[name] = lines_of(path.read_text(encoding="utf-8"))
    return _converted[name]


def load():
    if not CASES.exists():
        return {}
    return json.loads(CASES.read_text(encoding="utf-8"))["books"]


PARAMS = [pytest.param(name, c, id=f"{name[:6]}-{c['id']}") for name, b in load().items() for c in b["checks"]]


@pytest.mark.skipif(not PARAMS, reason="no local cases (tests/local_pdf_bench/cases.json)")
@pytest.mark.parametrize("name,c", PARAMS or [pytest.param(None, None, id="none")])
def test_page_fact(name, c):
    ok, detail = check(converted(name, load()[name]["pdf"]), c)
    assert ok, f"{c['type']} {c.get('text') or (c.get('before'), c.get('after'))}: {detail}"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    total = passed = 0
    for name, b in load().items():
        res = [(c, *check(converted(name, b["pdf"]), c)) for c in b["checks"]]
        ok = sum(r[1] for r in res)
        total += len(res)
        passed += ok
        print(f"{ok}/{len(res)}  {name}")
        for c, good, detail in res:
            if not good:
                print(f"    FAIL {c['id']} [{c['type']}] {detail}")
    print(f"total {passed}/{total}")
