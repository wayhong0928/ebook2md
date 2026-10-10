"""_render_book_notes：PDF 來源的書（manifest 的 epub_path 是 None）也要能產生書籍筆記。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from notes import _render_book_notes  # noqa: E402

CHAPTERS = [{"chapter_num": 1, "title": "Ch1", "summary": "s", "key_quotes": ["q"], "key_concepts": []}]


class RenderBookNotesSourceTest(unittest.TestCase):
    def test_pdf_book_without_epub_path(self):
        entry = {"epub_path": None, "pdf_path": "D:/Books/cat/Sample Book.pdf",
                 "md_path": "D:/Books/markdown/cat/Sample Book.md", "category": "cat"}
        out = _render_book_notes(entry, {}, CHAPTERS, "summary")
        self.assertIn('title: "Sample Book"', out)
        self.assertIn('source_epub: ""', out)
        self.assertIn('source_pdf: "D:/Books/cat/Sample Book.pdf"', out)
        self.assertNotIn("None", out)

    def test_epub_book_unchanged(self):
        entry = {"epub_path": "D:/Books/cat/Other.epub", "md_path": "D:/Books/markdown/cat/Other.md"}
        out = _render_book_notes(entry, {"title": "Other"}, CHAPTERS, "summary")
        self.assertIn('source_epub: "D:/Books/cat/Other.epub"', out)
        self.assertNotIn("source_pdf", out)


if __name__ == "__main__":
    unittest.main()
