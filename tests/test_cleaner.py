import unittest
from bs4 import BeautifulSoup
import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from cleaner import EpubCleaner

class TestEpubCleaner(unittest.TestCase):
    def test_remove_noise_tags(self):
        html = "<div><p>Content</p><script>console.log('bad');</script><style>body{color:red;}</style></div>"
        cleaner = EpubCleaner(html)
        soup = cleaner.clean()
        self.assertIsNone(soup.script)
        self.assertIsNone(soup.style)
        self.assertEqual(soup.find('p').text, "Content")

    def test_remove_structural_noise(self):
        html = "<body><header>Head</header><nav>Menu</nav><p>Real Content</p><footer>Foot</footer></body>"
        cleaner = EpubCleaner(html)
        soup = cleaner.clean()
        self.assertIsNone(soup.nav)
        self.assertIsNone(soup.header)
        self.assertIsNone(soup.footer)
        self.assertEqual(soup.find('p').text, "Real Content")

    def test_process_images(self):
        html = '<p>Text <img src="pic.jpg" alt="A nice sunset"> end.</p>'
        cleaner = EpubCleaner(html)
        soup = cleaner.clean()
        self.assertIsNone(soup.img)
        self.assertIn("[圖片說明: A nice sunset]", str(soup))
        
        html2 = '<p><img src="pic2.jpg"></p>'
        cleaner2 = EpubCleaner(html2)
        soup2 = cleaner2.clean()
        self.assertIn("[圖片]", str(soup2))

    def test_clean_attributes(self):
        html = '<p style="color: red;" onclick="alert()">Text</p>'
        cleaner = EpubCleaner(html)
        soup = cleaner.clean()
        p_tag = soup.find('p')
        self.assertNotIn('style', p_tag.attrs)
        self.assertNotIn('onclick', p_tag.attrs)
        self.assertEqual(p_tag.text, "Text")

if __name__ == '__main__':
    unittest.main()
