"""A shop page's product name, price and availability from its markup.

Main-content extraction keeps a product's description and drops the price
block, so fetched shop pages lost exactly the specifics the grounding check
judges (Oct 2026: deep-research prices "not on the pages read" although the
pages' JSON-LD and itemprop tags had them). The line built here goes at the top
of the extracted text, so no length cap can cut it.
"""

import json
from typing import Any

from bs4 import BeautifulSoup

from src.agent.tools.html_soup import parsed_html

_MAX_PRODUCTS = 3
_SCHEMA_PREFIX = "https://schema.org/"
_PRICE_META = (
    ("property", "product:price:amount", "product:price:currency"),
    ("property", "og:price:amount", "og:price:currency"),
    ("itemprop", "price", "priceCurrency"),
)


def _types(node: dict[str, Any]) -> list[str]:
    value = node.get("@type")
    return [str(t) for t in value] if isinstance(value, list) else [str(value)]


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every Product object in a JSON-LD tree (top level, lists and @graph)."""
    if isinstance(node, list):
        return [p for item in node for p in _walk(item)]
    if not isinstance(node, dict):
        return []
    found = [node] if "Product" in _types(node) else []
    return found + _walk(node.get("@graph"))


def _offer_text(offers: Any) -> str:
    offer = offers[0] if isinstance(offers, list) and offers else offers
    if not isinstance(offer, dict):
        return ""
    currency = str(offer.get("priceCurrency") or "").strip()
    low, high = offer.get("lowPrice"), offer.get("highPrice")
    price = offer.get("price")
    amount = f"{low}–{high}" if low is not None and high is not None else price
    parts = [f"price {amount} {currency}".strip()] if amount is not None else []
    availability = str(offer.get("availability") or "").replace(_SCHEMA_PREFIX, "")
    if availability:
        parts.append(availability.replace("http://schema.org/", ""))
    return ", ".join(parts)


def _json_ld_products(soup: BeautifulSoup) -> list[str]:
    products: list[str] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError, TypeError:
            continue
        for product in _walk(data):
            offer = _offer_text(product.get("offers"))
            name = str(product.get("name") or "").strip()
            if offer:
                products.append(f"{name} - {offer}" if name else offer)
    return products


def _meta_price(soup: BeautifulSoup) -> str:
    for attr, amount_key, currency_key in _PRICE_META:
        amount = soup.find("meta", attrs={attr: amount_key})
        if amount and amount.get("content"):
            currency = soup.find("meta", attrs={attr: currency_key})
            unit = currency.get("content", "") if currency else ""
            return f"price {amount['content']} {unit}".strip()
    return ""


def product_data_line(html: str) -> str:
    """'Product data (page markup): <name> - price <amount> <currency>, <stock>'
    or '' when the page carries no product price."""
    try:
        with parsed_html(html) as soup:
            products = _json_ld_products(soup)[:_MAX_PRODUCTS] or [
                p for p in [_meta_price(soup)] if p
            ]
    except Exception:  # noqa: BLE001
        return ""
    if not products:
        return ""
    return "Product data (page markup): " + "; ".join(products)
