"""Prototype (2026-10-05, not wired into the pipeline): PDF with a text layer -> Markdown

- chapter headings from PDF bookmarks (get_toc), '---' before top-level ones
- without bookmarks: headings guessed from font size
- vertical (直排) pages: columns ordered right-to-left, top-to-bottom
- lines inside a block are joined (no newline between CJK characters)
- running headers / footers / page numbers dropped
- pages with no usable text are reported, not converted (scans need OCR)
"""
import collections
import datetime
import re
import statistics
import sys
import unicodedata
from pathlib import Path

import fitz

MARGIN = 0.08  # top/bottom share of the page treated as header/footer zone


def is_cjk(ch):
    return "　" <= ch <= "鿿" or "＀" <= ch <= "￯"


def join_lines(parts):
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
        elif out.endswith("-") and p[:1].islower():
            out = out[:-1] + p
        elif is_cjk(out[-1]) or is_cjk(p[0]):
            out += p
        else:
            out += " " + p
    return out


def usable(text):
    """Share of characters that are CJK / letters / digits / common punctuation
    (not private-use glyphs or '(cid:123)' garbage)."""
    t = re.sub(r"\s", "", text)
    if not t:
        return 0.0
    pua = sum(1 for c in t if "" <= c <= "")
    return 1 - pua / len(t)


def page_items(page):
    """[(y0, x0, kind, text, size, block_no)] in reading order, plus vertical flag."""
    d = page.get_text("dict")
    hor, ver = [], []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            text = "".join(s["text"] for s in l["spans"])
            if not text.strip():
                continue
            size = max(s["size"] for s in l["spans"])
            x0, y0, x1, y1 = l["bbox"]
            # some vertical PDFs place every character as its own horizontal line
            one_cjk = len(text.strip()) == 1 and is_cjk(text.strip())
            if abs(l["dir"][0]) < 0.5 or one_cjk:
                ver.append((x0, y0, x1, y1, text, size))
            else:
                hor.append((y0, x0, y1, text, size, b["number"]))
    # weigh by characters: a side tab of stacked single characters must not flip a text page
    vertical = sum(len(v[4].strip()) for v in ver) > sum(len(h[3].strip()) for h in hor)
    paras = []
    if vertical:
        # columns: cluster by x centre, right to left
        ver.sort(key=lambda v: -(v[0] + v[2]) / 2)
        cols = []
        for v in ver:
            cx, w = (v[0] + v[2]) / 2, max(v[2] - v[0], 1)
            if cols and abs(cols[-1]["cx"] - cx) < w * 0.6:
                cols[-1]["items"].append(v)
            else:
                cols.append({"cx": cx, "items": [v]})
        def flush_v(cur):
            text = "".join(t for _, t, _ in cur)
            open_end = not re.search(r"[。！？!?」』﹂…:：]\s*$", text)
            paras.append((cur[0][0], 0, text, statistics.median(s for *_, s in cur), open_end))

        tops = [min(i[1] for i in c["items"]) for c in cols]
        body_top = min(tops) if tops else 0
        cur = []
        for c, top in zip(cols, tops):
            chars = "".join(i[4] for i in sorted(c["items"], key=lambda i: i[1]))
            size = statistics.median(i[5] for i in c["items"])
            # an indented column (starts lower than the body top) opens a paragraph
            if cur and top - body_top > size * 1.5:
                flush_v(cur)
                cur = []
            cur.append((top, chars, size))
        if cur:
            flush_v(cur)
        # horizontal bits on a vertical page (page numbers, running heads) kept as their own lines
        for y0, x0, y1, text, size, _ in hor:
            paras.append((y0, x0, text, size, False))
        return paras, True
    # Horizontal: one item per visual line, in block order. A line that runs
    # to the right edge continues into the next line; a short line ends the
    # paragraph. Font-size changes always start a new paragraph.
    lines = []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            if abs(l["dir"][0]) < 0.5:
                continue
            text = "".join(s["text"] for s in l["spans"])
            if text.strip():
                lines.append((l["bbox"], text, max(s["size"] for s in l["spans"])))
    if not lines:
        return paras, False
    right = max(bb[2] for bb, _, _ in lines)
    run = [lines[0]]

    def flush():
        bb, _, size = run[0]
        last_bb, last_text, last_size = run[-1]
        open_end = last_bb[2] >= right - last_size * 1.5 and not re.search(r"[。！？!?」』…:：]\s*$", last_text)
        paras.append((bb[1], bb[0], join_lines(t for _, t, _ in run), size, open_end))

    for ln in lines[1:]:
        prev_bb, prev_text, prev_size = run[-1]
        bb, text, size = ln
        cont = (abs(size - prev_size) <= 0.5
                and prev_bb[2] >= right - prev_size * 1.5
                and -prev_size * 0.5 <= bb[1] - prev_bb[3] < prev_size * 1.2)  # line boxes may overlap a little
        if not cont:
            flush()
            run = []
        run.append(ln)
    flush()
    return paras, False


def norm_furniture(text):
    return re.sub(r"\d+", "#", unicodedata.normalize("NFKC", text)).strip()


def convert(pdf_path, out_dir):
    doc = fitz.open(pdf_path)
    n = doc.page_count
    pages = []
    stats = collections.Counter()
    for i in range(n):
        pg = doc[i]
        paras, vertical = page_items(pg)
        h = pg.rect.height
        pages.append((paras, vertical, h))
        stats["vertical_pages"] += vertical
        txt = "".join(p[2] for p in paras)
        if len(txt.strip()) < 20:
            stats["empty_pages"] += 1
        elif usable(txt) < 0.8:
            stats["garbled_pages"] += 1

    # running heads / footers: margin lines whose digit-normalised text repeats
    margin_counts = collections.Counter()
    for paras, _, h in pages:
        seen = set()
        for p in paras:
            if p[0] < h * MARGIN or p[0] > h * (1 - MARGIN):
                seen.add(norm_furniture(p[2]))
        margin_counts.update(seen)
    furniture = {t for t, c in margin_counts.items() if c >= max(3, n * 0.2) or re.fullmatch(r"[#\s\-–—|·•.]*", t)}

    sizes = [p[3] for paras, _, _ in pages for p in paras if len(p[2]) > 30]
    body = statistics.median(sizes) if sizes else 10

    toc = [t for t in doc.get_toc(simple=False) if t[1].strip()]
    if toc and len(toc) >= n * 0.8 and len({t[1] for t in toc}) < len(toc) * 0.5:
        toc = []  # one bookmark per page with repeated names: not a chapter list
    levels = collections.Counter(t[0] for t in toc)
    top = min(levels) if levels else None
    if top is not None and levels[top] < 3 and len(levels) > 1:
        top = sorted(levels)[1]  # a lone level-1 entry is the book title
    marks = collections.defaultdict(list)  # page -> [(level, title)] in TOC order
    for lvl, t, pno, dest in toc:
        if pno >= 1:
            marks[pno - 1].append((lvl, t.strip()))

    def key(t):
        return "".join(c for c in unicodedata.normalize("NFKC", t) if c.isalnum())

    def heading(lvl, t):
        sep = "\n---\n" if top is not None and lvl <= top else ""
        return sep + f"{'#' * min(max(lvl - (top or 1) + 1, 1), 6)} {t}\n"

    def matches(para_text, k):
        pk = key(para_text)
        if not pk:
            return False
        if pk == k:
            return True
        return len(pk) >= 2 and (k.startswith(pk) or pk.startswith(k)) and len(pk) <= len(k) * 1.5

    out = [f"# 書名：{Path(pdf_path).stem}\n\n# 作者：\n\n# 轉換日期：{datetime.date.today().isoformat()}\n\n---\n"]
    open_idx = None  # index in out of a paragraph that runs on to the next page
    heads_guessed = 0
    for i, (paras, vertical, h) in enumerate(pages):
        body_paras = []
        for p in paras:
            if norm_furniture(p[2]) in furniture and (p[0] < h * MARGIN or p[0] > h * (1 - MARGIN)):
                stats["furniture_dropped"] += 1
                continue
            body_paras.append(p)
        # a bookmark title that appears as a line on its page replaces that line
        at = collections.defaultdict(list)
        unplaced = []
        used = set()
        for lvl, t in marks.get(i, []):
            k = key(t)
            hit = next((j for j, p in enumerate(body_paras) if j not in used and matches(p[2], k)), None)
            if hit is None:
                unplaced.append((lvl, t))
            else:
                used.add(hit)
                at[hit].append((lvl, t))
        if unplaced:
            out.extend(heading(lvl, t) for lvl, t in unplaced)
            open_idx = None
            stats["toc_unplaced"] += len(unplaced)
        for j, p in enumerate(body_paras):
            text, size, open_end = p[2], p[3], p[4]
            if j in at:
                out.extend(heading(lvl, t) for lvl, t in at[j])
                open_idx = None
                stats["toc_placed"] += len(at[j])
                continue
            if not toc and not vertical and size >= body * 1.25 and len(text) <= 30:
                out.append(f"## {text}\n")
                heads_guessed += 1
                open_idx = None
                continue
            if open_idx is not None and j == 0:
                # paragraph continued from the previous page
                prev = out[open_idx].rstrip("\n")
                out[open_idx] = join_lines([prev, text]) + "\n"
                stats["page_joins"] += 1
            else:
                out.append(text + "\n")
            open_idx = len(out) - 1 if open_end else None
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    out_path = Path(out_dir) / f"{Path(pdf_path).stem}.md"
    out_path.write_text(md, encoding="utf-8")
    stats.update(pages=n, toc_entries=len(toc), headings_guessed=heads_guessed, chars=len(md))
    return out_path, stats


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in sys.argv[2:]:
        path, st = convert(p, out_dir)
        print(path.name, dict(st))
