from pipeline.browser.lazyload import has_unresolved_lazy_content


def test_detects_empty_comp_lazyload_placeholder():
    html = (
        '<div class="comp_lazyload" tag="ofp-fe-techSpecs" '
        'file="_cms_lazyload_include_/abc/def/"></div>'
    )
    assert has_unresolved_lazy_content(html) is True


def test_resolved_placeholder_with_injected_content_is_not_flagged():
    html = (
        '<div class="comp_lazyload" tag="ofp-fe-techSpecs" '
        'file="_cms_lazyload_include_/abc/def/">'
        "<section><h2>Tech Specs</h2><p>16GB RAM</p></section>"
        "</div>"
    )
    assert has_unresolved_lazy_content(html) is False


def test_attribute_order_does_not_matter():
    html = '<div tag="fragment" file="_cms_lazyload_include_/abc/" class="comp_lazyload"></div>'
    assert has_unresolved_lazy_content(html) is True


def test_page_with_no_lazyload_markup_is_unaffected():
    html = "<html><body><main><h1>Product</h1><p>Great laptop.</p></main></body></html>"
    assert has_unresolved_lazy_content(html) is False
