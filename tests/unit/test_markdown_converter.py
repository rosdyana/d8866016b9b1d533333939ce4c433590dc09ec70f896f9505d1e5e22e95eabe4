"""The Markdown side of the crawl4ai converter.

`test_llm_text_fallback.py` pins the pruned format against the OEM-product
failure mode. This pins the unpruned one, which had no test at all: the
whole page must survive, spec table included, and script/style must not.
"""

from extract.markdown import to_markdown

ARTICLE = (
    "<html><body><article>"
    + "<p>This is a long paragraph of genuine article prose about laptops. </p>" * 25
    + "</article></body></html>"
)

SPEC_ROWS = "".join(
    f"<li><span>Spec {i}</span><span>AMD Ryzen 7 8845HS, 32 GB DDR5, 1 TB NVMe SSD</span></li>"
    for i in range(40)
)
PRODUCT_PAGE = (
    "<html><body>"
    "<script>var telemetry = {captcha: 'https://www.recaptcha.net/x'};</script>"
    "<div class='promo'><p>Labor Day Sale. 3% back in rewards.</p></div>"
    f"<ul class='config'>{SPEC_ROWS}</ul>"
    "</body></html>"
)


def test_article_prose_survives():
    assert "genuine article prose" in (to_markdown(ARTICLE) or "")


def test_product_page_keeps_the_specs():
    out = to_markdown(PRODUCT_PAGE) or ""
    assert "Ryzen" in out
    assert "DDR5" in out
    assert "NVMe" in out


def test_script_contents_are_not_rendered_as_text():
    # Same trap `pipeline/quality.py` documents: lenovo.com inlines
    # RECAPTCHA:"https://www.recaptcha.net/..." as a JS config path, and it
    # must not end up in the prose output.
    assert "recaptcha" not in (to_markdown(PRODUCT_PAGE) or "").lower()


def test_empty_html_does_not_raise():
    assert to_markdown("") is None
    assert to_markdown("<html><body></body></html>") in (None, "")


def test_url_is_used_as_the_link_base():
    html = '<html><body><p>see <a href="/deals">deals</a> now</p></body></html>'
    out = to_markdown(html, url="https://example.com/shop") or ""
    assert "https://example.com/deals" in out
