"""ebook2md command line.

    ebook2md convert BOOK [BOOK ...] [-o DIR] [--name FILE.md]
    ebook2md slice BOOK [-o CHAPTERS.json]
"""
import argparse
import json
import sys
from pathlib import Path

from . import __version__


def _convert(args) -> int:
    from .epub import epub2md
    from .pdf import pdf2md

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.name and len(args.books) > 1:
        print("--name only works with a single book", file=sys.stderr)
        return 2
    failed = 0
    for book in map(Path, args.books):
        kind = book.suffix.lower()
        try:
            if kind == ".epub":
                ok = epub2md.process_epub(str(book), str(out_dir), args.name)
                failed += not ok
            elif kind == ".pdf":
                usable, why = pdf2md.text_layer(book)
                if not usable:
                    # scans and fonts without a Unicode map: no OCR here
                    print(f"Skipped (no usable text layer: {why}): {book}")
                    failed += 1
                    continue
                path, stats = pdf2md.convert(book, out_dir, out_name=args.name)
                print(f"Successfully converted to: {path}")
            else:
                print(f"Not an .epub or .pdf file: {book}", file=sys.stderr)
                failed += 1
        except Exception as e:  # one broken book must not stop the others
            print(f"Failed: {book}: {e}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def _slice(args) -> int:
    from . import slicing

    book = Path(args.book)
    if book.suffix.lower() == ".epub":
        chapters, report = slicing.slice_epub(book)
    else:
        chapters, report = slicing.slice_md(book.read_text(encoding="utf-8"))
    if report:
        slicing.print_report(report, chapters)
    if not chapters or not report.get("self_check"):
        print("Slicing failed: no chapters, or the chapters do not re-join to the source text",
              file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else book.with_suffix(".chapters.json")
    payload = {"source": book.name, "converter": f"ebook2md {__version__}", "report": report,
               "chapters": chapters}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(chapters)} chapters -> {out}")
    return 0


def main(argv=None) -> int:
    # Windows consoles default to cp950/cp1252; book titles must not crash printing
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="ebook2md", description="EPUB / PDF books to Markdown, and books to chapters.")
    ap.add_argument("--version", action="version", version=f"ebook2md {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("convert", help="convert .epub / .pdf books to Markdown")
    c.add_argument("books", nargs="+", help=".epub or .pdf files")
    c.add_argument("-o", "--output", default=".", help="output folder (default: current folder)")
    c.add_argument("--name", help="output file name, single book only "
                                  "(default: '{title}_{author}.md' for EPUB, '{file name}.md' for PDF)")

    s = sub.add_parser("slice", help="cut an .epub or a converted .md into chapters (JSON)")
    s.add_argument("book", help=".epub, or an .md written by 'ebook2md convert'")
    s.add_argument("-o", "--output", help="JSON file to write (default: next to the book, .chapters.json)")

    args = ap.parse_args(argv)
    return {"convert": _convert, "slice": _slice}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
