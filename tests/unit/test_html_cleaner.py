from extract.html_cleaner import clean_html


def test_strips_script_and_style_tags():
    html = (
        "<html><head><style>body{color:red}</style></head>"
        "<body><p>Hello</p><script>alert('x')</script></body></html>"
    )
    cleaned = clean_html(html)
    assert "<script" not in cleaned
    assert "<style" not in cleaned
    assert "<p>Hello</p>" in cleaned


def test_preserves_regular_markup():
    html = "<div class=\"a\"><span>text</span></div>"
    cleaned = clean_html(html)
    assert "<span>text</span>" in cleaned
