import os
import re
import datetime
from extractor import EpubExtractor
from cleaner import EpubCleaner
from converter import EpubConverter


def sanitize_filename(name):
    """
    Sanitize the string to be safe for filenames.
    """
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()


def generate_markdown_content(epub_path):
    """
    Core function to generate markdown content from EPUB.
    Returns:
        tuple: (full_markdown_text: str, filename: str)
    """
    try:
        extractor = EpubExtractor(epub_path)
    except Exception as e:
        raise RuntimeError(f"Error loading EPUB: {e}")

    metadata = extractor.get_metadata()
    title = metadata["title"]
    author = metadata["author"]

    # Sanitize output filename
    # Need to import sanitize_filename or move it inside or outside
    # It is defined above in this file.
    safe_title = sanitize_filename(title)
    safe_author = sanitize_filename(author)
    filename = f"{safe_title}_{safe_author}.md"

    converter = EpubConverter()

    full_markdown_content = []

    # Add Front Matter
    conversion_date = datetime.date.today().isoformat()
    front_matter = f"""# 書名：{title}

# 作者：{author}

# 轉換日期：{conversion_date}

---
"""
    full_markdown_content.append(front_matter)

    # Iterate items
    for content, toc_title, href in extractor.get_spine_items():
        try:
            # 1. Clean
            cleaner = EpubCleaner(content)
            soup = cleaner.clean()

            # 2. Convert
            md = converter.convert(soup)

            # Skip empty content
            if not md.strip():
                continue

            # 3. TOC Compensation
            # Check if MD starts with a header (#)
            if not re.match(r"^#+\s+", md):
                if toc_title:
                    # Inject Title
                    md = f"# {toc_title}\n\n{md}"

            # Append with separator
            full_markdown_content.append(md)
            full_markdown_content.append("\n\n---\n\n")

        except Exception as e:
            print(f"Warning: Failed to process item {href}: {e}")
            continue

    return "".join(full_markdown_content), filename


def process_epub(epub_path, output_dir):
    """
    Main orchestration function.
    """
    print(f"Processing: {epub_path}")

    try:
        content, filename = generate_markdown_content(epub_path)
    except Exception as e:
        print(e)
        return

    output_path = os.path.join(output_dir, filename)

    # Write to file
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully converted to: {output_path}")
    except Exception as e:
        print(f"Error writing output file: {e}")


def main():
    import argparse

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

    args = parser.parse_args()

    if not os.path.exists(args.output_dir):
        try:
            os.makedirs(args.output_dir)
            print(f"Created output directory: {args.output_dir}")
        except Exception as e:
            print(f"Error creating output directory: {e}")
            return

    process_epub(args.epub_path, args.output_dir)


if __name__ == "__main__":
    main()
