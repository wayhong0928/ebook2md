"""
Three-file sync: moves EPUB + MD + Obsidian card together when reclassifying.
Updates manifest and activity log after every move.
"""
import re
import shutil
import sys
from pathlib import Path

from config import EBOOKS_ROOT, MARKDOWN_ROOT, VAULT_BOOKS, VALID_CATEGORIES
from logger import get_logger
from activity import record_book_action
from manifest import load_manifest, update_book

log = get_logger("sync")


def _target_dir(base: Path, category: str, subfolder: str = "") -> Path:
    d = base / category
    return d / subfolder if subfolder else d


def _safe_move(src: Path, dst_dir: Path, dry_run: bool = False) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst == src:
        return src
    if dry_run:
        log.debug("[dry-run] move: %s → %s", src, dst)
        return dst
    shutil.move(str(src), str(dst))
    log.debug("Moved: %s → %s", src.name, dst_dir)
    return dst


def _sync_card_frontmatter(card_path: Path, epub_value: str, md_value: str, pdf_value: str = "", category_value: str | None = None, dry_run: bool = False) -> list[str]:
    """Rewrite source_epub/source_pdf/source_md/category lines inside an Obsidian card's frontmatter in place.
    Returns list of field names skipped because the line wasn't found (old-format cards)."""
    text = card_path.read_text(encoding="utf-8")
    skipped = []
    changed = False

    fields = [("source_epub", epub_value), ("source_pdf", pdf_value), ("source_md", md_value)]
    if category_value is not None:
        fields.append(("category", category_value))

    for field, value in fields:
        pattern = re.compile(rf'^{field}:\s*".*?"\s*$', re.MULTILINE)
        new_text, n = pattern.subn(f'{field}: "{value}"', text, count=1)
        if n:
            text = new_text
            changed = True
        else:
            skipped.append(field)

    if category_value is not None:
        moc_pattern = re.compile(r'^- 可加入：\[\[_.*?_MOC\]\]\s*$', re.MULTILINE)
        new_text, n = moc_pattern.subn(f'- 可加入：[[_{category_value}_MOC]]', text, count=1)
        if n:
            text = new_text
            changed = True
        else:
            skipped.append("moc_suggestion")

    if not dry_run and changed:
        card_path.write_text(text, encoding="utf-8")

    return skipped


def reclassify(
    book_id: str,
    new_category: str,
    new_classification: dict | None = None,
    dry_run: bool = False,
) -> bool:
    if new_category not in VALID_CATEGORIES:
        log.error("Invalid category: '%s'", new_category)
        return False

    manifest = load_manifest()
    entry = manifest["books"].get(book_id)
    if not entry:
        log.error("book_id not found: %s", book_id)
        return False

    old_category = entry.get("category", "unknown")
    subfolder = new_classification.get("subfolder_name", "") if new_classification else ""

    log.info("Reclassify: %s | %s → %s", book_id, old_category, new_category)
    updates = {}

    # Move EPUB
    if entry.get("epub_path"):
        epub_path = Path(entry["epub_path"])
        if epub_path.exists():
            new_epub = _safe_move(epub_path, _target_dir(EBOOKS_ROOT, new_category, subfolder), dry_run=dry_run)
            updates["epub_path"] = new_epub.as_posix()
            print(f"  [epub] → {new_epub.parent.name}/{new_epub.name}")
        else:
            log.warning("EPUB not found: %s", epub_path)

    # Move PDF
    if entry.get("pdf_path"):
        pdf_path = Path(entry["pdf_path"])
        if pdf_path.exists():
            new_pdf = _safe_move(pdf_path, _target_dir(EBOOKS_ROOT, new_category, subfolder), dry_run=dry_run)
            updates["pdf_path"] = new_pdf.as_posix()
            print(f"  [pdf]  → {new_pdf.parent.name}/{new_pdf.name}")
        else:
            log.warning("PDF not found: %s", pdf_path)

    # Move MD
    if entry.get("md_path"):
        md_path = Path(entry["md_path"])
        if md_path.exists():
            new_md = _safe_move(md_path, _target_dir(MARKDOWN_ROOT, new_category, subfolder), dry_run=dry_run)
            updates["md_path"] = new_md.as_posix()
            print(f"  [md]   → {new_md.parent.name}/{new_md.name}")

    # Move Obsidian note
    if entry.get("obsidian_card"):
        card_path = Path(entry["obsidian_card"])
        if card_path.exists():
            new_card = _safe_move(card_path, _target_dir(VAULT_BOOKS, new_category, subfolder), dry_run=dry_run)
            updates["obsidian_card"] = new_card.as_posix()
            print(f"  [note] → {new_card.parent.name}/{new_card.name}")

    if not dry_run:
        updates["category"] = new_category
        if new_classification:
            updates["classification"] = new_classification
        update_book(book_id, updates)
        record_book_action("reclassified", book_id, {
            "from": old_category,
            "to": new_category,
        })
        log.info("Reclassify complete: %s → %s", book_id, new_category)
        print(f"  [ok] Manifest updated.")

        # Sync Obsidian card frontmatter (source_epub/source_md) to the new paths.
        new_card = updates.get("obsidian_card") or entry.get("obsidian_card")
        if new_card:
            card_path = Path(new_card)
            if card_path.exists():
                # entry.get(key, "") only falls back to "" when the key is
                # missing entirely; if the key exists but is explicitly None
                # (e.g. no EPUB on record, PDF-only source), it still returns
                # None. Coalesce explicitly so we never stringify None into
                # the literal text "None" in the frontmatter.
                epub_value = updates.get("epub_path") or entry.get("epub_path") or ""
                pdf_value = updates.get("pdf_path") or entry.get("pdf_path") or ""
                md_value = updates.get("md_path") or entry.get("md_path") or ""
                skipped = _sync_card_frontmatter(card_path, epub_value, md_value, pdf_value=pdf_value, category_value=new_category)
                if skipped:
                    log.warning("Card frontmatter fields not found/skipped for %s: %s", book_id, skipped)
                    print(f"  [warn] Card frontmatter fields skipped ({card_path.name}): {skipped}")
            else:
                log.warning("Obsidian card not found, skipping frontmatter sync: %s", card_path)
        else:
            log.warning("No obsidian_card path for %s, skipping frontmatter sync", book_id)

    return True


def move_from_inbox(book_id: str, dry_run: bool = False) -> bool:
    manifest = load_manifest()
    entry = manifest["books"].get(book_id)
    if not entry:
        log.error("book_id not found: %s", book_id)
        return False

    category = entry.get("category", "尚未歸檔")
    classification = entry.get("classification", {})
    subfolder = classification.get("subfolder_name", "") if classification else ""

    obsidian_card = entry.get("obsidian_card")
    if not obsidian_card:
        log.error("No Obsidian card path in manifest for %s", book_id)
        return False

    card_path = Path(obsidian_card)
    if not card_path.exists():
        log.error("Card file not found: %s", card_path)
        return False

    new_card_dir = VAULT_BOOKS / category
    if subfolder:
        new_card_dir = new_card_dir / subfolder

    new_card = _safe_move(card_path, new_card_dir, dry_run=dry_run)

    if not dry_run:
        update_book(book_id, {"obsidian_card": new_card.as_posix()})
        record_book_action("moved_from_inbox", book_id, {
            "category": category,
            "card_path": new_card.as_posix(),
        })
        log.info("Moved from Inbox: %s → %s/%s", book_id, new_card.parent.name, new_card.name)
        print(f"  [ok] Moved to {new_card.parent.name}/: {new_card.name}")

    return True
