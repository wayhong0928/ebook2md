"""
Main CLI entry point for the epub → Obsidian classification pipeline.

Workflow (no API key required):
  1. python run_pipeline.py scan
  2. python run_pipeline.py convert --all
  3. python run_pipeline.py prepare-batch --limit 20
     → ask Claude Code: "請分類 pipeline/pending_classify.json，輸出到 pipeline/classify_results.json"
  4. python run_pipeline.py apply-batch
  5. python run_pipeline.py reclassify --book-id "<id>"   (if needed)
  6. python run_pipeline.py inbox-move --book-id "<id>"   (approve inbox cards)

Other commands:
  python run_pipeline.py log           (show recent activity)
  python run_pipeline.py history --book-id "<id>"
"""
import argparse
import sys
from pathlib import Path

# Windows terminals often default to the cp950/cp936 codepage, which cannot
# encode rare CJK characters (e.g. "〇") that show up in some book titles.
# That previously crashed print()/log calls mid-command (see CLAUDE.md
# "書名／檔名含罕見中文字元...cp950 codepage 無法編碼而崩潰"). Force UTF-8
# on stdout/stderr so callers no longer need to remember a PYTHONIOENCODING
# prefix by hand.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

sys.path.insert(0, str(Path(__file__).parent))

from logger import get_logger
from activity import print_recent, book_history, record
from manifest import scan, load_manifest, get_books_needing_processing
from convert import convert_batch, convert_one
from classify import prepare_batch, apply_batch, RESULTS_FILE
from create_book_card import create_card, create_cards_batch
from sync import reclassify, move_from_inbox
from notes import prepare_notes, apply_notes, split_pending_notes, merge_notes_results, NOTES_RESULTS_FILE

log = get_logger("pipeline")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_scan(args):
    record("scan_started")
    manifest = scan(verbose=True)
    record("scan_complete", details={"total": len(manifest["books"])})


def cmd_convert(args):
    if args.book:
        epub_path = Path(args.book)
        if not epub_path.exists():
            log.error("File not found: %s", epub_path)
            sys.exit(1)
        md_path = convert_one(epub_path, force=args.force)
        if not md_path:
            sys.exit(1)
    elif args.all:
        manifest = scan(verbose=False)
        pending = get_books_needing_processing(manifest)
        if not pending:
            print("No books pending conversion. Run 'scan' first.")
            return
        convert_batch(book_ids=[b["id"] for b in pending], force=args.force)
    else:
        print("Error: specify --all or --book <path>", file=sys.stderr)
        sys.exit(1)


def cmd_prepare_batch(args):
    prepare_batch(limit=args.limit, force=args.force)


def cmd_apply_batch(args):
    results_path = Path(args.input) if args.input else RESULTS_FILE
    if not results_path.exists():
        log.error("Results file not found: %s", results_path)
        print(f"\nResults file not found: {results_path}")
        print("Ask Claude Code to classify pending_classify.json first.")
        sys.exit(1)

    classifications = apply_batch(results_path)
    if not classifications:
        print("No classifications applied.")
        return

    if args.cards:
        print(f"\n=== Creating Obsidian cards ===")
        create_cards_batch(classifications, dry_run=args.dry_run)
    else:
        print(f"\n{len(classifications)} classifications applied to manifest.")
        print("Run with --cards to also create Obsidian cards, or run 'create-cards' separately.")


def cmd_create_cards(args):
    manifest = load_manifest()
    if args.book_id:
        entry = manifest["books"].get(args.book_id)
        if not entry or not entry.get("classification"):
            log.error("No classification found for: %s", args.book_id)
            sys.exit(1)
        create_card(args.book_id, entry["classification"], dry_run=args.dry_run)
    else:
        classified = {
            k: v["classification"]
            for k, v in manifest["books"].items()
            if v.get("status") == "classified" and v.get("classification")
        }
        if not classified:
            print("No classified books without cards found.")
            return
        create_cards_batch(classified, dry_run=args.dry_run)


def cmd_reclassify(args):
    if not args.book_id:
        print("Error: --book-id required", file=sys.stderr)
        sys.exit(1)
    manifest = load_manifest()
    entry = manifest["books"].get(args.book_id, {})
    existing_classification = entry.get("classification")
    if existing_classification:
        existing_classification = dict(existing_classification)
        existing_classification["category"] = args.category
    reclassify(
        args.book_id,
        args.category,
        new_classification=existing_classification,
        dry_run=args.dry_run,
    )


def cmd_inbox_move(args):
    if not args.book_id:
        print("Error: --book-id required", file=sys.stderr)
        sys.exit(1)
    move_from_inbox(args.book_id, dry_run=args.dry_run)


def cmd_prepare_notes(args):
    if not args.book_id:
        print("Error: --book-id required", file=sys.stderr)
        sys.exit(1)
    prepare_notes(args.book_id, max_chapters=args.max_chapters)


def cmd_apply_notes(args):
    from pathlib import Path
    results_path = Path(args.input) if args.input else NOTES_RESULTS_FILE
    if not results_path.exists():
        log.error("Notes results not found: %s", results_path)
        print(f"\nNotes results not found: {results_path}")
        print("Ask Claude Code to generate notes first.")
        sys.exit(1)
    apply_notes(results_path)


def cmd_split_notes(args):
    split_pending_notes(max_chars_per_batch=args.max_chars)


def cmd_merge_notes(args):
    if not args.book_id:
        print("Error: --book-id required", file=sys.stderr)
        sys.exit(1)
    merge_notes_results(args.book_id, args.batches)


def cmd_log(args):
    print_recent(n=args.n)


def cmd_history(args):
    if not args.book_id:
        print("Error: --book-id required", file=sys.stderr)
        sys.exit(1)
    book_history(args.book_id)


def cmd_process_new(args):
    """
    Full pipeline for new EPUBs (scan → convert → prepare-batch).
    After this, ask Claude Code to classify, then run apply-batch --cards.
    """
    print("=== Step 1: Scan library ===")
    record("process_new_started")
    manifest = scan(verbose=True)

    print("\n=== Step 2: Convert new EPUBs ===")
    pending = get_books_needing_processing(manifest)
    epub_only = [b for b in pending if (b.get("epub_path") or "").endswith(".epub")]
    if not epub_only:
        print("No new EPUBs to convert.")
    else:
        convert_batch(book_ids=[b["id"] for b in epub_only], force=False)

    print("\n=== Step 3: Prepare classification batch ===")
    prepare_batch(limit=args.limit, force=False)

    print("\n" + "=" * 60)
    print("Ready for classification.")
    print("Tell Claude Code:")
    print('  "請分類 pipeline/pending_classify.json 裡的書，輸出到 pipeline/classify_results.json"')
    print("\nThen run:")
    print("  python pipeline/run_pipeline.py apply-batch --cards")


def cmd_status(args):
    manifest = load_manifest()
    books = manifest["books"]
    from collections import Counter
    counts = Counter(v.get("status", "unknown") for v in books.values())
    print(f"=== Book Library Status (last scan: {manifest.get('last_scan', 'never')}) ===")
    print(f"  Total:                  {len(books)}")
    for status, count in sorted(counts.items()):
        print(f"  {status:<28} {count}")
    print(f"\nLog file: {__import__('config').PIPELINE_DIR / 'logs' / 'pipeline.log'}")
    print(f"Activity: {__import__('config').PIPELINE_DIR / 'activity_log.jsonl'}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Claude × Obsidian Book Classification Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    sub.add_parser("scan", help="Scan Ebooks library and update manifest")

    # status
    sub.add_parser("status", help="Show library status summary")

    # convert
    p_convert = sub.add_parser("convert", help="Convert EPUBs to Markdown")
    p_convert.add_argument("--all", action="store_true")
    p_convert.add_argument("--book", metavar="PATH")
    p_convert.add_argument("--force", action="store_true")

    # process-new (master command)
    p_process_new = sub.add_parser(
        "process-new",
        help="Full pipeline: scan → convert new EPUBs → prepare classify batch",
    )
    p_process_new.add_argument(
        "--limit", type=int, default=20, metavar="N",
        help="Max books per classification batch (default: 20)",
    )

    # prepare-batch
    p_prepare = sub.add_parser("prepare-batch", help="Export books for Claude Code to classify")
    p_prepare.add_argument("--limit", type=int, default=20, metavar="N",
                           help="Max books per batch (default: 20)")
    p_prepare.add_argument("--force", action="store_true",
                           help="Re-export even if already classified")

    # apply-batch
    p_apply = sub.add_parser("apply-batch", help="Apply Claude Code's classification results")
    p_apply.add_argument("--input", metavar="PATH",
                         help=f"Results JSON (default: pipeline/classify_results.json)")
    p_apply.add_argument("--cards", action="store_true",
                         help="Also create Obsidian cards after applying")
    p_apply.add_argument("--dry-run", action="store_true")

    # create-cards
    p_cards = sub.add_parser("create-cards", help="Create Obsidian cards for classified books")
    p_cards.add_argument("--book-id", metavar="ID")
    p_cards.add_argument("--dry-run", action="store_true")

    # prepare-notes
    p_prep_notes = sub.add_parser("prepare-notes", help="Export chapter content for Claude Code to generate notes")
    p_prep_notes.add_argument("--book-id", required=True, metavar="ID")
    p_prep_notes.add_argument("--max-chapters", type=int, default=None, metavar="N",
                              help="限制章節數（預設不限制，整本書都會處理；只有轉檔異常大量章節時才需要用這個暫時限縮）")

    # apply-notes
    p_apply_notes = sub.add_parser("apply-notes", help="Apply Claude Code's generated notes to Obsidian")
    p_apply_notes.add_argument("--input", metavar="PATH",
                               help="Notes results JSON (default: pipeline/notes_results.json)")

    # split-notes
    p_split_notes = sub.add_parser("split-notes", help="Split a large pending_notes.json into per-batch files for multiple subagents")
    p_split_notes.add_argument("--max-chars", type=int, default=150_000, metavar="N",
                               help="單一subagent批次的字元上限（預設150,000）")

    # merge-notes
    p_merge_notes = sub.add_parser("merge-notes", help="Merge notes_results_batch{N}.json files back into one notes_results.json")
    p_merge_notes.add_argument("--book-id", required=True, metavar="ID")
    p_merge_notes.add_argument("--batches", type=int, required=True, metavar="N")

    # reclassify
    p_reclassify = sub.add_parser("reclassify", help="Move book to a different category (3-file sync)")
    p_reclassify.add_argument("--book-id", required=True, metavar="ID")
    p_reclassify.add_argument("--category", required=True, metavar="CAT")
    p_reclassify.add_argument("--dry-run", action="store_true")

    # inbox-move
    p_inbox = sub.add_parser("inbox-move", help="Approve and move card from 00_Inbox to 10_Books")
    p_inbox.add_argument("--book-id", required=True, metavar="ID")
    p_inbox.add_argument("--dry-run", action="store_true")

    # log
    p_log = sub.add_parser("log", help="Show recent activity log")
    p_log.add_argument("--n", type=int, default=20, metavar="N")

    # history
    p_history = sub.add_parser("history", help="Show history for a specific book")
    p_history.add_argument("--book-id", required=True, metavar="ID")

    args = parser.parse_args()

    commands = {
        "scan": cmd_scan,
        "status": cmd_status,
        "convert": cmd_convert,
        "process-new": cmd_process_new,
        "prepare-batch": cmd_prepare_batch,
        "apply-batch": cmd_apply_batch,
        "create-cards": cmd_create_cards,
        "prepare-notes": cmd_prepare_notes,
        "apply-notes": cmd_apply_notes,
        "split-notes": cmd_split_notes,
        "merge-notes": cmd_merge_notes,
        "reclassify": cmd_reclassify,
        "inbox-move": cmd_inbox_move,
        "log": cmd_log,
        "history": cmd_history,
    }

    log.debug("Command invoked: %s", args.command)
    commands[args.command](args)


if __name__ == "__main__":
    main()
