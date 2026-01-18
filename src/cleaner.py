from bs4 import BeautifulSoup
import re


class EpubCleaner:
    def __init__(self, html_content):
        """
        Initialize with HTML content (bytes or str).
        """
        content_str = ""
        if isinstance(html_content, bytes):
            # Try decoding utf-8, usually EPUB is utf-8
            try:
                content_str = html_content.decode("utf-8")
            except UnicodeDecodeError:
                # Fallback
                content_str = html_content.decode("latin-1", errors="ignore")
        else:
            content_str = str(html_content)

        # Remove XML declaration pattern <?xml ... ?>
        content_str = re.sub(r"<\?xml[^>]*\?>", "", content_str, flags=re.IGNORECASE)

        self.soup = BeautifulSoup(content_str, "html.parser")

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
        """Remove navigation and footer elements."""
        for tag_name in ["nav", "footer", "header", "aside"]:
            for tag in self.soup.find_all(tag_name):
                tag.decompose()

        # Also remove elements with specific roles or classes that imply noise
        # This is a heuristic and can be adjusted
        for tag in self.soup.find_all(
            attrs={"role": ["navigation", "banner", "contentinfo"]}
        ):
            tag.decompose()

    def _process_images(self):
        """
        Convert <img> tags to text representations.
        Format: [圖片說明: Alt Text] or [圖片]
        """
        for img in self.soup.find_all("img"):
            alt_text = img.get("alt", "").strip()

            if alt_text:
                replacement_text = f" [圖片說明: {alt_text}] "
            else:
                replacement_text = " [圖片] "

            img.replace_with(replacement_text)

    def _clean_attributes(self):
        """
        Remove inline styles and other non-semantic attributes.
        Keep 'colspan', 'rowspan' for tables.
        Keep 'id' tentatively (might be useful later, or remove if strictly following spec).
        """
        allowed_attributes = [
            "colspan",
            "rowspan",
            "href",
            "src",
        ]  # src is for iframes/audio/video if we kept them, but img src is gone.
        # href is needed for links (external).

        for tag in self.soup.find_all(True):
            # 1. Remove style, width, height (Pure visual noise)
            for attr in ["style", "width", "height", "cellspacing", "cellpadding", "border"]:
                if attr in tag.attrs:
                    del tag.attrs[attr]

            # 2. Remove 'class' except for code blocks (preserve syntax highlighting hints)
            if "class" in tag.attrs:
                # If it's not a code block, strip classes to reduce noise
                if tag.name not in ["code", "pre"]:
                    del tag.attrs["class"]

            # 3. Remove 'id' (We don't support internal anchors in final MD to output cleaner context)
            if "id" in tag.attrs:
                del tag.attrs["id"]

            # 4. Remove event handlers (security)
            attrs_to_remove = [key for key in tag.attrs if key.startswith("on")]
            for key in attrs_to_remove:
                del tag.attrs[key]

            # 5. Filter remaining attributes to whitelist
            # keys = list(tag.attrs.keys())
            # for key in keys:
            #     if key not in allowed_attributes and key != "class":
            #         del tag.attrs[key] 
            # (Commented out: strict whitelisting might be too aggressive for now, 
            # let's stick to blacklisting common noise)
