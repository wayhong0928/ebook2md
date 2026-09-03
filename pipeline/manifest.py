"""
Scans the Ebooks library and Obsidian vault to build/update manifest.json.
Tracks every EPUB's conversion and classification state.
"""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from config import (
    EBOOKS_ROOT, MARKDOWN_ROOT, VAULT_BOOKS, VAULT_INBOX,
    MANIFEST_PATH, VALID_CATEGORIES,
)
from logger import get_logger

log = get_logger("manifest")


def _make_book_id(path: Path) -> str:
    return path.stem.replace(" ", "_")


def find_md_for_epub(epub_stem: str, md_index: dict[str, Path] | None = None) -> Path | None:
    if md_index is not None:
        return md_index.get(epub_stem)
    return next((p for p in MARKDOWN_ROOT.rglob("*.md") if p.stem == epub_stem), None)


def _find_obsidian_card(epub_stem: str, card_index: dict[str, Path] | None = None) -> Path | None:
    short = epub_stem.rsplit("_", 1)[0]
    if card_index is not None:
        return card_index.get(epub_stem) or card_index.get(short)
    for p in list(VAULT_BOOKS.rglob("*.md")) + list(VAULT_INBOX.rglob("*.md")):
        if p.stem == epub_stem or p.stem == short:
            return p
    return None


def _infer_category_from_path(epub_path: Path) -> str:
    for part in epub_path.parts:
        if part in VALID_CATEGORIES:
            return part
    return "尚未歸檔"


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"last_scan": None, "books": {}}


def save_manifest(manifest: dict) -> None:
    manifest["last_scan"] = datetime.now().isoformat()
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def scan(verbose: bool = True) -> dict:
    manifest = load_manifest()
    books = manifest.get("books", {})

    epub_files = list(EBOOKS_ROOT.rglob("*.epub"))
    pdf_files = list(EBOOKS_ROOT.rglob("*.pdf"))
    log.info("Scan started: found %d EPUB, %d PDF files in %s", len(epub_files), len(pdf_files), EBOOKS_ROOT)

    # Build lookup indexes once — avoids O(n²) rglob calls
    md_index: dict[str, Path] = {p.stem: p for p in MARKDOWN_ROOT.rglob("*.md")}
    card_index: dict[str, Path] = {
        p.stem: p
        for p in list(VAULT_BOOKS.rglob("*.md")) + list(VAULT_INBOX.rglob("*.md"))
    }

    new_count = 0
    for epub_path in epub_files:
        book_id = _make_book_id(epub_path)
        md_path = find_md_for_epub(epub_path.stem, md_index)
        obsidian_card = _find_obsidian_card(epub_path.stem, card_index)

        if book_id not in books:
            books[book_id] = {
                "epub_path": epub_path.as_posix(),
                "pdf_path": None,
                "md_path": md_path.as_posix() if md_path else None,
                "obsidian_card": obsidian_card.as_posix() if obsidian_card else None,
                "category": _infer_category_from_path(epub_path),
                "series": "",
                "author": "",
                "status": "card_only" if obsidian_card else ("converted" if md_path else "raw"),
                "last_processed": None,
                "activity_history": [],
            }
            new_count += 1
            log.debug("New book registered: %s", book_id)
        else:
            entry = books[book_id]
            entry["epub_path"] = epub_path.as_posix()
            if md_path:
                entry["md_path"] = md_path.as_posix()
                log.debug("MD path updated: %s", book_id)
            if obsidian_card and not entry.get("obsidian_card"):
                entry["obsidian_card"] = obsidian_card.as_posix()
                if entry.get("status") in ("raw", "converted"):
                    entry["status"] = "card_only"

    # Scan PDFs — only register PDF-only books; if EPUB exists, just record pdf_path
    pdf_new_count = 0
    for pdf_path in pdf_files:
        book_id = _make_book_id(pdf_path)
        if book_id in books:
            if not books[book_id].get("pdf_path"):
                books[book_id]["pdf_path"] = pdf_path.as_posix()
            continue

        md_path = find_md_for_epub(pdf_path.stem, md_index)
        obsidian_card = _find_obsidian_card(pdf_path.stem, card_index)
        books[book_id] = {
            "epub_path": None,
            "pdf_path": pdf_path.as_posix(),
            "md_path": md_path.as_posix() if md_path else None,
            "obsidian_card": obsidian_card.as_posix() if obsidian_card else None,
            "category": _infer_category_from_path(pdf_path),
            "series": "",
            "author": "",
            "status": "card_only" if obsidian_card else ("converted" if md_path else "raw"),
            "last_processed": None,
            "activity_history": [],
        }
        pdf_new_count += 1
        log.debug("New PDF-only book registered: %s", book_id)

    manifest["books"] = books
    save_manifest(manifest)

    counts = Counter(b["status"] for b in books.values())

    log.info(
        "Scan complete: total=%d epub_new=%d pdf_new=%d raw=%d converted=%d classified=%d card_only=%d",
        len(books), new_count, pdf_new_count,
        counts["raw"], counts["converted"], counts["classified"], counts["card_only"],
    )

    if verbose:
        print(f"Found {len(epub_files)} EPUB + {len(pdf_files)} PDF files. ({new_count} EPUB new, {pdf_new_count} PDF-only new)")
        print(f"  raw (not converted):           {counts['raw']}")
        print(f"  converted (awaiting classify): {counts['converted']}")
        print(f"  classified (awaiting card):    {counts['classified']}")
        print(f"  card_only (Obsidian card done):{counts['card_only']}")
        print(f"Manifest saved to: {MANIFEST_PATH}")

    return manifest


def get_books_needing_processing(manifest: dict) -> list[dict]:
    return [
        {"id": k, **v}
        for k, v in manifest["books"].items()
        if v.get("status") in ("raw", "converted")
    ]


def update_book(book_id: str, updates: dict) -> None:
    manifest = load_manifest()
    if book_id not in manifest["books"]:
        log.warning("update_book: book_id '%s' not in manifest", book_id)
        return
    manifest["books"][book_id].update(updates)
    manifest["books"][book_id]["last_processed"] = datetime.now().isoformat()
    save_manifest(manifest)
    log.debug("Manifest updated: %s → %s", book_id, updates.get("status", "(no status change)"))


def count_books_by_field(field: str, value: str, manifest: dict) -> int:
    if not value:
        return 0
    return sum(
        1 for b in manifest["books"].values()
        if b.get(field, "").strip() == value.strip()
    )


if __name__ == "__main__":
    scan()
