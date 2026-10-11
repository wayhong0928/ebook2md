"""Cross-book concept matching and multi-source concept cards, on synthetic
cards in a temp folder (no real vault)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline")))

import concept_match  # noqa: E402
import notes  # noqa: E402


def card(title, book, definition, quote, related=("其他概念",)):
    rel = "\n".join(f"- [[{r}]]" for r in related)
    return (f'---\ntitle: "{title}"\ntags:\n  - "#type/concept"\n'
            f'source_book: "[[{book}]]"\ndate_added: "2026-01-01"\n---\n\n'
            f"## 定義\n{definition}\n\n## 原文\n> {quote}\n\n## 相關概念\n{rel}\n\n## 我的理解\n")


class ConceptMatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        cards = {
            "低強度有氧": ("書甲", "心跳略升但仍能說話的低強度有氧運動，用來累積耐力與燃燒脂肪。",
                       "低強度有氧可以邊運動邊聊天。"),
            "延遲滿足": ("書乙", "為了更大的長期報酬，暫時放棄眼前的小獎勵。", "孩子等十五分鐘就能拿到兩顆糖。"),
            "確認偏誤": ("書乙", "只尋找支持自己既有看法的證據。", "我們總是看見自己想看的。"),
            "本書自己的卡": ("書丙", "心跳略升但仍能說話的低強度有氧運動。", "邊跑邊聊天。"),
        }
        for t, (b, d, q) in cards.items():
            (self.dir / f"{t}.md").write_text(card(t, b, d, q), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_card_sources_both_forms(self):
        self.assertEqual(concept_match.card_sources('source_book: "[[A]]"\n'), ["A"])
        block = 'source_book:\n  - "[[A]]"\n  - "[[B：副書名]]"\ndate_added: "x"\n'
        self.assertEqual(concept_match.card_sources(block), ["A", "B：副書名"])
        self.assertEqual(concept_match.card_sources("title: x\n"), [])

    def test_same_idea_other_title_ranks_first_and_own_book_excluded(self):
        q = [{"title": "二區訓練", "definition": "低強度有氧運動，心跳略升但仍能說話，累積耐力。",
              "source_quote": "邊運動邊聊天的強度。"}]
        rows = concept_match.match(q, "書丙", self.dir, top_n=5, min_score=0.0)
        titles = [c["title"] for c in rows[0]["candidates"]]
        self.assertEqual(titles[0], "低強度有氧")
        self.assertNotIn("本書自己的卡", titles)

    def test_title_containment_scaled_by_length(self):
        self.assertEqual(concept_match._title_score("延遲滿足", "延遲滿足"), 1.0)
        near = concept_match._title_score("延遲滿足", "延遲滿足理論")
        far = concept_match._title_score("滿足", "延遲滿足的十二個條件")
        self.assertGreater(near, far)
        self.assertGreaterEqual(far, 0.5)

    def test_queries_from_book(self):
        q = concept_match.queries_from_book("書乙", self.dir)
        self.assertEqual(sorted(c["title"] for c in q), ["延遲滿足", "確認偏誤"])


class AddSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "延遲滿足.md"
        self.path.write_text(card("延遲滿足", "書乙", "為了長期報酬放棄眼前獎勵。", "等十五分鐘拿兩顆糖。"),
                             encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_book_adds_tagged_definition_quote_and_related_once(self):
        c = {"title": "延遲滿足", "definition": "忍住眼前的小獎勵。", "source_quote": "先忍住，\n之後拿更多。",
             "related_concepts": ["其他概念", "自我控制", "延遲滿足", "沒有卡的詞"]}
        self.assertTrue(notes._add_source_to_card(self.path, c, "書丁", {"自我控制"}))
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(concept_match.card_sources(text), ["書乙", "書丁"])
        # the first book's untagged paragraph and quote get tagged once another book joins
        self.assertIn("## 定義\n為了長期報酬放棄眼前獎勵。（[[書乙]]）\n\n忍住眼前的小獎勵。（[[書丁]]）\n", text)
        self.assertIn("> 等十五分鐘拿兩顆糖。\n（[[書乙]]）\n\n> 先忍住，\n> 之後拿更多。\n（[[書丁]]）", text)
        self.assertEqual(text.count("[[其他概念]]"), 1)
        self.assertNotIn("- [[延遲滿足]]", text)  # no self-link
        self.assertNotIn("沒有卡的詞", text)  # no plain-text name on a shared card
        self.assertIn("- [[自我控制]]\n\n## 我的理解", text)
        # same book, same output again: no change
        self.assertFalse(notes._add_source_to_card(self.path, c, "書丁", {"自我控制"}))
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)
        # third book extends the list form
        self.assertTrue(notes._add_source_to_card(self.path, {"title": "延遲滿足"}, "書戊"))
        self.assertEqual(concept_match.card_sources(self.path.read_text(encoding="utf-8")),
                         ["書乙", "書丁", "書戊"])

    def test_rerun_replaces_the_books_old_paragraph_and_drops_duplicates(self):
        notes._add_source_to_card(self.path, {"title": "延遲滿足", "definition": "舊版定義。",
                                              "source_quote": "舊版引文。"}, "書丁")
        text = self.path.read_text(encoding="utf-8")
        # a second paragraph of the same book, as an older tool could leave
        text = text.replace("舊版定義。（[[書丁]]）", "舊版定義。（[[書丁]]）\n\n更舊的定義。（[[書丁]]）")
        self.path.write_text(text, encoding="utf-8")
        new = {"title": "延遲滿足", "definition": "新版定義。", "source_quote": "新版引文。"}
        self.assertTrue(notes._add_source_to_card(self.path, new, "書丁"))
        text = self.path.read_text(encoding="utf-8")
        for gone in ("舊版定義", "更舊的定義", "舊版引文"):
            self.assertNotIn(gone, text)
        self.assertIn("新版定義。（[[書丁]]）", text)
        self.assertIn("> 新版引文。\n（[[書丁]]）", text)
        self.assertEqual(text.count("（[[書丁]]）"), 2)  # one definition, one quote
        self.assertIn("為了長期報酬放棄眼前獎勵。（[[書乙]]）", text)  # the other book untouched
        self.assertIn("> 等十五分鐘拿兩顆糖。\n（[[書乙]]）", text)

    def test_card_of_this_book_only_is_left_alone(self):
        before = self.path.read_text(encoding="utf-8")
        self.assertFalse(notes._add_source_to_card(self.path, {"title": "延遲滿足", "definition": "別的。"}, "書乙"))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
