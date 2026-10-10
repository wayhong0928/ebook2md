import ebooklib
from ebooklib import epub
import os
import posixpath
from dataclasses import dataclass, field
from urllib.parse import unquote

# --- Monkey Patch: Make EpubReader lenient to missing files ---
# Many EPUBs have manifest entries (like CSS/Images) that don't exist in the zip.
# Standard ebooklib crashes on these. We patch it to return empty bytes instead,
# and record the name so the caller can report one summary line per book.
_original_read_file = epub.EpubReader.read_file
_original_parse_nav = epub.EpubReader._parse_nav
_original_parse_ncx = epub.EpubReader._parse_ncx


def _lenient_read_file(self, name):
    try:
        return _original_read_file(self, name)
    except KeyError:
        missing = getattr(self, "_missing_files", None)
        if missing is None:
            missing = self._missing_files = []
        missing.append(name)
        return b""


def _lenient_parse_nav(self, data, base_path, navtype="toc"):
    # A manifest can point at a nav document that isn't in the zip; parsing the
    # empty bytes returned above raises "Document is empty". Skip the nav and
    # keep whatever TOC the NCX gave us.
    if not data or not data.strip():
        return
    return _original_parse_nav(self, data, base_path, navtype)


def _lenient_parse_ncx(self, data):
    if not data or not data.strip():
        return
    return _original_parse_ncx(self, data)


epub.EpubReader.read_file = _lenient_read_file
epub.EpubReader._parse_nav = _lenient_parse_nav
epub.EpubReader._parse_ncx = _lenient_parse_ncx
# -----------------------------------------------------------


@dataclass
class TocEntry:
    title: str
    depth: int  # 1 = top level of the TOC
    fragment: str  # "" when the entry points at the whole file


@dataclass
class SpineDocument:
    content: bytes
    href: str
    toc_entries: list = field(default_factory=list)  # [TocEntry] in TOC order

    @property
    def file_title(self):
        """Title of the first TOC entry that points at the file itself (no fragment)."""
        for entry in self.toc_entries:
            if not entry.fragment:
                return entry.title
        return None


class EpubExtractor:
    def __init__(self, epub_path):
        if not os.path.exists(epub_path):
            raise FileNotFoundError(f"EPUB file not found: {epub_path}")

        reader = epub.EpubReader(epub_path)
        try:
            self.book = reader.load()
            reader.process()
        except Exception as e:
            raise RuntimeError(f"Failed to read EPUB file: {e}")
        self.missing_files = getattr(reader, "_missing_files", [])

        self._doc_names = [
            item.get_name()
            for item in self.book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        ]
        self.toc_entries = self._build_toc_entries()
        self.toc_map = self._build_toc_map()

    def get_metadata(self):
        """
        Extract title and author from metadata.
        Returns:
            dict: {'title': str, 'author': str}
        """
        titles = self.book.get_metadata("DC", "title")
        title = (titles[0][0] if titles else None) or "Untitled Book"

        creators = self.book.get_metadata("DC", "creator")
        author = (creators[0][0] if creators else None) or "Unknown Author"

        return {"title": title.strip(), "author": author.strip()}

    def _resolve_href(self, href):
        """
        Map a TOC href (file part only) to the name of a document in the book.
        TOC hrefs are sometimes written relative to another directory
        (e.g. '../OEBPS/Text/01.xhtml' while the item is 'Text/01.xhtml'), so
        fall back to the longest matching path suffix, then a unique basename.
        """
        href = posixpath.normpath(unquote(href)).lstrip("./")
        if href in self._doc_names:
            return href
        parts = href.split("/")
        for start in range(1, len(parts)):
            suffix = "/".join(parts[start:])
            hits = [n for n in self._doc_names if n == suffix or n.endswith("/" + suffix)]
            if len(hits) == 1:
                return hits[0]
        base = parts[-1]
        hits = [n for n in self._doc_names if posixpath.basename(n) == base]
        if len(hits) == 1:
            return hits[0]
        return href

    def _build_toc_entries(self):
        """
        Flatten the TOC (nested Links and Sections) into
        {document name: [TocEntry, ...]} keeping TOC order and depth.
        """
        entries = {}

        def add(node, depth):
            href = getattr(node, "href", None)
            title = (getattr(node, "title", None) or "").strip()
            if not href or not title:
                return
            file_part, _, fragment = href.partition("#")
            name = self._resolve_href(file_part)
            entries.setdefault(name, []).append(TocEntry(title, depth, unquote(fragment)))

        def walk(nodes, depth):
            for node in nodes:
                if isinstance(node, (tuple, list)):
                    if len(node) == 2:
                        parent, children = node
                        add(parent, depth)
                        walk(children, depth + 1)
                    else:
                        walk(node, depth)
                else:
                    add(node, depth)

        walk(self.book.toc, 1)
        return entries

    def _build_toc_map(self):
        """
        {document name: title} for the first TOC entry of each document.
        Kept for callers of the original API.
        """
        return {name: lst[0].title for name, lst in self.toc_entries.items() if lst}

    def get_spine_documents(self):
        """Yields SpineDocument for each XHTML document in reading order."""
        for item_ref in self.book.spine:
            item = self.book.get_item_with_id(item_ref[0])
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                href = item.get_name()
                yield SpineDocument(item.get_content(), href, self.toc_entries.get(href, []))

    def get_spine_items(self):
        """
        Yields content and TOC title for each document in the spine.
        Returns:
            Generator yielding (content: bytes, title: str|None, file_name: str)
        """
        for doc in self.get_spine_documents():
            yield (doc.content, self.toc_map.get(doc.href), doc.href)


if __name__ == "__main__":
    # Quick test if run directly
    import sys

    if len(sys.argv) > 1:
        path = sys.argv[1]
        try:
            extractor = EpubExtractor(path)
            meta = extractor.get_metadata()
            print(f"Book: {meta['title']} by {meta['author']}")
            print("-" * 20)
            for doc in extractor.get_spine_documents():
                titles = ", ".join(e.title for e in doc.toc_entries) or "None"
                print(f"File: {doc.href} | TOC: {titles}")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Usage: python extractor.py <path_to_epub>")
