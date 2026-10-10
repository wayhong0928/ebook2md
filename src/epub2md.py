"""Old entry point, kept for v1.6 only: use `python -m ebook2md convert` instead.

    python src/epub2md.py BOOK.epub [OUTPUT_DIR] [-o NAME.md]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook2md.epub.epub2md import main  # noqa: E402

if __name__ == "__main__":
    print("src/epub2md.py is deprecated and will be removed after v1.6; "
          "use: python -m ebook2md convert BOOK.epub -o OUTPUT_DIR [--name NAME.md]", file=sys.stderr)
    main()
