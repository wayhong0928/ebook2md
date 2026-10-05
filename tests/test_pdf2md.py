"""pdf2md: build small PDFs with PyMuPDF, convert, check the Markdown."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../pipeline")))

import fitz  # noqa: E402

import pdf2md  # noqa: E402

FONT = "china-t"  # built-in Traditional Chinese font
SIZE = 12
LEFT = 30
FULL = "這是一行寫滿到右邊界的測試文字內容甲乙"  # 20 characters, reaches the right edge
W, H = 300, 400


def write_lines(page, lines, top=60, step=SIZE * 1.5):
    """lines: [str]; each drawn as one visual line from the left margin."""
    y = top
    for text in lines:
        page.insert_text((LEFT, y), text, fontname=FONT, fontsize=SIZE)
        y += step


def write_column(page, x, chars, top=60):
    """Vertical text drawn the way some PDFs do it: one character per line."""
    for i, ch in enumerate(chars):
        page.insert_text((x, top + i * SIZE * 1.2), ch, fontname=FONT, fontsize=SIZE)


class PdfTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, pages, toc=None, width=W):
        """pages: [callable(page)]; returns the converted Markdown."""
        doc = fitz.open()
        for draw in pages:
            draw(doc.new_page(width=width, height=H))
        if toc:
            doc.set_toc(toc)
        path = os.path.join(self.dir, "book.pdf")
        doc.save(path)
        out, self.stats = pdf2md.convert(path, self.dir, author="作者甲")
        with open(out, encoding="utf-8") as f:
            return f.read()


class TestParagraphs(PdfTestCase):
    def test_full_lines_join_and_short_line_ends_paragraph(self):
        md = self.build([lambda p: write_lines(p, [FULL, FULL, "第一段結束。", FULL, "第二段。"])])
        self.assertIn(FULL + FULL + "第一段結束。\n\n" + FULL + "第二段。", md)

    def test_overlapping_line_boxes_still_join(self):
        # line pitch smaller than the glyph box height: the boxes overlap
        md = self.build([lambda p: write_lines(p, [FULL, FULL, "結束。"], step=SIZE * 0.95)])
        self.assertIn(FULL + FULL + "結束。", md)

    def test_paragraph_continues_on_next_page(self):
        md = self.build([lambda p: write_lines(p, ["前一段。", FULL]),
                         lambda p: write_lines(p, ["跨頁接續的句子。"])])
        self.assertIn(FULL + "跨頁接續的句子。", md)
        self.assertEqual(self.stats["page_joins"], 1)

    def test_bullet_starts_a_paragraph(self):
        md = self.build([lambda p: write_lines(p, [FULL, "◆" + FULL[1:], "接續。", "◆第二項。"])])
        self.assertIn(FULL + "\n\n◆" + FULL[1:] + "接續。\n\n◆第二項。", md)

    def test_two_column_ragged_english(self):
        # left column first; ragged-right lines of one block run on
        left = [["Left column first paragraph runs", "over three lines that stop", "short of the edge."],
                ["Second left paragraph has its", "own block and two more", "lines of text here."]]
        right = [["Right column paragraph comes", "after the whole left column", "in reading order."],
                 ["Another right paragraph that is", "long enough to count as", "column text too."]]

        def draw(p):
            # right column drawn first: block order alone would put it first
            for x, paras in ((320, right), (30, left)):
                y = 60
                for para in paras:
                    for line in para:
                        p.insert_text((x, y), line, fontname="helv", fontsize=10)
                        y += 13
                    y += 20
        md = self.build([draw], width=600)
        self.assertIn("Left column first paragraph runs over three lines that stop short of the edge.\n", md)
        self.assertIn("Right column paragraph comes after the whole left column in reading order.\n", md)
        self.assertLess(md.index("lines of text here."), md.index("Right column paragraph"))

    def test_english_lines_and_hyphenation(self):
        self.assertEqual(pdf2md.join_lines(["infor-", "mation is"]), "information is")
        self.assertEqual(pdf2md.join_lines(["hello", "world"]), "hello world")
        self.assertEqual(pdf2md.join_lines(["中文", "接續"]), "中文接續")


class TestFurniture(PdfTestCase):
    def test_running_header_and_page_numbers_dropped(self):
        def page(n):
            def draw(p):
                p.insert_text((LEFT, 20), "書眉文字", fontname=FONT, fontsize=9)
                write_lines(p, [f"第{n}頁的內文。"])
                p.insert_text((W / 2, H - 12), str(n), fontname=FONT, fontsize=9)
            return draw
        md = self.build([page(n) for n in range(1, 7)])
        self.assertNotIn("書眉文字", md)
        body = md.split("---", 1)[1]
        for n in range(1, 7):
            self.assertIn(f"第{n}頁的內文。", body)
            self.assertNotIn(f"\n{n}\n", body)

    def test_long_english_footer_dropped(self):
        footer = "Annual Outlook Report for Testing Only | May 2025"  # over 40 characters

        def page(n):
            def draw(p):
                write_lines(p, [f"第{n}頁的內文。"])
                p.insert_text((LEFT, H - 12), f"{n}  {footer}", fontname="helv", fontsize=7)
            return draw
        md = self.build([page(n) for n in range(1, 7)])
        self.assertNotIn("Annual Outlook", md)

    def test_vertical_head_in_body_size_dropped_and_paragraph_runs_on(self):
        # OCR gives the running head the body size; it sits far right and starts higher
        def page(cols):
            def draw(p):
                write_column(p, 280, "書眉文字", top=40)
                for x, chars in zip((230, 210, 190), cols):
                    write_column(p, x, chars)
            return draw
        col = "甲乙丙丁戊己庚辛壬癸子丑"  # 12 characters: paragraphs over 30 set the body size
        md = self.build([page([col, col, col[:-1]]), page(["寅卯辰。" + col[4:], col, col[:-1] + "。"]),
                         page([col, col, col[:-1] + "。"])])
        self.assertNotIn("書眉", md)
        self.assertIn(col[:-1] + "寅卯辰。", md)


class TestHeadings(PdfTestCase):
    def test_bookmarks_become_headings_without_duplicates(self):
        toc = [[1, "第一章 開始", 1], [2, "第一節", 1], [1, "第二章 結束", 2], [1, "第三章 尾聲", 3]]
        md = self.build([lambda p: write_lines(p, ["第一章 開始", FULL, "內文一。"]),
                         lambda p: write_lines(p, ["內文二。"]),
                         lambda p: write_lines(p, ["內文三。"])], toc=toc)
        self.assertIn("---\n# 第一章 開始", md)
        self.assertIn("## 第一節", md)
        self.assertIn("---\n# 第二章 結束\n", md)
        self.assertEqual(md.count("第一章 開始"), 1)
        self.assertLess(md.index("# 第二章 結束"), md.index("內文二。"))

    def test_bookmark_title_with_newlines_stays_one_heading(self):
        toc = [[1, "第一章\n---\n# 假標題", 1], [1, "第二章", 2], [1, "第三章", 3]]
        md = self.build([lambda p: write_lines(p, ["內文一。"]), lambda p: write_lines(p, ["內文二。"]),
                         lambda p: write_lines(p, ["內文三。"])], toc=toc)
        self.assertIn("# 第一章 --- # 假標題\n", md)
        self.assertNotIn("\n# 假標題", md)

    def test_lone_top_entry_is_treated_as_book_title(self):
        # one level-1 bookmark (the book itself) above the real chapters
        toc = [[1, "書名", 1], [2, "第一章", 1], [2, "第二章", 2], [2, "第三章", 3]]
        md = self.build([lambda p: write_lines(p, ["內文一。"]), lambda p: write_lines(p, ["內文二。"]),
                         lambda p: write_lines(p, ["內文三。"])], toc=toc)
        self.assertIn("---\n# 第一章", md)
        self.assertIn("---\n# 第三章", md)

    def test_front_matter_has_author(self):
        md = self.build([lambda p: write_lines(p, ["內文。"])])
        self.assertTrue(md.startswith("# 書名：book\n\n# 作者：作者甲\n"))


class TestVertical(PdfTestCase):
    def test_single_character_columns_read_right_to_left(self):
        def draw(p):
            write_column(p, 250, "甲乙丙丁")
            write_column(p, 230, "戊己庚。")
        md = self.build([draw])
        self.assertIn("甲乙丙丁戊己庚。", md)
        self.assertEqual(self.stats["vertical_pages"], 1)

    def test_sideways_bracket_placed_by_its_lower_edge(self):
        # real PDFs give a sideways bracket a box that starts above the glyph,
        # higher than the character before it
        def draw(p):
            write_column(p, 250, "驚人的")
            write_column(p, 250, "專業性。", top=60 + 4 * SIZE * 1.2)
            p.insert_text((250 + SIZE * 0.4, 60 + 2 * SIZE * 1.2 - SIZE * 0.3), "(", fontname="helv", fontsize=SIZE)
            write_column(p, 230, "後文。")
        md = self.build([draw])
        self.assertIn("驚人的(專業性。", md)

    def test_side_tab_does_not_flip_text_page(self):
        def draw(p):
            write_lines(p, [FULL, FULL, "結束。"])
            write_column(p, 285, "解答與說明", top=200)
        md = self.build([draw])
        self.assertEqual(self.stats["vertical_pages"], 0)
        self.assertIn(FULL + FULL + "結束。", md)


class TestTextLayer(PdfTestCase):
    def save(self, pages):
        doc = fitz.open()
        for draw in pages:
            draw(doc.new_page(width=W, height=H))
        path = os.path.join(self.dir, "t.pdf")
        doc.save(path)
        return path

    def test_scan_without_text_is_rejected(self):
        ok, why = pdf2md.text_layer(self.save([lambda p: p.draw_rect(fitz.Rect(10, 10, 100, 100))] * 5))
        self.assertFalse(ok)
        self.assertIn("scan", why)

    def test_text_pdf_is_accepted(self):
        ok, _ = pdf2md.text_layer(self.save([lambda p: write_lines(p, [FULL, "內文。"])] * 5))
        self.assertTrue(ok)

    def test_garbled_text_scores_low(self):
        # broken fonts come out as private-use glyphs or letters from unrelated scripts
        self.assertLess(pdf2md.usable("ьՐሂᣉҫўΕĂ˚ސർࣇג"), 0.8)
        self.assertLess(pdf2md.usable("\U000f1c5d\U000f257c\U000f1318"), 0.8)
        self.assertEqual(pdf2md.usable("中文與 English，標點「」。"), 1.0)


if __name__ == "__main__":
    unittest.main()
