import unittest
from bs4 import BeautifulSoup
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from converter import EpubConverter

class TestEpubConverter(unittest.TestCase):
    def setUp(self):
        self.converter = EpubConverter()

    def test_headings(self):
        html = "<h1>Title</h1><h2>Subtitle</h2>"
        soup = BeautifulSoup(html, 'html.parser')
        md = self.converter.convert(soup)
        self.assertIn("# Title", md)
        self.assertIn("## Subtitle", md)

    def test_links(self):
        html = '<p>Go to <a href="http://google.com">Google</a> or <a href="#chapter1">Chapter 1</a>.</p>'
        soup = BeautifulSoup(html, 'html.parser')
        md = self.converter.convert(soup)
        self.assertIn("[Google](http://google.com)", md)
        self.assertNotIn("(#chapter1)", md)
        self.assertIn("Chapter 1", md) # Text should remain

    def test_whitespace_compression(self):
        html = "<p>Para 1</p><br><br><br><p>Para 2</p>"
        # markdownify might convert br to \n.
        soup = BeautifulSoup(html, 'html.parser')
        md = self.converter.convert(soup)
        # We expect Para 1 \n\n Para 2, not \n\n\n\n
        self.assertFalse("\n\n\n" in md)

    def test_tables(self):
        html = "<table><tr><td>Cell 1</td><td>Cell 2</td></tr></table>"
        soup = BeautifulSoup(html, 'html.parser')
        md = self.converter.convert(soup)
        self.assertIn("| Cell 1 | Cell 2 |", md)
        self.assertIn("| --- | --- |", md)

    def test_code_blocks(self):
        html = '<pre><code>print("Hello World")</code></pre>'
        soup = BeautifulSoup(html, 'html.parser')
        md = self.converter.convert(soup)
        # markdownify usually converts pre>code to ``` ```
        self.assertIn('```', md)
        self.assertIn('print("Hello World")', md)


if __name__ == '__main__':
    unittest.main()
