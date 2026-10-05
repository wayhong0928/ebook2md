"""prepare-notes chapter slicing: no text is dropped, long chapters are split
again instead of truncated. Built on small synthetic EPUBs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../pipeline")))

import notes  # noqa: E402

LIMIT = notes.MAX_CHARS_PER_CHAPTER


def para(n_chars, word="測試句子內容。"):
    """One <p> of roughly n_chars characters ending a sentence."""
    return "<p>" + word * max(1, n_chars // len(word)) + "</p>"


def paras(total, each=500):
    return "".join(para(each) for _ in range(max(1, total // each)))


def build_epub(path, files, toc):
    """files: [(file_name, body_html)]; toc: ebooklib toc structure."""
    book = epub.EpubBook()
    book.set_identifier("slice-test")
    book.set_title("Slice Test")
    book.set_language("zh")
    items = []
    for name, body in files:
        item = epub.EpubHtml(title=name, file_name=name, lang="zh")
        item.content = f"<html><body>{body}</body></html>"
        book.add_item(item)
        items.append(item)
    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = items
    epub.write_epub(str(path), book, {})
    return path


class SliceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def slice(self, files, toc):
        path = build_epub(Path(self.tmp.name) / "book.epub", files, toc)
        chapters, report = notes._slice_from_epub(path)
        self.assertTrue(report["self_check"])
        for c in chapters:
            self.assertEqual(len(c["content"]), c["char_count"])
            self.assertLessEqual(c["char_count"], LIMIT)
        return chapters, report


class TestEpubSlicing(SliceTestBase):
    def test_long_chapter_without_structure_is_split_not_truncated(self):
        body = "<h1>第一章</h1>" + paras(95_000)
        chapters, report = self.slice([("c1.xhtml", body)], [epub.Link("c1.xhtml", "第一章", "c1")])
        self.assertEqual([c["title"] for c in chapters], ["第一章（1/3）", "第一章（2/3）", "第一章（3/3）"])
        self.assertTrue(all(c["split"] == "paragraph" for c in chapters))
        self.assertEqual(report["chapter_chars"] + len(chapters) - 1, report["original_chars"])

    def test_sibling_chapters_in_one_file_are_cut_at_their_anchors(self):
        body = "".join(f'<h2 id="s{i}">第{i}章</h2>' + paras(5000) for i in (1, 2, 3))
        toc = [epub.Link(f"all.xhtml#s{i}", f"第{i}章", f"s{i}") for i in (1, 2, 3)]
        chapters, report = self.slice([("all.xhtml", body)], toc)
        self.assertEqual([c["title"] for c in chapters], ["第1章", "第2章", "第3章"])
        self.assertEqual(report["toc_resplit_documents"], 1)

    def test_flat_toc_of_tiny_entries_keeps_the_file_whole(self):
        body = "".join(f'<p id="e{i}">條目{i}</p>' + para(250) for i in range(40))
        toc = [epub.Link(f"ref.xhtml#e{i}", f"條目{i}", f"e{i}") for i in range(40)]
        chapters, _ = self.slice([("ref.xhtml", body)], toc)
        self.assertEqual(len(chapters), 1)

    def test_title_page_title_carries_to_the_content_file(self):
        files = [("t1.xhtml", "<p>01 冒險</p>"), ("b1.xhtml", "<h5>小標</h5>" + paras(3000)),
                 ("t2.xhtml", "<p>02 成長</p>"), ("b2.xhtml", "<h5>另一個小標</h5>" + paras(3000))]
        toc = [epub.Link("t1.xhtml", "01 冒險", "t1"), epub.Link("t2.xhtml", "02 成長", "t2")]
        chapters, _ = self.slice(files, toc)
        self.assertEqual([c["title"] for c in chapters], ["01 冒險", "02 成長"])

    def test_short_title_page_with_epigraph_absorbs_the_body_file(self):
        files = [("t8.xhtml", "<h1>第八章</h1>" + para(300)), ("b8.xhtml", "<h3>一、小節</h3>" + paras(5000))]
        toc = [epub.Link("t8.xhtml", "第八章", "t8")]
        chapters, _ = self.slice(files, toc)
        self.assertEqual([c["title"] for c in chapters], ["第八章"])

    def test_untitled_file_joins_the_previous_chapter(self):
        files = [("a.xhtml", "<h1>第一章</h1>" + paras(3000)), ("a_split.xhtml", paras(3000)),
                 ("b.xhtml", "<h1>第二章</h1>" + paras(3000))]
        toc = [epub.Link("a.xhtml", "第一章", "a"), epub.Link("b.xhtml", "第二章", "b")]
        chapters, _ = self.slice(files, toc)
        self.assertEqual([c["title"] for c in chapters], ["第一章", "第二章"])
        self.assertGreater(chapters[0]["char_count"], 5500)

    def test_notes_at_the_back_are_listed_not_summarised(self):
        files = [("c1.xhtml", "<h1>第一章</h1>" + paras(5000)), ("c2.xhtml", "<h1>第二章</h1>" + paras(5000)),
                 ("n.xhtml", "<h1>注釋</h1>" + paras(3000))]
        toc = [epub.Link("c1.xhtml", "第一章", "c1"), epub.Link("c2.xhtml", "第二章", "c2"),
               epub.Link("n.xhtml", "注釋", "n")]
        chapters, report = self.slice(files, toc)
        self.assertEqual([c["title"] for c in chapters], ["第一章", "第二章"])
        self.assertEqual([b["title"] for b in report["back_matter"]], ["注釋"])

    def test_notes_title_in_the_first_half_is_a_chapter(self):
        files = [("n.xhtml", "<h1>注釋</h1>" + paras(3000)), ("c1.xhtml", "<h1>第一章</h1>" + paras(9000))]
        toc = [epub.Link("n.xhtml", "注釋", "n"), epub.Link("c1.xhtml", "第一章", "c1")]
        chapters, report = self.slice(files, toc)
        self.assertEqual(len(chapters), 2)
        self.assertEqual(report["back_matter"], [])

    def test_oversize_chapter_splits_at_toc_subsections(self):
        body = "<h1>第一章</h1>" + paras(2000) + "".join(
            f'<h2 id="s{i}">第{i}節</h2>' + paras(15000) for i in (1, 2, 3, 4))
        toc = [(epub.Link("c1.xhtml", "第一章", "c1"),
                [epub.Link(f"c1.xhtml#s{i}", f"第{i}節", f"s{i}") for i in (1, 2, 3, 4)])]
        chapters, report = self.slice([("c1.xhtml", body)], toc)
        # the 2000-character intro is packed with 第1節 under the chapter title
        self.assertEqual([c["title"] for c in chapters],
                         ["第一章", "第一章／第2節", "第一章／第3節", "第一章／第4節"])
        self.assertEqual(report["oversize_chapters"], 1)
        self.assertTrue(all(c["split"] == "toc_sub" for c in chapters))

    def test_mid_sentence_anchor_is_not_a_cut(self):
        body = ('<p>' + "前文" * 2000 + '<a id="x"></a>' + "後文" * 2000 + "。</p>"
                + '<h2 id="y">第二章</h2>' + paras(5000))
        toc = [epub.Link("c.xhtml#x", "假章", "x"), epub.Link("c.xhtml#y", "第二章", "y")]
        chapters, _ = self.slice([("c.xhtml", body)], toc)
        self.assertNotIn("假章", [c["title"] for c in chapters])
        self.assertIn("後文", chapters[0]["content"])


    def test_trailing_footnotes_leave_the_chapter(self):
        notes_html = "".join(f'<p class="footnote" id="foot-{i}">{i}　某作者，《某書》，頁{i}。</p>' for i in range(60))
        files = [("c1.xhtml", "<h1>第一章</h1>" + paras(5000) + "<h3>注釋</h3>" + notes_html),
                 ("c2.xhtml", "<h1>第二章</h1>" + paras(5000))]
        toc = [epub.Link("c1.xhtml", "第一章", "c1"), epub.Link("c2.xhtml", "第二章", "c2")]
        chapters, report = self.slice(files, toc)
        self.assertEqual([c["title"] for c in chapters], ["第一章", "第二章"])
        self.assertNotIn("某作者", chapters[0]["content"])
        self.assertFalse(chapters[0]["content"].rstrip().endswith("注釋"))
        self.assertEqual(report["note_tails"], 1)
        self.assertEqual(report["back_matter"][0]["kind"], "chapter_notes")

    def test_note_class_followed_by_body_text_stays(self):
        body = ("<h1>第一章</h1>" + paras(3000) + '<div class="footnote"><p>側欄說明文字。</p></div>'
                + paras(3000))
        chapters, report = self.slice([("c1.xhtml", body)], [epub.Link("c1.xhtml", "第一章", "c1")])
        self.assertIn("側欄說明文字", chapters[0]["content"])
        self.assertEqual(report["note_tails"], 0)

    def test_bare_note_class_and_aside_are_not_notes(self):
        body = "<h1>第一章</h1>" + paras(3000) + '<p class="note">引言框。</p><aside><p>補充。</p></aside>'
        chapters, report = self.slice([("c1.xhtml", body)], [epub.Link("c1.xhtml", "第一章", "c1")])
        self.assertIn("引言框", chapters[0]["content"])
        self.assertEqual(report["note_tails"], 0)

    def test_chapter_continuing_after_its_notes_stays_one_chapter(self):
        notes_html = '<div epub:type="footnotes">' + "".join(f"<p>{i} 注文內容。</p>" for i in range(80)) + "</div>"
        files = [("a.xhtml", "<h1>第一章</h1>" + paras(4000) + notes_html), ("a2.xhtml", paras(4000)),
                 ("b.xhtml", "<h1>第二章</h1>" + paras(3000))]
        toc = [epub.Link("a.xhtml", "第一章", "a"), epub.Link("b.xhtml", "第二章", "b")]
        chapters, report = self.slice(files, toc)
        self.assertEqual([c["title"] for c in chapters], ["第一章", "第二章"])
        self.assertNotIn("注文內容", chapters[0]["content"])
        self.assertGreater(chapters[0]["char_count"], 7500)
        self.assertEqual(report["note_tails"], 1)

    def test_short_files_are_kept_not_skipped(self):
        files = [("c1.xhtml", "<h1>第一章</h1>" + paras(3000)), ("p.xhtml", "<p>一段很短的小節內容。</p>"),
                 ("c2.xhtml", "<h1>第二章</h1>" + paras(3000))]
        toc = [epub.Link("c1.xhtml", "第一章", "c1"), epub.Link("c2.xhtml", "第二章", "c2")]
        chapters, report = self.slice(files, toc)
        self.assertEqual([c["title"] for c in chapters], ["第一章", "第二章"])
        self.assertIn("很短的小節", chapters[0]["content"])
        self.assertEqual(report["skipped_empty_documents"], 0)
        self.assertGreaterEqual(report["chapter_chars"], report["original_chars"])

    def test_lone_heading_before_a_long_section_is_not_a_chapter(self):
        body = ("<h1>第一章</h1>" + paras(6000) + "<h2>三、目的</h2><p>短句。</p><h2>四、方法</h2>" + paras(42000)
                + "<h2>五、結論</h2>" + paras(6000))
        chapters, _ = self.slice([("c1.xhtml", body)], [epub.Link("c1.xhtml", "第一章", "c1")])
        self.assertTrue(all(c["char_count"] >= notes.MIN_CHAPTER_CHARS for c in chapters),
                        [(c["title"], c["char_count"]) for c in chapters])


class TestBackMatterTitles(unittest.TestCase):
    def test_titles(self):
        for t in ["參考書目", "主要參考文獻", "參考書目及注釋", "附錄2：網路資源與延伸閱讀", "徵引書目",
                  "主要參考材料", "人名索引", "附注", "Notes", "Bibliography"]:
            self.assertTrue(notes._is_back_matter(t, 0.9), t)
        for t in ["參考文獻的寫法", "∣延伸閱讀∣ 某人的自傳性資料", "注意力經濟", "研究方法", "Notes on Design"]:
            self.assertFalse(notes._is_back_matter(t, 0.9), t)
        self.assertFalse(notes._is_back_matter("注釋", 0.2))


class TestMdSlicing(unittest.TestCase):
    def test_only_converter_front_matter_is_skipped(self):
        body = "內容句子。" * 100
        md = (f"# 書名：X\n\n# 作者：Y\n\n---\n\n# 作者序\n\n{body}\n\n---\n\n"
              f"# 書名頁之後\n\n{body}\n\n---\n\n")
        chapters, _ = notes._slice_from_md(md)
        self.assertEqual([c["title"] for c in chapters], ["作者序", "書名頁之後"])

    def test_long_md_section_splits_at_headings_and_rejoins(self):
        sec = "# 第一章\n\n" + "\n\n".join(f"## 第{i}節\n\n" + "內容句子。" * 3000 for i in range(1, 4))
        md = "# 書名：X\n\n---\n\n" + sec + "\n\n---\n\n"
        chapters, report = notes._slice_from_md(md)
        self.assertTrue(report["self_check"])
        self.assertEqual([c["title"] for c in chapters], ["第一章", "第一章／第2節", "第一章／第3節"])
        self.assertEqual("\n".join(c["content"] for c in chapters), sec)


if __name__ == "__main__":
    unittest.main()
