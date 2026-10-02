import pytest

from extract.normalize import build_from_html, extract_title


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (
            '<head><title>Review | Stuff</title><meta property="og:title" content="Asus ExpertBook Ultra review"></head>',
            "Asus ExpertBook Ultra review",
        ),
        # Attribute order varies between sites.
        ('<meta content="Reversed order" property="og:title">', "Reversed order"),
        ("<title>\n  Fallback &amp; title \n</title>", "Fallback & title"),
        ('<meta property="og:title" content=""><title>Empty og falls back</title>', "Empty og falls back"),
        ("<html><body>no title</body></html>", None),
        ("", None),
    ],
)
def test_extract_title(html, expected):
    assert extract_title(html) == expected


def test_title_is_set_whatever_formats_were_asked_for():
    html = "<html><head><title>A page</title></head><body>" + "<p>text</p>" * 50 + "</body></html>"
    assert build_from_html(html, "https://example.com/", ("raw_html",)).title == "A page"
