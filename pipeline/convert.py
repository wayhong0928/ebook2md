"""
Wraps epub_to_markdown to batch-convert EPUBs to Markdown.
Outputs to MARKDOWN_STAGING (待分類/) until classify assigns a category.
Skips EPUBs that already have a corresponding MD file.
"""
import subprocess
import sys
from pathlib import Path

from config import EPUB2MD_SCRIPT, MARKDOWN_STAGING
from logger import get_logger
from activity import record_book_action
from manifest import load_manifest, update_book, scan, find_md_for_epub

log = get_logger("convert")


def convert_one(epub_path: Path, force: bool = False) -> Path | None:
    stem = epub_path.stem
    existing = find_md_for_epub(stem)
    if existing and not force:
        log.debug("Skip (already converted): %s", epub_path.name)
        return existing

    MARKDOWN_STAGING.mkdir(parents=True, exist_ok=True)
    log.info("Converting: %s", epub_path.name)

    result = subprocess.run(
        [sys.executable, str(EPUB2MD_SCRIPT), str(epub_path), str(MARKDOWN_STAGING),
         "--output-name", f"{stem}.md"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        log.error("Conversion failed: %s\n%s%s", epub_path.name, result.stdout, result.stderr)
        return None

    # Named after the EPUB stem so manifest.find_md_for_epub() can match it.
    output_md = MARKDOWN_STAGING / f"{stem}.md"
    if output_md.exists():
        log.info("Converted: %s → %s", epub_path.name, output_md.name)
        return output_md

    log.error("Output MD not found after conversion: %s", epub_path.name)
    return None


def convert_one_pdf(pdf_path: Path, force: bool = False, author: str = "") -> Path | None:
    """PDF with a text layer -> md via pdf2md. Scans and PDFs whose fonts
    have no Unicode map are skipped (no OCR) and get no md."""
    import pdf2md

    stem = pdf_path.stem
    existing = find_md_for_epub(stem)
    if existing and not force:
        log.debug("Skip (already converted): %s", pdf_path.name)
        return existing

    ok, why = pdf2md.text_layer(pdf_path)
    if not ok:
        log.warning("PDF not converted (%s): %s", why, pdf_path.name)
        return None

    MARKDOWN_STAGING.mkdir(parents=True, exist_ok=True)
    log.info("Converting PDF: %s", pdf_path.name)

    try:
        output_md, _ = pdf2md.convert(pdf_path, MARKDOWN_STAGING, author=author, out_name=f"{stem}.md")
        log.info("Converted PDF: %s → %s", pdf_path.name, output_md.name)
        return output_md
    except Exception as exc:
        log.error("PDF conversion failed: %s\n%s", pdf_path.name, exc)
        return None


def convert_batch(book_ids: list[str] | None = None, force: bool = False) -> dict[str, Path]:
    manifest = load_manifest()
    books = manifest["books"]

    if book_ids is None:
        targets = {
            k: v for k, v in books.items()
            if v.get("status") == "raw" or (force and (v.get("epub_path") or v.get("pdf_path")))
        }
    else:
        targets = {k: books[k] for k in book_ids if k in books}

    results = {}
    log.info("Convert batch started: %d book(s)", len(targets))
    print(f"Converting {len(targets)} book(s)...")

    for book_id, entry in targets.items():
        if entry.get("epub_path"):
            md_path = convert_one(Path(entry["epub_path"]), force=force)
        elif entry.get("pdf_path"):
            md_path = convert_one_pdf(Path(entry["pdf_path"]), force=force, author=entry.get("author", ""))
        else:
            log.warning("No source file for: %s", book_id)
            continue
        if md_path:
            update_book(book_id, {"md_path": md_path.as_posix(), "status": "converted"})
            record_book_action("converted", book_id, {"md_path": md_path.as_posix()})
            results[book_id] = md_path

    log.info("Convert batch complete: %d/%d succeeded", len(results), len(targets))
    print(f"Done. {len(results)}/{len(targets)} converted.")
    return results


if __name__ == "__main__":
    scan(verbose=False)
    convert_batch()
