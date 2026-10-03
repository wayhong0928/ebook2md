from bs4 import BeautifulSoup, NavigableString, UnicodeDammit
import re
import unicodedata

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
BLOCK_TAGS = HEADING_TAGS + ["p", "div", "li", "dt", "dd", "td", "th", "blockquote", "figcaption", "caption"]
CONTAINER_TAGS = ["body", "section", "article", "main", "div"]
TABLE_PARTS = ["tr", "td", "th", "thead", "tbody", "tfoot"]
# Anchors inside these get no heading: it would break a table or land in code
NO_HEADING_INSIDE = TABLE_PARTS + ["pre", "code"]


def _norm(text):
    """Normalize for title matching: NFKC, drop whitespace and punctuation."""
    text = unicodedata.normalize("NFKC", text or "")
    return "".join(ch for ch in text if ch.isalnum())


def _matches_title(block_text, title):
    b, t = _norm(block_text), _norm(title)
    if not b or not t:
        return False
    if b == t:
        return True
    # TOC title = heading + subtitle split into two paragraphs in the body
    if t.startswith(b) and len(b) >= len(t) * 0.5:
        return True
    # Body heading carries a little extra (e.g. a chapter number prefix), but
    # a sentence that merely starts with a short title is body text.
    if b.endswith(t) and len(b) - len(t) <= max(4, len(t) // 2) and not block_text.rstrip().endswith("。"):
        return True
    return False


# Text ending like this is a finished sentence; a heading may follow it.
_SENTENCE_END = "。！？!?.…」』）)\"'”’：:；;》〉】]"
_TRAILING_NOTE_MARKS = re.compile(r"[\d①-⑳\[\]\s]+$")


def _ends_sentence(text):
    text = _TRAILING_NOTE_MARKS.sub("", text.strip())  # footnote numbers like '。12'
    return not text or text[-1] in _SENTENCE_END


class EpubCleaner:
    def __init__(self, html_content):
        """
        Initialize with HTML content (bytes or str).
        """
        content_str = ""
        if isinstance(html_content, bytes):
            try:
                content_str = html_content.decode("utf-8")
            except UnicodeDecodeError:
                # Non UTF-8 documents (Big5, GB18030...) declare their charset in
                # the XML declaration or a meta tag; let UnicodeDammit use it.
                dammit = UnicodeDammit(html_content, ["utf-8", "big5", "gb18030"], is_html=True)
                content_str = dammit.unicode_markup or html_content.decode("utf-8", errors="replace")
        else:
            content_str = str(html_content)

        # Remove XML declaration pattern <?xml ... ?>
        content_str = re.sub(r"<\?xml[^>]*\?>", "", content_str, flags=re.IGNORECASE)

        self.soup = BeautifulSoup(content_str, "html.parser")
        self.unanchored = []  # TOC entries whose #fragment isn't in this document

    def apply_toc_headings(self, toc_entries):
        """
        Turn the TOC entries that point inside this document (href with a
        #fragment) into headings, before ids are stripped by clean().

        Many EPUBs style their section titles as <p>/<div> and rely on TOC
        anchors, so without this the sub-sections vanish from the Markdown.
        If the anchored text matches the TOC title it becomes h{depth};
        otherwise a new heading with the TOC title is inserted at the anchor.
        Returns the number of headings added.
        """
        added = 0
        for entry in toc_entries:
            if not entry.fragment:
                continue
            anchor = self.soup.find(id=entry.fragment) or self.soup.find(attrs={"name": entry.fragment})
            if anchor is None:
                self.unanchored.append(entry)
                continue
            if anchor.name in HEADING_TAGS or anchor.find_parent(HEADING_TAGS):
                continue
            if anchor.name in NO_HEADING_INSIDE or anchor.find_parent(NO_HEADING_INSIDE):
                continue

            level = min(max(entry.depth, 1), 6)
            first = self._first_text_block(anchor)
            if first is not None and (first.name in HEADING_TAGS or first.find_parent(HEADING_TAGS)):
                # The section already opens with a heading (possibly a split one
                # like '### 第一章' + '# 章名'); don't add another.
                continue
            block = self._title_block(anchor, entry.title)
            if block is not None:
                block.name = f"h{level}"
                block.attrs.pop("class", None)
            else:
                if self._has_text_before(anchor) or not self._previous_text_ends_sentence(anchor):
                    # Anchor sits mid-paragraph, or the text before it stops
                    # mid-sentence (hard-wrapped <p> per line, anchor on a page
                    # image): a heading here would cut a sentence in two.
                    continue
                heading = self.soup.new_tag(f"h{level}")
                heading.string = entry.title
                anchor.insert_before(heading)
            added += 1
        return added

    def _title_block(self, anchor, title):
        """Find the block holding the title text at or right after the anchor."""
        text = anchor.get_text(strip=True)
        if text and _matches_title(text, title):
            # A heading-sized element (not a whole chapter container). An inline
            # anchor counts only if its whole block is the title, otherwise
            # converting the block would swallow body text into the heading.
            block = self._block_of(anchor)
            if block is not None and _matches_title(block.get_text(strip=True), title):
                return block
            return None
        if text and anchor.name in CONTAINER_TAGS:
            # <section id=...> wrapping the chapter: look at its first block
            first = self._first_leaf_block(anchor)
            if first is not None and _matches_title(first.get_text(strip=True), title):
                return first
            return None
        if not text:
            # Empty <a id="p17"/> page/anchor marker: the title follows it
            nxt = next((s for s in anchor.find_all_next(string=True) if s.strip()), None)
            if nxt is not None:
                block = self._block_of(nxt)
                if block is not None and _matches_title(block.get_text(strip=True), title):
                    return block
        return None

    def _first_text_block(self, anchor):
        """The first block with text at or after the anchor."""
        if anchor.get_text(strip=True):
            if anchor.name in CONTAINER_TAGS:
                inner = self._first_leaf_block(anchor)
                if inner is not None:
                    return inner
            return self._block_of(anchor) or anchor
        nxt = next((s for s in anchor.find_all_next(string=True) if s.strip()), None)
        return self._block_of(nxt) if nxt is not None else None

    @staticmethod
    def _first_leaf_block(container):
        """First block with text that has no text-bearing block inside it
        (skips wrapper <div>s around the actual title paragraph)."""
        for b in container.find_all(BLOCK_TAGS):
            if not b.get_text(strip=True):
                continue
            if not any(inner.get_text(strip=True) for inner in b.find_all(BLOCK_TAGS)):
                return b
        return None

    @staticmethod
    def _has_text_before(anchor):
        """True if text precedes the anchor in the same run of inline content
        (same paragraph, or bare text directly inside <body>/<section>)."""
        if anchor.name in BLOCK_TAGS:
            return False
        node = anchor
        while node.parent is not None and node.name not in BLOCK_TAGS and node.name not in CONTAINER_TAGS:
            for sib in node.previous_siblings:
                if isinstance(sib, NavigableString):
                    if sib.strip():
                        return True
                elif sib.name in BLOCK_TAGS or sib.name in CONTAINER_TAGS or sib.name == "br":
                    break
                elif sib.get_text(strip=True):
                    return True
            node = node.parent
        return False

    @staticmethod
    def _previous_text_ends_sentence(anchor):
        """True if the last text before the anchor in <body> ends a sentence
        (or there is none, or it is a heading)."""
        for s in anchor.find_all_previous(string=True):
            # Skip doctype/comments and anything outside <body>
            if type(s) is not NavigableString or not s.strip():
                continue
            parent = s.parent
            if parent is None or parent.name in ("script", "style", "title", "[document]") or s.find_parent("head"):
                continue
            if parent.name in HEADING_TAGS or s.find_parent(HEADING_TAGS):
                return True
            return _ends_sentence(s)
        return True

    @staticmethod
    def _block_of(node):
        if getattr(node, "name", None) in BLOCK_TAGS:
            return node
        return node.find_parent(BLOCK_TAGS)

    def clean(self):
        """
        Execute the cleaning pipeline.
        Returns:
            BeautifulSoup object of the cleaned HTML.
        """
        self._remove_noise_tags()
        self._remove_structural_noise()
        self._process_images()
        self._clean_attributes()
        return self.soup

    def get_html_string(self):
        return str(self.soup)

    def _remove_noise_tags(self):
        """Remove technical noise tags."""
        for tag_name in [
            "script",
            "style",
            "meta",
            "link",
            "noscript",
            "iframe",
            "svg",
        ]:
            for tag in self.soup.find_all(tag_name):
                tag.decompose()

    def _remove_structural_noise(self):
        """
        Remove navigation and page furniture.
        <aside> is kept: in EPUBs it holds footnotes (epub:type="footnote")
        and sidebars, which are book content.
        """
        for tag_name in ["nav", "footer", "header"]:
            for tag in self.soup.find_all(tag_name):
                tag.decompose()

        for tag in self.soup.find_all(
            attrs={"role": ["navigation", "banner", "contentinfo"]}
        ):
            tag.decompose()

        for tag in self.soup.find_all("aside"):
            tag.name = "div"

    def _process_images(self):
        """
        Convert <img> tags to text representations.
        Format: [圖片說明: Alt Text] or [圖片]
        """
        for img in self.soup.find_all("img"):
            alt_text = img.get("alt", "").strip()

            if not alt_text and img.find_parent(HEADING_TAGS):
                # Decorative icon inside a title: "## [圖片] 第一章" is noise
                img.decompose()
                continue

            if alt_text:
                replacement_text = f" [圖片說明: {alt_text}] "
            else:
                replacement_text = " [圖片] "

            img.replace_with(NavigableString(replacement_text))

    def _clean_attributes(self):
        """
        Remove inline styles and other non-semantic attributes.
        Keep 'colspan', 'rowspan' for tables and 'href' for external links.
        """
        for tag in self.soup.find_all(True):
            # 1. Remove style, width, height (Pure visual noise)
            for attr in ["style", "width", "height", "cellspacing", "cellpadding", "border"]:
                if attr in tag.attrs:
                    del tag.attrs[attr]

            # 2. Remove 'class' except for code blocks (preserve syntax highlighting hints)
            if "class" in tag.attrs and tag.name not in ["code", "pre"]:
                del tag.attrs["class"]

            # 3. Remove 'id' (internal anchors are not kept in the Markdown)
            if "id" in tag.attrs:
                del tag.attrs["id"]

            # 4. Remove event handlers (security)
            for key in [key for key in tag.attrs if key.startswith("on")]:
                del tag.attrs[key]
