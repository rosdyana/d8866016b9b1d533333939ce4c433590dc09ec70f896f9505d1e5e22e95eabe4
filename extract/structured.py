"""Pulls schema.org Product data out of <script type="application/ld+json">.

trafilatura extracts prose, and `clean_html()` strips <script> entirely, so
on a product catalogue the fields that actually matter - sku, price,
currency, availability - are dropped by both. This module recovers them and
`normalize.py` prepends them to the text formats.

Nothing here may raise: a malformed ld+json block on one page must never
fail a scrape job, so every parse is best-effort and yields no rows.
"""

from __future__ import annotations

import json
import re
from typing import Any

_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

_MAX_ROWS = 200


def _iter_nodes(node: Any):
    """schema.org payloads nest freely - a list of graphs, an @graph key, an
    ItemList wrapping products. Walk all of it rather than assuming a shape.
    """
    if isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    for key in ("@graph", "itemListElement", "item", "mainEntity", "hasVariant"):
        if key in node:
            yield from _iter_nodes(node[key])


def _is_product(node: dict) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return any(t in ("Product", "ProductModel") for t in node_type if isinstance(t, str))
    return node_type in ("Product", "ProductModel")


def _shorten(value: Any) -> str:
    """schema.org enums arrive as full URLs (http://schema.org/InStock)."""
    if not isinstance(value, str):
        return ""
    return value.rsplit("/", 1)[-1] if "schema.org" in value else value


def _first_offer(node: dict) -> dict:
    offers = node.get("offers")
    for candidate in _iter_nodes(offers):
        if isinstance(candidate, dict) and (
            "price" in candidate or "lowPrice" in candidate or "availability" in candidate
        ):
            return candidate
    return {}


def _price(offer: dict) -> str:
    for key in ("price", "lowPrice"):
        raw = offer.get(key)
        if isinstance(raw, dict):
            raw = raw.get("@value")
        if raw in (None, "", 0, "0", "0.0", "0.00"):
            # Lenovo emits "price": 0 as a placeholder on pages where the
            # real price is rendered client-side - reporting 0 would be
            # worse than reporting nothing.
            continue
        return str(raw).strip()
    return ""


def _brand(node: dict) -> str:
    brand = node.get("brand")
    if isinstance(brand, dict):
        return str(brand.get("name") or "").strip()
    if isinstance(brand, list) and brand:
        return _brand({"brand": brand[0]})
    return str(brand or "").strip()


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def extract_products(html: str) -> list[dict[str, str]]:
    products: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for raw in _LD_JSON_RE.findall(html or ""):
        try:
            # strict=False tolerates the raw control characters real sites
            # ship inside ld+json strings (observed on lenovo.com).
            payload = json.loads(raw.strip(), strict=False)
        except (ValueError, TypeError):
            continue

        for node in _iter_nodes(payload):
            if not _is_product(node):
                continue
            name = str(node.get("name") or "").strip()
            if not name:
                continue
            offer = _first_offer(node)
            row = {
                "name": name,
                "sku": str(node.get("sku") or node.get("mpn") or "").strip(),
                "brand": _brand(node),
                "price": _price(offer),
                "currency": str(offer.get("priceCurrency") or "").strip(),
                "availability": _shorten(offer.get("availability")),
            }
            key = (row["name"], row["sku"])
            if key in seen:
                continue
            seen.add(key)
            products.append(row)
            if len(products) >= _MAX_ROWS:
                return products

    return products


def products_to_markdown(products: list[dict[str, str]]) -> str:
    if not products:
        return ""
    lines = [
        "## Products",
        "",
        "| name | brand | sku | price | availability |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in products:
        # Currency without a number reads as data where there is none.
        price = f"{p['price']} {p['currency']}".strip() if p["price"] else ""
        lines.append(
            f"| {_cell(p['name'])} | {_cell(p['brand'])} | {_cell(p['sku'])} "
            f"| {_cell(price)} | {_cell(p['availability'])} |"
        )
    return "\n".join(lines)
