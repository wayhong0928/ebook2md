"""
Creates Obsidian book card .md files from classification results.
High-confidence books go directly to 10_Books/[category]/
Low-confidence books go to 00_Inbox/ for manual review.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

from config import (
    VAULT_BOOKS, VAULT_INBOX, CLASSIFY_CONFIDENCE_THRESHOLD,
)
from logger import get_logger
from activity import record_book_action
from manifest import load_manifest, update_book

log = get_logger("create_book_card")


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()


def _determine_output_dir(category: str, classification: dict) -> Path:
    confidence = classification.get("confidence", 0)

    if confidence < CLASSIFY_CONFIDENCE_THRESHOLD:
        log.debug("Low confidence (%.2f) → routing to Inbox", confidence)
        return VAULT_INBOX

    base_dir = VAULT_BOOKS / category
    subfolder = classification.get("subfolder_name", "").strip()
    if classification.get("needs_subfolder") and subfolder:
        base_dir = base_dir / _sanitize_filename(subfolder)

    return base_dir


def _render_book_card(book_id: str, entry: dict, classification: dict, source_path: Path, md_path: Path | None) -> str:
    title = classification.get("title") or entry.get("title") or source_path.stem
    author = classification.get("author") or entry.get("author", "")
    category = classification.get("category", "尚未歸檔")
    sub_categories = classification.get("sub_categories", [])
    series = classification.get("series", "")
    volume = classification.get("volume")
    core_premise = classification.get("core_premise", "")
    toc_summary = classification.get("toc_summary", "")
    tags = ["#type/book"] + classification.get("tags", [])
    today = date.today().isoformat()

    sub_cat_yaml = json.dumps(sub_categories, ensure_ascii=False)
    tags_yaml = "\n".join(f'  - "{t}"' for t in tags)
    # Not every book originates from an EPUB (some are PDF-only sources);
    # record whichever source files actually exist instead of assuming EPUB.
    source_epub = entry.get("epub_path") or ""
    source_pdf = entry.get("pdf_path") or ""
    source_md = md_path.as_posix() if md_path else ""
    series_line = f'series: "{series}"\n' if series else ""
    volume_line = f"volume: {volume}\n" if volume is not None else ""

    return f"""---
title: "{title}"
author: "{author}"
category: "{category}"
sub_categories: {sub_cat_yaml}
{series_line}{volume_line}tags:
{tags_yaml}
core_premise: "{core_premise}"
source_epub: "{source_epub}"
source_pdf: "{source_pdf}"
source_md: "{source_md}"
date_added: "{today}"
status: "card_only"
---

## 核心前提
{core_premise}

## 目錄摘要
{toc_summary}

---

## 章節筆記
*尚未生成，Phase 2 補入*

## 全書概念連結
*尚未生成，Phase 2 補入*

## MOC 連結建議
- 可加入：[[_{category}_MOC]]
- 相關概念：*尚未生成，Phase 2 補入*

## 整體心得
"""


def create_card(book_id: str, classification: dict, dry_run: bool = False) -> Path | None:
    manifest = load_manifest()
    entry = manifest["books"].get(book_id)
    if not entry:
        log.error("book_id not in manifest: %s", book_id)
        return None

    epub_path = Path(entry["epub_path"]) if entry.get("epub_path") else None
    pdf_path = Path(entry["pdf_path"]) if entry.get("pdf_path") else None
    md_path = Path(entry["md_path"]) if entry.get("md_path") else None
    # Prefer EPUB as the filename/title source, but fall back to PDF or MD
    # for books that were converted directly from PDF (no EPUB on record).
    source_path = epub_path or pdf_path or md_path
    if source_path is None:
        log.error("No source file (epub/pdf/md) recorded for: %s", book_id)
        return None
    category = classification.get("category", "尚未歸檔")

    out_dir = _determine_output_dir(category, classification)
    card_filename = _sanitize_filename(source_path.stem) + ".md"
    card_path = out_dir / card_filename

    content = _render_book_card(book_id, entry, classification, source_path, md_path)

    if dry_run:
        log.info("[dry-run] Would write card: %s", card_path)
        print(f"\n  [dry-run] Would write card to: {card_path}")
        print(content[:300] + "...")
        return card_path

    out_dir.mkdir(parents=True, exist_ok=True)
    card_path.write_text(content, encoding="utf-8")

    update_book(book_id, {
        "obsidian_card": card_path.as_posix(),
        "status": "card_only",
    })
    record_book_action("card_created", book_id, {
        "card_path": card_path.as_posix(),
        "category": category,
        "confidence": classification.get("confidence"),
    })

    loc = "Inbox" if out_dir == VAULT_INBOX else category
    log.info("Card created in %s: %s", loc, card_filename)
    print(f"  [ok] card → {loc}: {card_filename}")
    return card_path


def create_cards_batch(classifications: dict[str, dict], dry_run: bool = False) -> dict[str, Path]:
    results = {}
    log.info("Creating cards batch: %d book(s)", len(classifications))
    print(f"Creating {len(classifications)} Obsidian card(s)...")
    for book_id, classification in classifications.items():
        path = create_card(book_id, classification, dry_run=dry_run)
        if path:
            results[book_id] = path
    log.info("Cards batch complete: %d/%d created", len(results), len(classifications))
    print(f"Done. {len(results)}/{len(classifications)} cards created.")
    return results
