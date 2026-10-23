"""apply_batch：同一批進來的同作者／系列也要算進子資料夾門檻（10-18 作者甲 36 本一起進來，needs_subfolder 全是 false）。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline")))
import classify  # noqa: E402
from config import SERIES_SUBFOLDER_THRESHOLD  # noqa: E402
from manifest import EBOOKS_ROOT  # noqa: E402


def book(author="", series="", path=None):
    return {"author": author, "series": series, "epub_path": str(path) if path else "", "status": "converted"}


class ApplyBatchSubfolderTest(unittest.TestCase):
    def run_batch(self, manifest, results):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rp = Path(tmp.name) / "classify_results.json"
        rp.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(classify, "load_manifest", return_value=manifest), \
                mock.patch.object(classify, "update_book"), \
                mock.patch.object(classify, "record_book_action"), \
                mock.patch.object(classify, "record"):
            return classify.apply_batch(rp)

    def batch_of(self, n, author="作者甲", series=""):
        ids = [f"書{i}" for i in range(n)]
        manifest = {"books": {b: book() for b in ids}}
        results = [{"book_id": b, "category": "文學小說", "author": author, "series": series, "confidence": 0.9}
                   for b in ids]
        return manifest, results

    def test_threshold_is_five(self):
        self.assertEqual(SERIES_SUBFOLDER_THRESHOLD, 5)

    def test_six_in_one_batch(self):
        out = self.run_batch(*self.batch_of(6))
        self.assertTrue(all(c["needs_subfolder"] for c in out.values()))
        self.assertEqual({c["subfolder_name"] for c in out.values()}, {"作者甲"})

    def test_five_in_one_batch_is_the_boundary(self):
        out = self.run_batch(*self.batch_of(5, author="", series="系列甲"))
        self.assertTrue(all(c["needs_subfolder"] for c in out.values()))
        self.assertEqual({c["subfolder_name"] for c in out.values()}, {"系列甲"})

    def test_four_in_one_batch(self):
        out = self.run_batch(*self.batch_of(4))
        self.assertFalse(any(c["needs_subfolder"] for c in out.values()))

    def test_one_more_into_existing_subfolder(self):
        manifest = {"books": {f"舊{i}": book("作者甲", path=EBOOKS_ROOT / "文學小說" / "作者甲的書" / f"舊{i}.epub")
                              for i in range(5)}}
        manifest["books"]["新書"] = book()
        out = self.run_batch(manifest, [{"book_id": "新書", "category": "文學小說", "author": "作者甲", "confidence": 0.9}])
        self.assertTrue(out["新書"]["needs_subfolder"])
        self.assertEqual(out["新書"]["subfolder_name"], "作者甲的書")


if __name__ == "__main__":
    unittest.main()
