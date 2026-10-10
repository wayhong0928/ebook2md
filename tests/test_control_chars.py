"""Control characters carried in from source books are dropped from the md
(v1.7). Synthetic input only."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ebook2md import strip_control_chars  # noqa: E402
from ebook2md.epub.epub2md import generate_markdown_content  # noqa: E402


class StripTest(unittest.TestCase):
    def test_drops_c0_c1_del_and_lone_cr(self):
        self.assertEqual(strip_control_chars("a\x07b\x08c\x8ed\x9a\x9de\x7ff\x00g"), "abcdefg")
        self.assertEqual(strip_control_chars("http://x\r/y"), "http://x/y")

    def test_keeps_tab_newline_crlf_and_text(self):
        s = "第一行\t欄\n第二行\r\n（500,000）-1.5 αβ ｘ"
        self.assertEqual(strip_control_chars(s), s)


class EpubEntityTest(unittest.TestCase):
    def test_numeric_entity_for_c1_control_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = epub.EpubBook()
            book.set_identifier("ctrl-test")
            book.set_title("Ctrl Test")
            book.set_language("zh")
            item = epub.EpubHtml(title="c1", file_name="c1.xhtml", lang="zh")
            item.content = ("<html><body><h1>章</h1><p>乘上（1,000,000/250,000）&#142;"
                            "<sup>-1.5</sup>。&#154;P=K&#157;</p></body></html>")
            book.add_item(item)
            book.toc = [epub.Link("c1.xhtml", "章", "c1")]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            book.spine = [item]
            path = Path(tmp) / "b.epub"
            epub.write_epub(str(path), book, {})
            md, _ = generate_markdown_content(str(path))
        self.assertNotRegex(md, r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
        self.assertIn("250,000）", md)
        self.assertIn("P=K", md)


if __name__ == "__main__":
    unittest.main()
