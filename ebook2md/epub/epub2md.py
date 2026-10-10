import os
import re
import sys
import datetime
from .. import front_matter, strip_control_chars
from .extractor import EpubExtractor
from .cleaner import EpubCleaner, _matches_title
from .converter import EpubConverter


def sanitize_filename(name):
    """
    Sanitize the string to be safe for filenames.
    """
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()


def _needs_file_title(md, title, depth):
    """
    True when the document's Markdown doesn't already open with its TOC title.
    Looks at the run of headings at the top, since titles are often split
    ('###### 01' + '# 章名' for TOC '01 章名'). A run made only of
    deeper headings (e.g. the first sub-section) doesn't count as the title.
    """
    heads = []
    for line in md.splitlines():
        line = line.strip()
        if not line or re.fullmatch(r"\[圖片[^\]]*\]", line):
            continue
        m = re.match(r"^(#+)\s+(.*)", line)
        if not m:
            break
        heads.append((len(m.group(1)), m.group(2)))
    if not heads:
        return True
    if any(_matches_title(text, title) for _, text in heads):
        return False
    if _matches_title("".join(text for _, text in heads), title):
        return False
    return min(level for level, _ in heads) > depth


def generate_markdown_content(epub_path, stats=None):
    """
    Core function to generate markdown content from EPUB.
    stats: optional dict, filled with counts describing the conversion.
    Returns:
        tuple: (full_markdown_text: str, filename: str)
    """
    try:
        extractor = EpubExtractor(epub_path)
    except Exception as e:
        raise RuntimeError(f"Error loading EPUB: {e}")

    if stats is None:
        stats = {}
    stats.update(documents=0, empty_documents=0, failed_documents=0,
                 toc_headings_added=0, file_titles_added=0, empty_doc_titles_added=0,
                 missing_files=len(extractor.missing_files))

    metadata = extractor.get_metadata()
    title = metadata["title"]
    author = metadata["author"]

    if title == "Untitled Book":
        # Avoid multiple metadata-less EPUBs colliding on the same generic filename.
        title = os.path.splitext(os.path.basename(epub_path))[0]

    safe_title = sanitize_filename(title)
    safe_author = sanitize_filename(author)
    filename = f"{safe_title}_{safe_author}.md"

    converter = EpubConverter()

    full_markdown_content = []

    # Add Front Matter
    conversion_date = datetime.date.today().isoformat()
    full_markdown_content.append(front_matter(title, author, conversion_date))

    for doc in extractor.get_spine_documents():
        stats["documents"] += 1
        try:
            # 1. Clean (TOC anchors become headings before ids are stripped)
            cleaner = EpubCleaner(doc.content)
            stats["toc_headings_added"] += cleaner.apply_toc_headings(doc.toc_entries)
            soup = cleaner.clean()

            # 2. Convert
            md = converter.convert(soup)

            # Skip empty content, but keep the TOC titles of a page that is only
            # a picture (part/chapter title pages, covers): the title would be lost
            if not md.strip():
                stats["empty_documents"] += 1
                if not doc.toc_entries:
                    continue
                md = "\n\n".join(f"{'#' * min(max(e.depth, 1), 6)} {e.title}" for e in doc.toc_entries)
                stats["empty_doc_titles_added"] += len(doc.toc_entries)
                full_markdown_content.append(md)
                full_markdown_content.append("\n\n---\n\n")
                continue

            # 3. TOC Compensation: the document has a TOC title but its
            # Markdown doesn't start with it (title styled as <p>, or absent)
            # An entry whose #fragment doesn't exist in the HTML is treated as
            # pointing at the file (common for front matter: 版權頁, 書名頁).
            file_entry = next((e for e in doc.toc_entries if not e.fragment), None)
            if file_entry is None and doc.toc_entries and doc.toc_entries[0] in cleaner.unanchored:
                file_entry = doc.toc_entries[0]
            if file_entry and _needs_file_title(md, file_entry.title, file_entry.depth):
                level = "#" * min(file_entry.depth, 6)
                md = f"{level} {file_entry.title}\n\n{md}"
                stats["file_titles_added"] += 1

            # Append with separator
            full_markdown_content.append(md)
            full_markdown_content.append("\n\n---\n\n")

        except Exception as e:
            stats["failed_documents"] += 1
            print(f"Warning: Failed to process item {doc.href}: {e}")
            continue

    if extractor.missing_files:
        print(f"Note: {len(extractor.missing_files)} file(s) listed in the EPUB manifest are "
              f"missing from the archive (skipped), e.g. {extractor.missing_files[0]}")

    return strip_control_chars("".join(full_markdown_content)), filename


def process_epub(epub_path, output_dir, output_name=None):
    """
    Main orchestration function.
    output_name: file name to write instead of the default '{title}_{author}.md'.
    Returns True on success, False on failure.
    """
    print(f"Processing: {epub_path}")

    try:
        content, filename = generate_markdown_content(epub_path)
    except Exception as e:
        print(e)
        return False

    output_path = os.path.join(output_dir, output_name or filename)

    # Write to file
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully converted to: {output_path}")
        return True
    except Exception as e:
        print(f"Error writing output file: {e}")
        return False


def main():
    import argparse

    # Windows consoles default to cp950/cp1252; book titles must not crash printing.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Convert EPUB to Markdown for NotebookLM."
    )
    parser.add_argument("epub_path", help="Path to the input EPUB file.")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Directory to save the output Markdown file. Defaults to current directory.",
    )
    parser.add_argument(
        "-o",
        "--output-name",
        help="Output file name (e.g. 'book.md'). Defaults to '{title}_{author}.md'.",
    )

    args = parser.parse_args()

    if not os.path.exists(args.output_dir):
        try:
            os.makedirs(args.output_dir)
            print(f"Created output directory: {args.output_dir}")
        except Exception as e:
            print(f"Error creating output directory: {e}")
            sys.exit(1)

    success = process_epub(args.epub_path, args.output_dir, args.output_name)
    if not success:
        sys.exit(1)

