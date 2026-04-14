"""
eBay product search scraper.

Primary:  ScraperAPI structured endpoint (fast, reliable, parsed JSON)
Fallback: Playwright + BeautifulSoup (no API key needed, but fragile)
"""

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

ITEMS_PER_PAGE = 60
MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# ScraperAPI (primary)
# ---------------------------------------------------------------------------

def _parse_scraperapi_result(item: dict) -> dict | None:
    """Convert a ScraperAPI eBay structured result to our canonical format."""
    title = item.get("product_title", "")
    if not title:
        return None

    # Price
    price = None
    currency = "USD"
    item_price = item.get("item_price", {})
    if isinstance(item_price, dict):
        val = item_price.get("value") or item_price.get("from")
        cur = item_price.get("currency", "USD")
        if val is not None:
            try:
                price = float(str(val).replace(",", ""))
                currency = cur
            except (ValueError, TypeError):
                pass

    url = item.get("product_url", "")
    image_url = item.get("image", "")
    condition = item.get("condition", "")
    shipping = item.get("shipping_cost", "")
    if item.get("free_returns"):
        shipping = shipping or "Free returns"

    # Seller info
    seller_parts = []
    if item.get("seller_name"):
        seller_parts.append(item["seller_name"])
    if item.get("seller_rating"):
        seller_parts.append(f"{item['seller_rating']}% positive")
    if item.get("seller_rating_count"):
        seller_parts.append(f"({item['seller_rating_count']})")
    seller = " ".join(seller_parts)

    # Listing type from extra_info
    listing_type = "Buy It Now"
    extra = item.get("extra_info", "").lower()
    if "auction" in extra or "bid" in extra:
        listing_type = "Auction"
    elif "best offer" in extra:
        listing_type = "Buy It Now or Best Offer"
    elif "buy it now" in extra:
        listing_type = "Buy It Now"

    return {
        "title": title,
        "price": price,
        "currency": currency,
        "url": url,
        "image_url": image_url,
        "condition": condition,
        "seller": seller,
        "shipping": shipping,
        "location": "",
        "listing_type": listing_type,
    }


def _search_scraperapi(
    query: str,
    max_results: int = 50,
    condition: str = None,
    min_price: float = None,
    max_price: float = None,
) -> list[dict] | None:
    """Search eBay via ScraperAPI structured endpoint. Returns None on failure."""
    results = []
    page = 1
    items_per = min(60, max_results) if max_results <= 60 else 60
    max_pages = max(1, (max_results // items_per) + 1)

    # Map our condition values to ScraperAPI values
    condition_map = {
        "new": "new",
        "used": "used",
        "open box": "open_box",
        "refurbished": "refurbished",
        "for parts": "not_working",
    }

    while len(results) < max_results and page <= max_pages:
        params = {
            "api_key": SCRAPER_API_KEY,
            "query": query,
            "page": str(page),
            "items_per_page": str(items_per),
        }
        if condition:
            mapped = condition_map.get(condition.lower().strip())
            if mapped:
                params["condition"] = mapped

        try:
            logger.info("ScraperAPI eBay page %d: %s", page, query)
            resp = requests.get(
                "https://api.scraperapi.com/structured/ebay/search/v2",
                params=params,
                timeout=70,
            )

            if resp.status_code != 200:
                logger.warning("ScraperAPI returned %d", resp.status_code)
                return None

            data = resp.json()
        except Exception as e:
            logger.warning("ScraperAPI request failed: %s", e)
            return None

        items = data.get("results", [])
        if not items:
            break

        for item in items:
            if len(results) >= max_results:
                break

            parsed = _parse_scraperapi_result(item)
            if not parsed:
                continue

            # Price filters
            if parsed["price"] is not None:
                if min_price is not None and parsed["price"] < min_price:
                    continue
                if max_price is not None and parsed["price"] > max_price:
                    continue

            results.append(parsed)

        page += 1

    return results[:max_results]


# ---------------------------------------------------------------------------
# Playwright fallback
# ---------------------------------------------------------------------------

def _parse_price(price_text: str) -> tuple[float | None, str]:
    if not price_text:
        return None, "USD"
    price_text = price_text.strip()
    currency = "USD"
    if price_text.startswith("C $") or "CAD" in price_text:
        currency = "CAD"
    elif price_text.startswith("GBP") or price_text.startswith("\u00a3"):
        currency = "GBP"
    elif price_text.startswith("EUR") or price_text.startswith("\u20ac"):
        currency = "EUR"
    match = re.search(r"[\d,]+\.?\d*", price_text)
    if match:
        try:
            return float(match.group().replace(",", "")), currency
        except ValueError:
            return None, currency
    return None, currency


def _parse_items_playwright(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for item in soup.select("li.s-card"):
        try:
            title_el = item.select_one(".s-card__title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            title = re.sub(r"Opens in a new window or tab$", "", title).strip()
            if title.lower() in ("shop on ebay", "results matching fewer words", ""):
                continue
            if title.startswith("New Listing"):
                title = title[len("New Listing"):].strip()

            link_el = item.select_one("a.s-card__link") or item.select_one("a[href*='/itm/']")
            url = link_el["href"] if link_el else ""
            if "?" in url:
                url = url.split("?")[0]

            img_el = item.select_one("img")
            image_url = (img_el.get("src", "") or img_el.get("data-src", "")) if img_el else ""

            price_el = item.select_one(".s-card__price")
            price_text = price_el.get_text(strip=True) if price_el else ""
            if " to " in price_text:
                price_text = price_text.split(" to ")[0]
            price, currency = _parse_price(price_text)
            if price is None:
                continue

            cond_el = item.select_one(".s-card__subtitle")
            condition_text = cond_el.get_text(strip=True) if cond_el else ""

            shipping = ""
            location = ""
            listing_type = "Buy It Now"
            seller = ""
            for row in item.select(".s-card__attribute-row"):
                row_text = row.get_text(strip=True)
                row_lower = row_text.lower()
                if "shipping" in row_lower or (
                    "free" in row_lower and "deliver" in row_lower
                ) or row_lower.startswith("+$") or row_lower.startswith("free"):
                    if not shipping:
                        shipping = row_text
                elif "located in" in row_lower or "from " in row_lower:
                    location = row_text
                    if location.lower().startswith("located in "):
                        location = location[len("located in "):]
                elif "buy it now" in row_lower:
                    listing_type = "Buy It Now"
                elif "auction" in row_lower or "bid" in row_lower:
                    listing_type = "Auction"
                elif "best offer" in row_lower:
                    listing_type = "Buy It Now or Best Offer"
                elif "positive" in row_lower:
                    seller = row_text

            results.append({
                "title": title, "price": price, "currency": currency,
                "url": url, "image_url": image_url, "condition": condition_text,
                "seller": seller, "shipping": shipping, "location": location,
                "listing_type": listing_type,
            })
        except Exception:
            continue
    return results


async def _search_playwright(
    query: str,
    max_results: int = 50,
    condition: str = None,
    min_price: float = None,
    max_price: float = None,
) -> list[dict]:
    """Fallback: Playwright + BeautifulSoup scraper."""
    all_results: list[dict] = []
    pages_needed = max(1, (max_results + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    condition_map = {
        "new": "1000", "open box": "1500",
        "refurbished": "2000|2010|2020|2030|2500",
        "used": "3000", "for parts": "7000",
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        page = await context.new_page()

        for page_num in range(1, pages_needed + 1):
            params = {"_nkw": query, "_ipg": str(ITEMS_PER_PAGE)}
            if page_num > 1:
                params["_pgn"] = str(page_num)
            if condition:
                cond_key = condition.lower().strip()
                if cond_key in condition_map:
                    params["LH_ItemCondition"] = condition_map[cond_key]
            if min_price is not None:
                params["_udlo"] = str(min_price)
            if max_price is not None:
                params["_udhi"] = str(max_price)

            url = "https://www.ebay.com/sch/i.html?" + urlencode(params)
            success = False

            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = await page.goto(url, wait_until="networkidle", timeout=30000)
                    if resp and resp.status == 200:
                        try:
                            await page.wait_for_selector("li.s-card", timeout=10000)
                        except Exception:
                            pass
                        html = await page.content()
                        items = _parse_items_playwright(html)
                        if items:
                            all_results.extend(items)
                            success = True
                            break
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(random.uniform(2, 4))
                except Exception:
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(random.uniform(2, 4))

            if not success:
                break
            if len(all_results) >= max_results:
                break
            if page_num < pages_needed:
                await asyncio.sleep(random.uniform(1, 3))

        await browser.close()

    return all_results[:max_results]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_ebay(
    query: str,
    max_results: int = 50,
    condition: str = None,
    min_price: float = None,
    max_price: float = None,
) -> list[dict]:
    """
    Search eBay for products matching the query.

    Tries ScraperAPI first (structured JSON, reliable).
    Falls back to Playwright scraping if ScraperAPI fails.

    Returns list of dicts: title, price, currency, url, image_url,
    condition, seller, shipping, location, listing_type.
    """
    # Try ScraperAPI first
    try:
        results = await asyncio.to_thread(
            _search_scraperapi, query, max_results, condition, min_price, max_price
        )
        if results is not None and len(results) > 0:
            logger.info("ScraperAPI returned %d eBay results", len(results))
            return results
        logger.warning("ScraperAPI returned no results, falling back to Playwright")
    except Exception as e:
        logger.warning("ScraperAPI failed (%s), falling back to Playwright", e)

    # Fallback to Playwright
    return await _search_playwright(query, max_results, condition, min_price, max_price)


async def _main():
    parser = argparse.ArgumentParser(description="Search eBay for products")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--max-results", type=int, default=50, help="Max results to return")
    parser.add_argument("--condition", type=str, default=None,
                        help="Condition filter: New, Used, Refurbished, 'Open Box', 'For Parts'")
    parser.add_argument("--min-price", type=float, default=None, help="Minimum price (USD)")
    parser.add_argument("--max-price", type=float, default=None, help="Maximum price (USD)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--playwright-only", action="store_true", help="Skip ScraperAPI, use Playwright only")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.playwright_only:
        results = await _search_playwright(args.query, args.max_results, args.condition, args.min_price, args.max_price)
    else:
        results = await search_ebay(
            query=args.query, max_results=args.max_results,
            condition=args.condition, min_price=args.min_price, max_price=args.max_price,
        )

    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n--- {len(results)} results ---", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(_main())
