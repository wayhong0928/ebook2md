"""_render_book_notes：PDF 來源的書（manifest 的 epub_path 是 None）也要能產生書籍筆記。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from notes import _quote_block, _render_book_notes, _render_concept_card  # noqa: E402

CHAPTERS = [{"chapter_num": 1, "title": "Ch1", "summary": "s", "key_quotes": ["q"], "key_concepts": []}]


class QuoteBlockTest(unittest.TestCase):
    """引文裡原書的硬換行寫進 vault 時併成一行（r52 有 19 張卡出現零碎的「> 。」行）。"""

    def test_cjk_lines_join_without_space(self):
        self.assertEqual(_quote_block("先忍住，\n之後拿更多。"), "> 先忍住，之後拿更多。")
        self.assertEqual(_quote_block("這句話寫完了\n。"), "> 這句話寫完了。")

    def test_other_lines_join_with_one_space(self):
        self.assertEqual(_quote_block("Hello\nworld."), "> Hello world.")
        self.assertEqual(_quote_block("他說\nAI 會取代"), "> 他說 AI 會取代")

    def test_blank_lines_and_edge_spaces_dropped(self):
        self.assertEqual(_quote_block("  甲 \n\n 乙。 "), "> 甲乙。")
        self.assertEqual(_quote_block("單行引文。"), "> 單行引文。")

    def test_concept_card_quote_is_one_line(self):
        out = _render_concept_card({"title": "T", "definition": "d", "source_quote": "第一行\n第二行。"}, "書")
        self.assertIn("## 原文\n> 第一行第二行。\n\n## 相關概念", out)

    def test_book_notes_one_line_per_quote(self):
        chs = [{"chapter_num": 1, "title": "Ch1", "summary": "s", "key_quotes": ["甲\n乙。", "丙。"], "key_concepts": []}]
        out = _render_book_notes({"epub_path": "D:/Books/cat/Other.epub"}, {"title": "Other"}, chs, "summary")
        self.assertIn("#### 重點擷取\n> 甲乙。\n> 丙。\n\n", out)


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
