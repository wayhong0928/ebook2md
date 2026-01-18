from markdownify import MarkdownConverter
import re


class CustomMarkdownConverter(MarkdownConverter):
    """
    Customized MarkdownConverter to handle specific requirements:
    1. Remove internal links but keep text.
    2. Keep external links.
    3. Ensure code blocks are preserved (markdownify default usually works).
    4. Handle tables (markdownify default works).
    """

    def convert_a(self, el, text, *args, **kwargs):
        href = el.get("href")
        if not href:
            return text

        # Check if external link
        if (
            href.startswith("http://")
            or href.startswith("https://")
            or href.startswith("mailto:")
        ):
            return super().convert_a(el, text, *args, **kwargs)

        # Internal link (anchor or relative file) -> return Just Text
        return text

    # We can override convert_table etc. if needed, but default is good start.


class EpubConverter:
    def __init__(self):
        pass

    def convert(self, html_soup):
        """
        Convert BeautifulSoup object to Markdown string.
        """
        # We pass str(html_soup) because markdownify takes a string.
        # However, passing soup directly is not supported by standard markdownify,
        # it expects HTML string.
        html_string = str(html_soup)

        md = CustomMarkdownConverter(heading_style="atx").convert(html_string)

        # Post-processing
        md = self._post_process(md)
        return md

    def _post_process(self, text):
        """
        Clean up the markdown text.
        1. Compress multiple newlines to max 2.
        """
        # Compress 3 or more newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
