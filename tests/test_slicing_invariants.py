"""Slicing invariants on random synthetic books (G4).

The slicer checks itself (report["self_check"]); these tests check the same
promises from the outside, against text the test builds on its own:
- no book text is lost: taking every chapter out of the source text, in
  order, leaves only notes and back matter
- chapters keep the book's order
- trailing notes and back matter never end up inside a chapter
- cuts fall between paragraphs, never inside one
- no chapter is over the limit unless it is a single paragraph
"""
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../pipeline")))

import notes  # noqa: E402

LIMIT = notes.MAX_CHARS_PER_CHAPTER
NOTE_WORD = "注文"
BACK_WORD = "書末附錄文字"


class Book:
    """A random book: spine files, TOC and the source text of each file."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.n = 0  # paragraph counter: every paragraph is unique
        self.files, self.toc = [], []

    def para(self, size):
        self.n += 1
        unit = f"第{self.n}段的測試句子內容。"
        return "<p>" + unit * max(1, size // len(unit)) + "</p>"

    def paras(self, total):
        out = []
        while total > 0:
            size = self.rng.randint(80, 1500)
            out.append(self.para(size))
            total -= size
        return "".join(out)

    def notes_html(self):
        k = self.rng.randint(5, 60)
        return "<h3>注釋</h3>" + "".join(
            f'<p class="footnote" id="fn{self.n}-{i}">{i}　{NOTE_WORD}{i}，某作者，《某書》。</p>' for i in range(k))

    def add(self, body, title=None, sub=None):
        name = f"f{len(self.files)}.xhtml"
        self.files.append((name, body))
        if title:
            link = epub.Link(name, title, name)
            self.toc.append((link, sub) if sub else link)
        return name

    def build(self):
        rng = self.rng
        ch = 0
        for _ in range(rng.randint(3, 9)):
            kind = rng.choice(["chapter", "chapter", "notes", "untitled", "short", "long", "anchors", "image"])
            ch += 1
            title = f"第{ch}章"
            if kind == "chapter":
                self.add(f"<h1>{title}</h1>" + self.paras(rng.randint(800, 12000)), title)
            elif kind == "notes":
                self.add(f"<h1>{title}</h1>" + self.paras(rng.randint(2000, 9000)) + self.notes_html(), title)
            elif kind == "untitled":
                self.add(self.paras(rng.randint(500, 6000)))
            elif kind == "short":
                self.add(f"<p>短短的一段第{ch}號。</p>")
            elif kind == "image":
                self.add('<p><img src="x.png" alt=""/></p>', title)
            elif kind == "long":
                body = f"<h1>{title}</h1>"
                for s in range(rng.randint(0, 4)):
                    body += self.paras(rng.randint(3000, 30000)) + f"<h2>{title}第{s + 1}節</h2>"
                self.add(body + self.paras(rng.randint(41000, 90000)), title)
            else:  # several TOC chapters inside one file, cut at anchors
                name = f"f{len(self.files)}.xhtml"
                body = ""
                for s in range(rng.randint(2, 4)):
                    body += f'<h2 id="a{s}">{title}之{s + 1}</h2>' + self.paras(rng.randint(3000, 9000))
                    self.toc.append(epub.Link(f"{name}#a{s}", f"{title}之{s + 1}", f"{name}-a{s}"))
                self.files.append((name, body))
        if rng.random() < 0.5:
            self.add("<h1>參考書目</h1>" + "".join(f"<p>{BACK_WORD}{i}。</p>" for i in range(rng.randint(5, 40))),
                     "參考書目")
        return self

    def write(self, path):
        book = epub.EpubBook()
        book.set_identifier("invariants")
        book.set_title("Invariants")
        book.set_language("zh")
        items = []
        for name, body in self.files:
            item = epub.EpubHtml(title=name, file_name=name, lang="zh")
            item.content = f"<html><body>{body}</body></html>"
            book.add_item(item)
            items.append(item)
        book.toc = self.toc
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = items
        epub.write_epub(str(path), book, {})

    def source_lines(self):
        out = []
        for _, body in self.files:
            text = BeautifulSoup(f"<html><body>{body}</body></html>", "html.parser").body.get_text("\n", strip=True)
            out += [l for l in text.split("\n") if l]
        return out


def is_left_out(line):
    """Lines the slicer may keep out of the chapters."""
    return NOTE_WORD in line or BACK_WORD in line or line in ("注釋", "參考書目")


class TestSlicingInvariants(unittest.TestCase):
    SEEDS = range(40)

    def check(self, book, chapters, report):
        src = book.source_lines()
        self.assertTrue(report["self_check"])
        pos = 0  # line index in src: chapters must come in order, whole paragraphs only
        for c in chapters:
            lines = c["content"].split("\n")
            self.assertEqual(len(c["content"]), c["char_count"])
            # find the chapter's first line at or after pos; lines skipped on the way must be left-out text
            start = pos
            while start < len(src) and src[start] != lines[0]:
                self.assertTrue(is_left_out(src[start]), f"{src[start][:40]!r} missing from every chapter")
                start += 1
            self.assertLess(start, len(src), f"chapter {c['title']!r} not found in order")
            k = start
            for line in lines:
                # notes cut out of the middle of a chapter (several ranges) are skipped
                while k < len(src) and src[k] != line and is_left_out(src[k]):
                    k += 1
                self.assertLess(k, len(src))
                self.assertEqual(src[k], line, f"chapter {c['title']!r} cut inside a paragraph or reordered")
                k += 1
            pos = k
            self.assertFalse(any(is_left_out(l) for l in lines), f"note/back matter inside {c['title']!r}")
            if c["char_count"] > LIMIT:
                self.assertEqual(len(lines), 1, f"{c['title']!r} over the limit with places to cut")
        for line in src[pos:]:
            self.assertTrue(is_left_out(line), f"{line[:40]!r} after the last chapter is lost")

    def test_random_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            for seed in self.SEEDS:
                with self.subTest(seed=seed):
                    book = Book(seed).build()
                    path = Path(tmp) / f"b{seed}.epub"
                    book.write(path)
                    chapters, report = notes._slice_from_epub(path)
                    self.assertTrue(chapters)
                    self.check(book, chapters, report)
                    if any(NOTE_WORD in l for l in book.source_lines()):
                        self.assertTrue(report["note_tails"] or report["back_matter"])

    def test_md_slicing_keeps_every_paragraph_in_order(self):
        rng = random.Random(7)
        for seed in range(10):
            with self.subTest(seed=seed):
                sections, n = [], 0
                for s in range(rng.randint(2, 8)):
                    body = [f"# 第{s + 1}章"]
                    for _ in range(rng.randint(1, 60)):
                        n += 1
                        body.append(f"第{n}段的內容。" * rng.randint(10, 400))
                        if rng.random() < 0.1:
                            body.append(f"## 小節{n}")
                    sections.append("\n\n".join(body))
                md = "# 書名：X\n\n# 作者：Y\n\n# 轉換日期：2026-01-01\n\n---\n\n" + "\n\n---\n\n".join(sections) + "\n"
                chapters, report = notes._slice_from_md(md)
                self.assertTrue(report["self_check"])
                joined = "\n".join(c["content"] for c in chapters)
                self.assertEqual([l for l in joined.split("\n") if l],
                                 [l for s in sections for l in s.split("\n") if l])
                for c in chapters:
                    self.assertTrue(c["char_count"] <= LIMIT or "\n" not in c["content"].strip())


if __name__ == "__main__":
    unittest.main()
