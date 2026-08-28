import json

from extract.structured import extract_products, products_to_markdown

# Shape copied from a real lenovo.com product page (2026-08-29): offers
# nested as a dict, availability as a full schema.org URL, and "price": 0
# used as a placeholder where the real price renders client-side.
LENOVO = {
    "@context": "http://schema.org/",
    "@type": "Product",
    "name": "ThinkPad L13 Gen 5 (13” Intel) Laptop",
    "sku": "LEN101T0091",
    "mpn": "LEN101T0091",
    "brand": {"@type": "Brand", "name": "ThinkPad"},
    "offers": {
        "@type": "Offer",
        "price": 0,
        "priceCurrency": "USD",
        "availability": "http://schema.org/InStock",
    },
}


def _wrap(payload) -> str:
    return f'<html><body><script type="application/ld+json">{json.dumps(payload)}</script></body></html>'


def test_extracts_product_with_nested_offer():
    products = extract_products(_wrap(LENOVO))
    assert len(products) == 1
    assert products[0]["name"].startswith("ThinkPad L13")
    assert products[0]["sku"] == "LEN101T0091"
    assert products[0]["brand"] == "ThinkPad"
    assert products[0]["availability"] == "InStock"


def test_placeholder_zero_price_is_reported_as_absent():
    # Real sites ship "price": 0 on pages that render the price in JS.
    # Emitting "0.00 USD" would be worse than emitting nothing.
    assert extract_products(_wrap(LENOVO))[0]["price"] == ""
    assert "USD" not in products_to_markdown(extract_products(_wrap(LENOVO)))


def test_finds_products_nested_in_graph_and_itemlist():
    payload = {
        "@graph": [
            {"@type": "BreadcrumbList", "itemListElement": []},
            {
                "@type": "ItemList",
                "itemListElement": [
                    {"@type": "Product", "name": "XPS 13", "sku": "X1"},
                    {"@type": "Product", "name": "XPS 15", "sku": "X2"},
                ],
            },
        ]
    }
    assert {p["name"] for p in extract_products(_wrap(payload))} == {"XPS 13", "XPS 15"}


def test_tolerates_raw_control_characters():
    # lenovo.com ships literal newlines inside ld+json string values, which
    # strict json.loads rejects outright - losing the whole block.
    raw = '{"@type":"Product","name":"Legion\n Pro","sku":"L1"}'
    html = f'<html><script type="application/ld+json">{raw}</script></html>'
    assert extract_products(html)[0]["sku"] == "L1"


def test_malformed_json_ld_never_raises():
    for bad in [
        "",
        "<html>no ld+json here</html>",
        '<script type="application/ld+json">{broken</script>',
        '<script type="application/ld+json">null</script>',
        '<script type="application/ld+json">[1, 2, "x"]</script>',
    ]:
        assert extract_products(bad) == []


def test_pipe_in_name_does_not_break_the_table():
    html = _wrap({"@type": "Product", "name": "XPS 13 | Plus", "sku": "X1"})
    row = products_to_markdown(extract_products(html)).splitlines()[-1]
    assert "\\|" in row  # the name's own pipe is escaped
    # 5 columns => 6 unescaped delimiters, so the row still parses as one row
    assert row.replace("\\|", "").count("|") == 6


def test_no_products_yields_no_table():
    assert products_to_markdown([]) == ""
