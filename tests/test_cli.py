"""ebook2md command line, the converter version line, and reproducible output
(the same code converts the same book to the same bytes)."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import fitz
from ebooklib import epub

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ebook2md  # noqa: E402

BODY = "這是一段測試用的正文內容，句子寫到這裡結束。" * 40


def make_epub(path):
    book = epub.EpubBook()
    book.set_identifier("cli-test")
    book.set_title("測試書")
    book.add_author("作者甲")
    book.set_language("zh")
    items = []
    for i in (1, 2, 3):
        item = epub.EpubHtml(title=f"c{i}", file_name=f"c{i}.xhtml", lang="zh")
        item.content = f"<html><body><h1>第{i}章</h1>" + f"<p>{BODY}</p>" * 6 + "</body></html>"
        book.add_item(item)
        items.append(item)
    book.toc = [epub.Link(f"c{i}.xhtml", f"第{i}章", f"c{i}") for i in (1, 2, 3)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = items
    epub.write_epub(str(path), book, {})
    return path


def make_pdf(path, text=True):
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=300, height=400)
        if text:
            for k in range(12):
                page.insert_text((30, 60 + k * 18), "這是一行寫滿到右邊界的測試文字內容甲乙", fontname="china-t", fontsize=12)
    if text:
        doc.set_toc([[1, "第一章", 1], [1, "第二章", 3]])
    doc.save(str(path))
    return path


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "ebook2md", *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_convert_epub_and_pdf_with_version_line(self):
        e, p = make_epub(self.dir / "book.epub"), make_pdf(self.dir / "scan.pdf")
        r = run("convert", e, p, "-o", self.dir / "out")
        self.assertEqual(r.returncode, 0, r.stderr)
        md_e = (self.dir / "out" / "測試書_作者甲.md").read_text(encoding="utf-8")
        md_p = (self.dir / "out" / "scan.md").read_text(encoding="utf-8")
        for md in (md_e, md_p):
            head = md.split("\n---\n", 1)[0]
            self.assertRegex(head, r"^# 書名：.*\n\n# 作者：.*\n\n# 轉換日期：\d{4}-\d\d-\d\d\n\n"
                                   r"# 轉換器：ebook2md \d+\.\d+\.\d+( \(\w+(\+dirty)?\))?\n$")
            self.assertIn(f"ebook2md {ebook2md.__version__}", head)

    def test_name_option_and_single_book_only(self):
        e = make_epub(self.dir / "book.epub")
        self.assertEqual(run("convert", e, "-o", self.dir, "--name", "x.md").returncode, 0)
        self.assertTrue((self.dir / "x.md").exists())
        self.assertEqual(run("convert", e, e, "-o", self.dir, "--name", "x.md").returncode, 2)

    def test_pdf_without_text_is_skipped(self):
        p = make_pdf(self.dir / "blank.pdf", text=False)
        r = run("convert", p, "-o", self.dir / "out")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no usable text layer", r.stdout)
        self.assertFalse((self.dir / "out" / "blank.md").exists())

    def test_same_book_converts_to_the_same_bytes(self):
        """G5: nothing in the output depends on the run (dict order, temp names...)."""
        e, p = make_epub(self.dir / "book.epub"), make_pdf(self.dir / "scan.pdf")
        for d in ("a", "b"):
            self.assertEqual(run("convert", e, p, "-o", self.dir / d).returncode, 0)
        for name in ("測試書_作者甲.md", "scan.md"):
            self.assertEqual((self.dir / "a" / name).read_bytes(), (self.dir / "b" / name).read_bytes(), name)

    def test_slice_epub_and_converted_md(self):
        e = make_epub(self.dir / "book.epub")
        r = run("slice", e, "-o", self.dir / "e.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads((self.dir / "e.json").read_text(encoding="utf-8"))
        self.assertEqual([c["title"] for c in data["chapters"]], ["第1章", "第2章", "第3章"])
        self.assertTrue(data["report"]["self_check"])
        run("convert", e, "-o", self.dir, "--name", "book.md")
        r = run("slice", self.dir / "book.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads((self.dir / "book.chapters.json").read_text(encoding="utf-8"))
        # the version line is part of the converter's own head block, not a chapter
        self.assertEqual([c["title"] for c in data["chapters"]], ["第1章", "第2章", "第3章"])

    def test_old_entry_point_still_works_and_warns(self):
        e = make_epub(self.dir / "book.epub")
        r = subprocess.run([sys.executable, str(ROOT / "src" / "epub2md.py"), str(e), str(self.dir), "-o", "old.md"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("deprecated", r.stderr)
        self.assertTrue((self.dir / "old.md").exists())

    def test_version(self):
        r = run("--version")
        self.assertEqual(r.stdout.strip(), f"ebook2md {ebook2md.__version__}")


class NoPersonalPathsTest(unittest.TestCase):
    """The repo is public: the owner's library and vault locations stay in
    pipeline/local_config.json (gitignored)."""

    def test_tracked_files(self):
        files = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True).stdout.split()
        if not files:
            self.skipTest("not a git checkout")
        # any absolute drive path except the README examples, plus the owner's
        # configured locations when this checkout has them
        local = ROOT / "pipeline" / "local_config.json"
        own = [re.escape(str(v)) for v in json.loads(local.read_text(encoding="utf-8")).values()] if local.exists() else []
        drive = r"(?<![A-Za-z])[A-Za-z]:[\\/](?!Books/|Notes/)\w"
        pattern = re.compile("|".join([drive] + own), re.I)
        hits = []
        for f in files:
            p = ROOT / f
            if f == "tests/test_cli.py" or p.suffix.lower() not in (".py", ".md", ".txt", ".toml", ".yml", ".json") or not p.exists():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            hits += [f"{f}: {m.group(0)}" for m in pattern.finditer(text)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
