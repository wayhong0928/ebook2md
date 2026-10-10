"""PDF with a text layer -> Markdown (MarkItDown before 2026-10-05)

- chapter headings from PDF bookmarks (get_toc), '---' before top-level ones
- without bookmarks: headings guessed from font size
- vertical (直排) pages: columns ordered right-to-left, top-to-bottom;
  sideways digits, Latin and brackets put back at their place in the column
- two-column horizontal pages: left column first
- lines inside a paragraph are joined (no newline between CJK characters);
  ragged-right English runs on within a block
- running headers / footers / page numbers dropped
- tests/test_pdf_bench.py checks real pages against facts read off the page
  images (local cases only, see that file)
- text_layer() tells scans and broken-font PDFs apart; those are not converted (no OCR)
"""
import collections
import datetime
import re
import statistics
import unicodedata
from pathlib import Path

import fitz

from .. import front_matter

MARGIN = 0.08  # top/bottom share of the page always treated as header/footer zone


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


def _expected(ch):
    """Characters a Chinese or English book is made of. Fonts without a
    proper ToUnicode map come out as private-use glyphs or as random letters
    from unrelated scripts (Armenian, Ethiopic...), which fall outside."""
    o = ord(ch)
    return (o < 0x250 or 0x2000 <= o <= 0x2BFF or 0x2E80 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFFEF)


def usable(text):
    """Share of characters that look like real book text."""
    t = re.sub(r"\s", "", text)
    if not t:
        return 0.0
    return sum(map(_expected, t)) / len(t)


def text_layer(pdf_path, sample=40):
    """(ok, reason): whether the PDF has a text layer worth converting.
    Scans have (almost) no text; broken fonts give garbled text."""
    doc = fitz.open(pdf_path)
    n = doc.page_count
    step = max(1, n // sample)
    pages = [doc[i].get_text() for i in range(0, n, step)]
    doc.close()
    texty = [t for t in pages if len(t.strip()) >= 20]
    if len(texty) < len(pages) * 0.2:
        return False, f"scan: {len(texty)}/{len(pages)} sampled pages have text"
    garbled = sum(usable(t) < 0.8 for t in texty)
    if garbled > len(texty) * 0.3:
        return False, f"garbled: {garbled}/{len(texty)} text pages unreadable (font without Unicode map)"
    return True, ""


# edge: the page layout already marks it as a running head / page number
# candidate (outer column of a vertical page, sideways text outside columns)
Para = collections.namedtuple("Para", "y0 y1 x0 text size open_end edge")

NOTE_MARK = re.compile(r"[\d*＊†‡]{1,3}")


def page_items(page):
    """[Para] in reading order, plus vertical flag."""
    d = page.get_text("dict")
    hor, ver, blank = [], [], []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            text = "".join(s["text"] for s in l["spans"])
            if not text:
                continue
            size = max(s["size"] for s in l["spans"])
            x0, y0, x1, y1 = l["bbox"]
            if not text.strip():
                # word spaces of Latin set sideways on vertical pages
                blank.append((x0, y0, x1, y1, text, size))
                continue
            # some vertical PDFs place every character as its own horizontal line
            one_cjk = len(text.strip()) == 1 and is_cjk(text.strip())
            if abs(l["dir"][0]) < 0.5 or one_cjk:
                ver.append((x0, y0, x1, y1, text, size))
            else:
                hor.append((x0, y0, x1, y1, text, size))
    # weigh by characters: a side tab of stacked single characters must not flip a text page
    vertical = sum(len(v[4].strip()) for v in ver) > sum(len(h[4].strip()) for h in hor)
    paras = []
    if vertical:
        # columns: cluster by x centre, right to left; items are (y, item),
        # y being where the item sits in reading order
        ver.sort(key=lambda v: -(v[0] + v[2]) / 2)
        # small Latin letters, digits and brackets set in a column sit a
        # little off its centre: their tolerance comes from the body type
        # size (CJK keeps its own width, so two columns of small notes side
        # by side stay apart)
        typ = statistics.median(v[5] for v in ver)
        cols = []
        for v in ver:
            cx, w = (v[0] + v[2]) / 2, max(v[2] - v[0], 1)
            if not any(is_cjk(ch) for ch in v[4]):
                w = max(w, typ)
            # a column's centre is the median of what it holds so far: its
            # first item may be punctuation set off to the right
            if cols and abs(cols[-1]["cx"] - cx) < w * 0.6:
                cols[-1]["items"].append((v[1], v))
                cols[-1]["xs"].append(cx)
                cols[-1]["cx"] = statistics.median(cols[-1]["xs"])
            else:
                cols.append({"cx": cx, "xs": [cx], "items": [(v[1], v)]})
        # digits, Latin letters, brackets and spaces set sideways inside a
        # column (縱中橫) belong to that column at their height. Their box
        # sits up to half a character above the glyph, so they are placed by
        # their lower edge.
        rest = []
        for h in hor + blank:
            hx = (h[0] + h[2]) / 2
            col = None
            if len(h[4].strip()) <= 4:
                col = next((c for c in cols
                            if min(i[0] for _, i in c["items"]) - h[5] * 0.3 <= hx <= max(i[2] for _, i in c["items"]) + h[5] * 0.3
                            and min(i[1] for _, i in c["items"]) - h[5] <= h[1] <= max(i[3] for _, i in c["items"]) + h[5]), None)
            if col:
                col["items"].append((h[3] - h[5] * 0.3, h))
            elif h[4].strip():
                rest.append(h)
        for c in cols:
            c["items"].sort(key=lambda yi: yi[0])
            c["items"] = [i for _, i in c["items"]]
            # a space only counts between two Latin letters or digits
            c["text"] = re.sub(r"(?<![!-~]) +| +(?![!-~])", "", "".join(i[4] for i in c["items"]))
            c["size"] = statistics.median(i[5] for i in c["items"] if i[4].strip())
            c["top"] = c["items"][0][1]
        pitch = None
        # running head / page number: a short outermost column, not larger
        # than body text, set apart by a wider gap than the column pitch;
        # either in smaller type, or (when OCR gives it the body size) far
        # apart and starting at another height than the body columns
        if len(cols) >= 3:
            body_size = statistics.median(c["size"] for c in cols)
            gaps = [cols[k]["cx"] - cols[k + 1]["cx"] for k in range(len(cols) - 1)]
            pitch = statistics.median(gaps)
            for c, gap in ((cols[0], gaps[0]), (cols[-1], gaps[-1])):
                if len(c["text"].strip()) > 30 or c["size"] > body_size * 1.15 or gap < pitch * 1.5:
                    continue
                others_top = min(o["top"] for o in cols if o is not c)
                if c["size"] <= body_size * 0.85 or (gap >= pitch * 2 and abs(c["top"] - others_top) > c["size"] * 0.8):
                    c["edge"] = True

        def flush_v(cur):
            text = "".join(c["text"] for c in cur)
            open_end = not re.search(r"[。！？!?」』﹂…:：]\s*$", text)
            paras.append(Para(cur[0]["top"], max(i[3] for c in cur for i in c["items"]), cur[0]["cx"],
                              text, statistics.median(c["size"] for c in cur), open_end, False))

        body_top = min((c["top"] for c in cols if not c.get("edge")), default=0)
        # median, not max: OCR text layers let full columns end a couple of
        # characters apart, and squeeze some columns so their last character
        # sits higher; a short column must also hold fewer characters
        body_bottom = statistics.median([c["items"][-1][3] for c in cols if not c.get("edge")] or [0])
        body_len = statistics.median([len(c["text"]) for c in cols if not c.get("edge")] or [0])
        cur = []
        for c in cols:
            if c.get("edge"):
                # kept in place: if it turns out not to be furniture it stays where it was
                if cur:
                    flush_v(cur)
                    cur = []
                paras.append(Para(c["top"], c["items"][-1][3], c["cx"], c["text"], c["size"], False, True))
                continue
            # an indented column (starts lower than the body top) opens a
            # paragraph, and so does a wider gap than the column pitch (a
            # subheading set in body size)
            if cur and (c["top"] - body_top > c["size"] * 1.5
                        or (pitch and cur[-1]["cx"] - c["cx"] > pitch * 1.6)):
                flush_v(cur)
                cur = []
            cur.append(c)
            # a column that stops short after a full stop closes its
            # paragraph (notes start with a hanging number, not an indent)
            if (body_bottom - c["items"][-1][3] > c["size"] * 1.5 and len(c["text"]) < body_len - 2
                    and re.search(r"[。！？!?」』﹂]\s*$", c["text"])):
                flush_v(cur)
                cur = []
        if cur:
            flush_v(cur)
        # other horizontal bits on a vertical page (page numbers, running heads) kept as their own lines
        for x0, y0, x1, y1, text, size in rest:
            paras.append(Para(y0, y1, x0, text, size, False, True))
        return paras, True
    # Horizontal: one item per visual line, in block order (two-column pages:
    # left column first). A line that runs to the right edge continues into
    # the next line; a short line ends the paragraph. Font-size changes and
    # bullets always start a new paragraph.
    blocks, side = reading_order([b for b in d["blocks"] if b.get("lines")], page.rect.width)
    lines = []  # (bbox, text, size, block index, bold)
    for k, b in enumerate(blocks):
        for l in b["lines"]:
            if abs(l["dir"][0]) < 0.5:
                continue
            text = "".join(s["text"] for s in l["spans"])
            if text.strip():
                inked = [s for s in l["spans"] if s["text"].strip()]
                lines.append((l["bbox"], text, max(s["size"] for s in l["spans"]), k,
                              all(s["flags"] & 16 for s in inked)))
    if not lines:
        return paras, False
    # footnote marks set as raised small digits come out as lines of their
    # own; put each back into the line it sits on
    med = statistics.median(ln[2] for ln in lines)
    for ln in [ln for ln in lines if ln[2] <= med * 0.8 and NOTE_MARK.fullmatch(ln[1].strip())]:
        bb, t, s = ln[:3]
        cy = (bb[1] + bb[3]) / 2
        host = next((k for k, (hb, ht, hs, _, _) in enumerate(lines)
                     if hs > s and hb[1] - hs * 0.6 <= cy <= hb[3] and hb[0] <= bb[0] <= hb[2] + hs), None)
        if host is None:
            continue
        hb, ht, hs, hk, hbold = lines[host]
        at = min(len(ht), max(0, round((bb[0] - hb[0]) / max(hb[2] - hb[0], 1) * len(ht))))
        lines[host] = (hb, ht[:at] + t.strip() + ht[at:], hs, hk, hbold)
        lines.remove(ln)

    def right_edge(group):
        # the furthest edge that at least two lines reach, so one line running
        # long (Latin words, a side tab of single characters) does not move it
        ends = sorted((ln[0][2] for ln in group if len(ln[1].strip()) > 1), reverse=True)
        return next((a for a, b in zip(ends, ends[1:]) if a - b <= 2), ends[0] if ends else max(ln[0][2] for ln in group))

    # right edge per column on two-column pages, of the whole page otherwise
    rights = {}
    for ln in lines:
        rights.setdefault(side(blocks[ln[3]]), []).append(ln)
    rights = {s: right_edge(g) for s, g in rights.items()}
    page_right = right_edge(lines)

    def right_of(ln):
        s = side(blocks[ln[3]])
        return page_right if s is None else rights[s]

    # ragged-right Latin prose (English reports): lines stop anywhere, so a
    # block's lines run on unless something else ends the paragraph
    ragged = {}
    for k in {ln[3] for ln in lines}:
        g = [ln for ln in lines if ln[3] == k]
        text = "".join(ln[1] for ln in g).replace(" ", "")
        x0, x1 = min(ln[0][0] for ln in g), max(ln[0][2] for ln in g)
        ragged[k] = (len(g) >= 3 and sum(c.isascii() and c.isalpha() for c in text) >= len(text) * 0.6
                     and statistics.mean(ln[0][2] - ln[0][0] for ln in g[:-1]) >= (x1 - x0) * 0.7)
    run = [lines[0]]

    def flush():
        bb, size = run[0][0], run[0][2]
        last = run[-1]
        open_end = ((last[0][2] >= right_of(last) - last[2] * 1.5 or ragged[last[3]])
                    and not re.search(r"[。！？!?」』…:：.]\s*$", last[1]))
        paras.append(Para(bb[1], last[0][3], bb[0], join_lines(ln[1] for ln in run), size, open_end, False))

    for ln in lines[1:]:
        prev = run[-1]
        (pb, ptext, psize, pk, pbold), (bb, text, size, k, bold) = prev, ln
        # centre to centre: some line boxes are much taller than the type
        dy = (bb[1] + bb[3]) / 2 - (pb[1] + pb[3]) / 2
        cont = (abs(size - psize) <= 0.5
                and psize * 0.6 <= dy < psize * 2.4
                and not BULLET.match(text))
        if cont and not (pb[2] >= right_of(prev) - psize * 1.5):
            cont = (ragged[pk] and k == pk and bold == pbold
                    and (BULLET.match(ptext) or bb[0] <= pb[0] + psize)  # no indented new paragraph
                    and not (re.search(r"[.!?:;)]\s*$", ptext) and STEP.match(text)))
        if not cont:
            flush()
            run = []
        run.append(ln)
    flush()
    return paras, False


BULLET = re.compile(r"\s*[•●◆◇■□▪▫○★☆※➢►▶✓✔]")
STEP = re.compile(r"\s*(\d{1,2}[.)]?|[–-])\s")  # numbered step or dash item in Latin text


def reading_order(blocks, width):
    """(blocks, side): on a two-column page, left-column blocks come before
    right-column ones, band by band between blocks that span both columns.
    side(block) is 0 / 1 for a left / right column block, None otherwise
    (and always None on other pages, which keep MuPDF's block order)."""
    mid = width / 2

    def col(b):
        x0, _, x1, _ = b["bbox"]
        return 0 if x1 <= mid + 5 else 1 if x0 >= mid - 5 else None

    def chars(b):
        return sum(len(s["text"].strip()) for l in b["lines"] for s in l["spans"])

    if sum(col(b) == 0 and chars(b) >= 40 for b in blocks) < 2 or sum(col(b) == 1 and chars(b) >= 40 for b in blocks) < 2:
        return blocks, lambda b: None
    wide = sorted((b for b in blocks if col(b) is None), key=lambda b: b["bbox"][1])
    out, top = [], float("-inf")
    for w in wide + [None]:
        cut = w["bbox"][1] if w else float("inf")
        band = [b for b in blocks if col(b) is not None and top <= b["bbox"][1] < cut]
        out += sorted((b for b in band if col(b) == 0), key=lambda b: b["bbox"][1])
        out += sorted((b for b in band if col(b) == 1), key=lambda b: b["bbox"][1])
        if w:
            out.append(w)
        top = cut
    return out, col


def furniture_key(text):
    """Letters only: page numbers and punctuation drop out, so the running
    head of page 29 and of page 30 get the same key."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if c.isalpha())


def grams(key):
    # 4-character pieces: OCR noise or a page number glued to a running
    # head changes the whole string but not most of its pieces
    return {key} if len(key) < 4 else {key[a:a + 4] for a in range(len(key) - 3)}


def find_furniture(pages, body):
    """{(page, para)} to drop: running heads, footers and page numbers.

    A candidate sits outside the text block of horizontal pages (or is
    marked edge by page_items) and is short and not larger than body text.
    It is dropped when it has no letters (page numbers) or when most of its
    text recurs among the candidates of at least three pages (a running head
    that changes with each chapter is still dropped). For edge paragraphs,
    where the layout already says running head, two recurring pieces are
    enough: OCR garbles some copies of the head."""
    ratios = [(p.y0 / h, p.y1 / h) for paras, vertical, h in pages if not vertical
              for p in paras if len(p.text) > 30]
    if len(ratios) >= 20:
        tops = sorted(a for a, _ in ratios)
        bottoms = sorted(b for _, b in ratios)
        top_edge, bottom_edge = tops[len(tops) // 50], bottoms[-1 - len(bottoms) // 50]
    else:
        top_edge, bottom_edge = MARGIN, 1 - MARGIN
    cand = {}
    for i, (paras, vertical, h) in enumerate(pages):
        for j, p in enumerate(paras):
            outside = not vertical and (p.y1 <= h * top_edge + p.size * 0.5 or p.y0 >= h * bottom_edge - p.size * 0.5
                                        or p.y0 < h * MARGIN or p.y0 > h * (1 - MARGIN))
            # 60: an English footer with title and date runs to about 50
            if (p.edge or outside) and len(p.text.strip()) <= 60 and p.size < body * 1.15:
                cand[(i, j)] = furniture_key(p.text)
    pages_with = collections.defaultdict(set)
    for (i, _), k in cand.items():
        for g in grams(k):
            pages_with[g].add(i)

    def recurs(k, edge):
        # most of its pieces, not just one: a common word shared with other
        # captions or labels must not make a line furniture
        gs = grams(k)
        n = sum(len(pages_with[g]) >= 3 for g in gs)
        return n >= min(2, len(gs)) if edge else n >= len(gs) * 0.6

    return {(i, j) for (i, j), k in cand.items() if not k or recurs(k, pages[i][0][j].edge)}


def convert(pdf_path, out_dir, author="", out_name=None):
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
        txt = "".join(p.text for p in paras)
        if len(txt.strip()) < 20:
            stats["empty_pages"] += 1
        elif usable(txt) < 0.8:
            stats["garbled_pages"] += 1

    sizes = [p.size for paras, _, _ in pages for p in paras if len(p.text) > 30]
    body = statistics.median(sizes) if sizes else 10
    furniture = find_furniture(pages, body)

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
            # a bookmark title is one heading line: newlines in it would start
            # new Markdown blocks ('---', '#') and break chapter slicing
            marks[pno - 1].append((lvl, " ".join(t.split())))

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

    out = [front_matter(Path(pdf_path).stem, author, datetime.date.today().isoformat())]
    open_idx = None  # index in out of a paragraph that runs on to the next page
    heads_guessed = 0
    for i, (paras, vertical, h) in enumerate(pages):
        body_paras = []
        for j, p in enumerate(paras):
            if (i, j) in furniture:
                stats["furniture_dropped"] += 1
                continue
            body_paras.append(p)
        # a bookmark title that appears as a line on its page replaces that line
        at = collections.defaultdict(list)
        unplaced = []
        used = set()
        for lvl, t in marks.get(i, []):
            k = key(t)
            hit = next((j for j, p in enumerate(body_paras) if j not in used and matches(p.text, k)), None)
            if hit is None:
                unplaced.append((lvl, t))
            else:
                used.add(hit)
                at[hit].append((lvl, t))
        if unplaced:
            out.extend(heading(lvl, t) for lvl, t in unplaced)
            open_idx = None
            stats["toc_unplaced"] += len(unplaced)
        first = True  # no body paragraph of this page written yet
        for j, p in enumerate(body_paras):
            text, size, open_end = p.text, p.size, p.open_end
            if j in at:
                out.extend(heading(lvl, t) for lvl, t in at[j])
                open_idx = None
                first = False
                stats["toc_placed"] += len(at[j])
                continue
            if p.edge or (size < body * 0.5 and not first):
                # vertical-page head or sideways bit that was not dropped, or
                # type under half the body size after the page's body (OCR
                # noise in the margin): its own line, and a paragraph from the
                # previous page still runs on into the first body paragraph
                # after it
                out.append(text + "\n")
                continue
            if not toc and not vertical and size >= body * 1.25 and len(text) <= 30:
                out.append(f"## {text}\n")
                heads_guessed += 1
                open_idx = None
                first = False
                continue
            if open_idx is not None and first:
                # paragraph continued from the previous page (kept edge lines
                # written since then stay after it)
                prev = out[open_idx].rstrip("\n")
                out[open_idx] = join_lines([prev, text]) + "\n"
                stats["page_joins"] += 1
                at_idx = open_idx
            else:
                out.append(text + "\n")
                at_idx = len(out) - 1
            first = False
            open_idx = at_idx if open_end else None
    doc.close()  # Windows keeps an open PDF locked
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    out_path = Path(out_dir) / (out_name or f"{Path(pdf_path).stem}.md")
    out_path.write_text(md, encoding="utf-8")
    stats.update(pages=n, toc_entries=len(toc), headings_guessed=heads_guessed, chars=len(md))
    return out_path, stats

