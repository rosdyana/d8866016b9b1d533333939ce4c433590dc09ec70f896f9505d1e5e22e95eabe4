"""trafilatura prunes a product page down to its promo banners.

Real numbers behind the fallback (HP ZBook PDP, 2026-08-29): visible text
6,677 chars carrying the full spec sheet; trafilatura kept 503 (8%) with
zero spec terms. A genuine article page keeps ~97%.
"""

from extract.llm_text import to_llm_text

ARTICLE = (
    "<html><body><article>"
    + "<p>This is a long paragraph of genuine article prose about laptops. </p>" * 25
    + "</article></body></html>"
)

# Shaped like a PDP: a little prose trafilatura will latch onto, and a much
# larger spec block it treats as boilerplate.
SPEC_ROWS = "".join(
    f"<li><span>Spec {i}</span><span>AMD Ryzen 7 8845HS, 32 GB DDR5, 1 TB NVMe SSD</span></li>"
    for i in range(40)
)
PRODUCT_PAGE = (
    "<html><body>"
    "<div class='promo'><p>Labor Day Sale. 3% back in rewards.</p></div>"
    f"<ul class='config'>{SPEC_ROWS}</ul>"
    "</body></html>"
)


def test_article_extraction_is_unchanged():
    out = to_llm_text(ARTICLE) or ""
    assert "genuine article prose" in out
    # Must not fall back: trafilatura is the better answer on a real article.
    assert "Labor Day" not in out


def test_product_page_keeps_the_specs():
    out = to_llm_text(PRODUCT_PAGE) or ""
    assert "Ryzen" in out, "spec content was pruned away"
    assert "DDR5" in out
    assert "NVMe" in out


def test_empty_html_does_not_raise():
    assert to_llm_text("") in (None, "")
    assert to_llm_text("<html><body></body></html>") in (None, "")


def test_the_guard_fires_when_the_pruner_keeps_almost_nothing(monkeypatch):
    """The point of this module, tested directly rather than via the pruner.

    The other tests here pass whenever the *current* pruner happens to be
    permissive enough, which makes them a test of crawl4ai, not of the
    fallback. This one forces the failure the fallback exists for: a pruner
    that returns a plausible-looking snippet holding ~4% of the page.
    """
    import extract.llm_text as module

    monkeypatch.setattr(
        module,
        "render_pruned_markdown",
        lambda cleaned, url=None: ("Labor Day Sale. 3% back in rewards.",
                                   "<div>Labor Day Sale. 3% back in rewards.</div>"),
    )

    out = module.to_llm_text(PRODUCT_PAGE) or ""
    assert "Ryzen" in out, "the guard did not fall back to the visible text"
    assert out != "Labor Day Sale. 3% back in rewards."


def test_a_generous_pruner_result_is_kept_as_is(monkeypatch):
    import extract.llm_text as module

    full = module._visible_text(PRODUCT_PAGE)
    monkeypatch.setattr(
        module,
        "render_pruned_markdown",
        lambda cleaned, url=None: ("PRUNED MARKDOWN", f"<div>{full}</div>"),
    )

    assert module.to_llm_text(PRODUCT_PAGE) == "PRUNED MARKDOWN"
