"""
Classification pipeline — no API key required.

Flow:
  1. prepare_batch()  → writes pipeline/pending_classify.json
                        (book IDs + MD excerpts for Claude Code to classify)
  2. Claude Code reads the file, outputs classification JSON
  3. apply_batch()    → reads results, updates manifest, returns dict for card creation

The actual classification is done interactively by Claude Code in the same session.
"""
import json
from datetime import datetime
from pathlib import Path

from config import (
    CLASSIFY_MAX_CHARS, CLASSIFY_CONFIDENCE_THRESHOLD,
    PIPELINE_DIR, VALID_CATEGORIES, SERIES_SUBFOLDER_THRESHOLD,
)
from logger import get_logger
from activity import record, record_book_action
from manifest import (
    load_manifest, update_book,
    count_books_by_field,
)

log = get_logger("classify")

PENDING_FILE = PIPELINE_DIR / "pending_classify.json"
RESULTS_FILE = PIPELINE_DIR / "classify_results.json"


# ---------------------------------------------------------------------------
# Step 1 — Prepare batch for Claude Code
# ---------------------------------------------------------------------------

def prepare_batch(limit: int = 20, force: bool = False) -> Path:
    """
    Export up to `limit` books needing classification into pending_classify.json.
    Each entry contains the book_id and the first CLASSIFY_MAX_CHARS of its MD.
    Returns the path to the pending file.
    """
    manifest = load_manifest()
    candidates = [
        (k, v) for k, v in manifest["books"].items()
        if v.get("status") == "converted"
        and v.get("md_path")
        and (force or not v.get("classification"))
    ]

    if not candidates:
        log.info("No books pending classification.")
        return PENDING_FILE

    batch = candidates[:limit]
    log.info("Preparing classification batch: %d book(s) (of %d pending)", len(batch), len(candidates))

    entries = []
    for book_id, entry in batch:
        md_path = Path(entry["md_path"])
        if not md_path.exists():
            log.warning("MD file not found, skipping: %s", md_path)
            continue
        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
            excerpt = text[:CLASSIFY_MAX_CHARS]
        except Exception as e:
            log.error("Cannot read %s: %s", md_path, e)
            continue

        entries.append({
            "book_id": book_id,
            "epub_path": entry.get("epub_path", ""),
            "md_excerpt": excerpt,
        })

    payload = {
        "created": datetime.now().isoformat(),
        "total_pending": len(candidates),
        "batch_size": len(entries),
        "valid_categories": VALID_CATEGORIES,
        "confidence_threshold": CLASSIFY_CONFIDENCE_THRESHOLD,
        "subfolder_threshold": SERIES_SUBFOLDER_THRESHOLD,
        "books": entries,
    }

    PENDING_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Batch written to: %s", PENDING_FILE)
    record("prepare_batch", details={"batch_size": len(entries), "total_pending": len(candidates)})

    print(f"\nBatch ready: {PENDING_FILE}")
    print(f"  {len(entries)} book(s) exported, {len(candidates) - len(entries)} remaining after this batch.")
    print("\nNext step: ask Claude Code to classify this batch.")
    print('  → "請幫我分類 pipeline/pending_classify.json 裡的書籍，輸出結果到 pipeline/classify_results.json"')

    return PENDING_FILE


# ---------------------------------------------------------------------------
# Step 2 — Apply classification results from Claude Code
# ---------------------------------------------------------------------------

def _enrich_with_subfolder(result: dict, manifest: dict) -> dict:
    """Determine if a series/author subfolder should be created."""
    series = result.get("series", "").strip()
    author = result.get("author", "").strip()
    author_count = count_books_by_field("author", author, manifest)
    series_count = count_books_by_field("series", series, manifest) if series else 0
    needs = (
        (series and series_count >= SERIES_SUBFOLDER_THRESHOLD) or
        (author and author_count >= SERIES_SUBFOLDER_THRESHOLD)
    )
    result["needs_subfolder"] = needs
    result["subfolder_name"] = (series or author) if needs else ""
    return result


def apply_batch(results_path: Path = RESULTS_FILE) -> dict[str, dict]:
    """
    Read Claude Code's classification results from results_path.
    Update manifest for each book and return classifications for card creation.

    Expected format (list of objects):
    [
      {
        "book_id": "...",
        "category": "心理學",
        "sub_categories": [...],
        "series": "",
        "volume": null,
        "author": "...",
        "core_premise": "...",
        "toc_summary": "...",
        "tags": ["#topic/..."],
        "confidence": 0.95,
        "new_category_suggestion": null
      },
      ...
    ]
    """
    if not results_path.exists():
        log.error("Results file not found: %s", results_path)
        return {}

    try:
        raw = results_path.read_text(encoding="utf-8")
        results = json.loads(raw)
        if isinstance(results, dict) and "books" in results:
            results = results["books"]
    except Exception as e:
        log.error("Cannot parse results file: %s", e)
        return {}

    manifest = load_manifest()
    classifications = {}

    for item in results:
        book_id = item.get("book_id")
        if not book_id:
            log.warning("Result missing book_id, skipping: %s", str(item)[:80])
            continue

        if book_id not in manifest["books"]:
            log.warning("book_id not in manifest, skipping: %s", book_id)
            continue

        # Validate and normalise
        category = item.get("category", "尚未歸檔")
        if category not in VALID_CATEGORIES:
            log.warning("Invalid category '%s' for %s, setting 尚未歸檔", category, book_id)
            category = "尚未歸檔"
        item["category"] = category

        item = _enrich_with_subfolder(item, manifest)

        update_book(book_id, {
            "category": category,
            "series": item.get("series", ""),
            "author": item.get("author", ""),
            "classification": item,
            "status": "classified",
        })

        record_book_action("classified", book_id, {
            "category": category,
            "confidence": item.get("confidence"),
        })

        classifications[book_id] = item
        conf = item.get("confidence", 0)
        flag = "low-conf→Inbox" if conf < CLASSIFY_CONFIDENCE_THRESHOLD else "ok"
        log.info("Applied: %s → %s (conf=%.2f) [%s]", book_id, category, conf, flag)

    log.info("apply_batch complete: %d/%d classifications applied", len(classifications), len(results))
    record("apply_batch", details={"applied": len(classifications), "total": len(results)})
    return classifications


# ---------------------------------------------------------------------------
# Convenience: read pending file (for Claude Code to inspect)
# ---------------------------------------------------------------------------

def read_pending() -> dict | None:
    if not PENDING_FILE.exists():
        log.warning("No pending batch file found at %s", PENDING_FILE)
        return None
    return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
