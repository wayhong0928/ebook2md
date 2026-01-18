    def test_code_blocks(self):
        html = '<pre><code>print("Hello World")</code></pre>'
        soup = BeautifulSoup(html, 'html.parser')
        md = self.converter.convert(soup)
        self.assertIn('```', md)
        self.assertIn('print("Hello World")', md)
