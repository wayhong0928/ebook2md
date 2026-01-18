import ebooklib
from ebooklib import epub
import os


class EpubExtractor:
    def __init__(self, epub_path):
        if not os.path.exists(epub_path):
            raise FileNotFoundError(f"EPUB file not found: {epub_path}")

        try:
            self.book = epub.read_epub(epub_path)
        except Exception as e:
            raise RuntimeError(f"Failed to read EPUB file: {e}")

        self.toc_map = self._build_toc_map()

    def get_metadata(self):
        """
        Extract title and author from metadata.
        Returns:
            dict: {'title': str, 'author': str}
        """
        # Get title
        titles = self.book.get_metadata("DC", "title")
        title = titles[0][0] if titles else "Untitled Book"

        # Get author (creator)
        creators = self.book.get_metadata("DC", "creator")
        author = creators[0][0] if creators else "Unknown Author"

        return {"title": title, "author": author}

    def _build_toc_map(self):
        """
        Flatten the TOC to a dictionary mapping filenames (hrefs) to titles.
        Handles nested TOC structures.
        Returns:
            dict: {href_filename: title}
        """
        toc_map = {}

        def parse_toc_item(item):
            if isinstance(item, tuple) or isinstance(item, list):
                # Section with children: (Link object, [children...])
                # or just nested lists depending on ebooklib version/structure
                if len(item) == 2:
                    link_obj, children = item
                    # Process the parent link if it's a Link object
                    if isinstance(link_obj, epub.Link):
                        update_map(link_obj)

                    # Process children
                    for child in children:
                        parse_toc_item(child)
            elif isinstance(item, epub.Link):
                update_map(item)

        def update_map(link_obj):
            # link_obj.href might be 'chap01.xhtml#start'
            # We only care about 'chap01.xhtml' to match with spine items
            href = link_obj.href.split("#")[0]
            if href not in toc_map:
                toc_map[href] = link_obj.title

        for item in self.book.toc:
            parse_toc_item(item)

        return toc_map

    def get_spine_items(self):
        """
        Yields content and TOC title for each document in the spine.
        Returns:
            Generator yielding (content: bytes, title: str|None, file_name: str)
        """
        for item_ref in self.book.spine:
            # item_ref is (item_id, 'yes'/'no') - 'yes' means linear
            item_id = item_ref[0]
            item = self.book.get_item_with_id(item_id)

            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                href = item.get_name()
                # Try to find a title from TOC
                toc_title = self.toc_map.get(href)

                yield (item.get_content(), toc_title, href)


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
            for content, title, href in extractor.get_spine_items():
                print(f"File: {href} | TOC Title: {title if title else 'None'}")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Usage: python extractor.py <path_to_epub>")
