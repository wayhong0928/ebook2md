"""ebook2md: EPUB and text-layer PDF books to Markdown, and Markdown/EPUB
books to chapters.

    ebook2md convert BOOK...      # .epub or .pdf -> .md
    ebook2md slice BOOK           # .epub or converted .md -> chapters JSON

The output format is described in docs/output_format.md.
"""
import functools
import re
import subprocess
from pathlib import Path

__version__ = "1.7.0"


@functools.lru_cache(maxsize=None)
def converter_version() -> str:
    """'ebook2md 1.6.0 (abc1234)' in a git checkout ('+dirty' when the package
    has uncommitted changes), 'ebook2md 1.6.0' otherwise. Written into the
    head of every md so a file tells which code produced it."""
    pkg = Path(__file__).resolve().parent
    try:
        head = subprocess.run(["git", "-C", str(pkg), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        if head.returncode != 0:
            return f"ebook2md {__version__}"
        dirty = subprocess.run(["git", "-C", str(pkg), "status", "--porcelain", "--", "."],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return f"ebook2md {__version__} ({head.stdout.strip()}{'+dirty' if dirty else ''})"
    except (OSError, subprocess.SubprocessError):
        return f"ebook2md {__version__}"


# C0 controls except tab and newline, DEL, C1 controls, and a CR that is not
# part of CRLF. Books carry them in from the source: EPUB numeric entities
# such as &#142; left by a publisher's encoding conversion (an e-reader shows
# nothing there), Symbol-font bullets and tab leaders in PDF text layers, a
# stray CR inside a link. None has a reliable visible equivalent.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]|\r(?!\n)")


def strip_control_chars(text: str) -> str:
    """Drop the control characters above; tab, newline and CRLF stay."""
    return _CONTROL_CHARS.sub("", text)


def front_matter(title: str, author: str, date: str) -> str:
    """The block every converted md starts with (docs/output_format.md)."""
    return (f"# 書名：{title}\n\n# 作者：{author}\n\n# 轉換日期：{date}\n\n"
            f"# 轉換器：{converter_version()}\n\n---\n")
