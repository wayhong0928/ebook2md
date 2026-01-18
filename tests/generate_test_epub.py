from ebooklib import epub
import os

def create_sample_epub(filename="test_book.epub"):
    book = epub.EpubBook()

    # Set metadata
    book.set_identifier('id123456')
    book.set_title('Test Book for Extraction')
    book.set_language('en')
    book.add_author('Test Author')

    # Create chapters
    c1 = epub.EpubHtml(title='Introduction', file_name='intro.xhtml', lang='en')
    c1.content = '<h1>Introduction</h1><p>Welcome to the book.</p>'

    c2 = epub.EpubHtml(title='Chapter 2 (TOC Only)', file_name='chap02.xhtml', lang='en')
    # This chapter intentionally has NO H1 tag to test TOC fallback in later stages, 
    # but for Extractor test, we just want to verify we get the title "Chapter 2 (TOC Only)" from TOC map.
    c2.content = '<p>This chapter text has no header.</p>'

    c3 = epub.EpubHtml(title='Chapter 3', file_name='chap03.xhtml', lang='en')
    c3.content = '<h1>Chapter 3</h1><p>Content.</p>'

    # Add chapters
    book.add_item(c1)
    book.add_item(c2)
    book.add_item(c3)

    # Define Table of Contents
    book.toc = (epub.Link('intro.xhtml', 'Introduction', 'intro'),
                (epub.Section('Main Section'),
                 (epub.Link('chap02.xhtml', 'Chapter 2 (TOC Only)', 'chap02'),
                  epub.Link('chap03.xhtml', 'Chapter 3 (Nested)', 'chap03'))
                )
               )

    # Add default NCX and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define CSS style
    style = 'body { font-family: Times, serif; }'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
    book.add_item(nav_css)

    # Basic spine
    book.spine = ['nav', c1, c2, c3]

    # Write epub
    epub.write_epub(filename, book, {})
    print(f"Created {filename}")

if __name__ == '__main__':
    create_sample_epub(os.path.join(os.path.dirname(__file__), 'test_book.epub'))
