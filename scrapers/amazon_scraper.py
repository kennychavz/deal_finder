"""
Amazon product search scraper.

Primary:  ScraperAPI structured endpoint (fast, reliable, parsed JSON)
Fallback: Playwright + BeautifulSoup (no API key needed, but fragile)
"""

import asyncio
import argparse
import json
import logging
import os
import random
import re
import urllib.parse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "***REDACTED***")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]


# ---------------------------------------------------------------------------
# ScraperAPI (primary)
# ---------------------------------------------------------------------------

def _parse_scraperapi_result(item: dict) -> dict | None:
    """Convert a ScraperAPI structured result to our canonical format."""
    name = item.get("name", "")
    if not name:
        return None

    # Price — can be nested dict or string
    price = None
    price_raw = item.get("price")
    if isinstance(price_raw, (int, float)):
        price = float(price_raw)
    elif isinstance(price_raw, str):
        m = re.search(r"[\d,]+\.?\d*", price_raw.replace(",", ""))
        if m:
            price = float(m.group())
    elif isinstance(price_raw, dict):
        val = price_raw.get("current_price") or price_raw.get("value")
        if val:
            try:
                price = float(str(val).replace(",", "").replace("$", ""))
            except ValueError:
                pass

    # price_string fallback
    if price is None:
        ps = item.get("price_string", "")
        m = re.search(r"[\d,]+\.?\d*", ps.replace(",", ""))
        if m:
            price = float(m.group())

    asin = item.get("asin", "")
    url = item.get("url", "")
    if asin and not url:
        url = f"https://www.amazon.com/dp/{asin}"

    # Rating
    rating = None
    stars = item.get("stars")
    if stars is not None:
        try:
            rating = float(stars)
        except (ValueError, TypeError):
            pass

    review_count = 0
    tr = item.get("total_reviews")
    if tr is not None:
        try:
            review_count = int(str(tr).replace(",", ""))
        except (ValueError, TypeError):
            pass

    return {
        "title": name,
        "price": price,
        "currency": "USD",
        "url": url,
        "image_url": item.get("image", ""),
        "asin": asin,
        "rating": rating,
        "review_count": review_count,
        "prime": bool(item.get("has_prime") or item.get("is_prime")),
        "seller": None,
        "badge": item.get("badge") if item.get("is_best_seller") else None,
    }


def _search_scraperapi(
    query: str,
    max_results: int = 50,
    min_price: float = None,
    max_price: float = None,
) -> list[dict] | None:
    """Search Amazon via ScraperAPI structured endpoint. Returns None on failure."""
    results = []
    page = 1
    max_pages = max(1, (max_results // 20) + 1)

    while len(results) < max_results and page <= max_pages:
        params = {
            "api_key": SCRAPER_API_KEY,
            "query": query,
            "page": str(page),
        }

        try:
            logger.info("ScraperAPI Amazon page %d: %s", page, query)
            resp = requests.get(
                "https://api.scraperapi.com/structured/amazon/search",
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

def _parse_price(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def _parse_rating(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"(\d+\.?\d*)\s*out\s*of", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _parse_review_count(text: str) -> int:
    if not text:
        return 0
    match = re.search(r"[\d,]+", text)
    if match:
        try:
            return int(match.group().replace(",", ""))
        except ValueError:
            return 0
    return 0


def _extract_asin(element) -> str | None:
    asin = element.get("data-asin")
    if asin and asin.strip():
        return asin.strip()
    link = element.select_one("a[href*='/dp/']")
    if link:
        href = link.get("href", "")
        match = re.search(r"/dp/([A-Z0-9]{10})", href)
        if match:
            return match.group(1)
    return None


def _is_sponsored(element) -> bool:
    sponsored_markers = element.select(
        "span.puis-label-popover-default, "
        "span[data-component-type='sp-sponsored-result']"
    )
    if sponsored_markers:
        return True
    text = element.get_text(separator=" ", strip=True).lower()
    if "sponsored" in text[:200]:
        return True
    return False


def _parse_result_playwright(element) -> dict | None:
    asin = _extract_asin(element)
    if not asin:
        return None
    if _is_sponsored(element):
        return None

    title_el = element.select_one(
        "h2 span, h2 a span, span.a-size-medium.a-color-base.a-text-normal"
    )
    title = title_el.get_text(strip=True) if title_el else None
    if not title:
        return None

    price = None
    price_whole = element.select_one("span.a-price-whole")
    price_frac = element.select_one("span.a-price-fraction")
    if price_whole:
        whole = price_whole.get_text(strip=True).replace(",", "").rstrip(".")
        frac = price_frac.get_text(strip=True) if price_frac else "00"
        try:
            price = float(f"{whole}.{frac}")
        except ValueError:
            pass
    if price is None:
        price_el = element.select_one("span.a-price span.a-offscreen")
        if price_el:
            price = _parse_price(price_el.get_text(strip=True))

    img_el = element.select_one("img.s-image")
    image_url = img_el.get("src", "") if img_el else ""

    rating = None
    rating_el = element.select_one("span.a-icon-alt")
    if rating_el:
        rating = _parse_rating(rating_el.get_text(strip=True))

    review_count = 0
    review_el = element.select_one(
        "span.a-size-base.s-underline-text, "
        "a[href*='customerReviews'] span.a-size-base"
    )
    if review_el:
        review_count = _parse_review_count(review_el.get_text(strip=True))

    prime = bool(element.select_one("i.a-icon-prime, span[data-a-badge-type='prime']"))

    seller = None
    seller_el = element.select_one("span.a-size-small.a-color-secondary:has(+ span)")
    if seller_el:
        seller = seller_el.get_text(strip=True)

    badge = None
    badge_el = element.select_one(
        "span.a-badge-text, "
        "span[data-component-type='s-status-badge-component'] span.a-badge-text"
    )
    if badge_el:
        badge = badge_el.get_text(strip=True)

    return {
        "title": title,
        "price": price,
        "currency": "USD",
        "url": f"https://www.amazon.com/dp/{asin}",
        "image_url": image_url,
        "asin": asin,
        "rating": rating,
        "review_count": review_count,
        "prime": prime,
        "seller": seller,
        "badge": badge,
    }


async def _search_playwright(
    query: str,
    max_results: int = 50,
    min_price: float = None,
    max_price: float = None,
) -> list[dict]:
    """Fallback: Playwright + BeautifulSoup scraper."""
    results = []
    page = 1
    max_pages = (max_results // 16) + 2

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=random.choice(USER_AGENTS),
            locale="en-US",
            timezone_id="America/New_York",
        )
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        page_obj = await context.new_page()

        try:
            await page_obj.goto("https://www.amazon.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(1.5, 3))
        except Exception:
            pass

        while len(results) < max_results and page <= max_pages:
            params = {"k": query}
            if page > 1:
                params["page"] = str(page)
            if min_price is not None or max_price is not None:
                lo = int(min_price * 100) if min_price else ""
                hi = int(max_price * 100) if max_price else ""
                params["rh"] = f"p_36:{lo}-{hi}"

            url = f"https://www.amazon.com/s?{urllib.parse.urlencode(params)}"

            success = False
            for attempt in range(3):
                try:
                    response = await page_obj.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if response and response.status == 200:
                        try:
                            await page_obj.wait_for_selector(
                                "div[data-component-type='s-search-result']", timeout=15000
                            )
                        except Exception:
                            pass
                        success = True
                        break
                    await asyncio.sleep(random.uniform(2, 5))
                except Exception:
                    await asyncio.sleep(random.uniform(2, 4))

            if not success:
                break

            html = await page_obj.content()
            if "captcha" in html.lower() or "robot check" in html.lower():
                break

            soup = BeautifulSoup(html, "html.parser")
            elements = soup.select("div[data-component-type='s-search-result']")
            if not elements:
                break

            for el in elements:
                if len(results) >= max_results:
                    break
                product = _parse_result_playwright(el)
                if product and product["price"] is not None:
                    if min_price and product["price"] < min_price:
                        continue
                    if max_price and product["price"] > max_price:
                        continue
                    results.append(product)

            page += 1
            await asyncio.sleep(random.uniform(2, 5))

        await browser.close()

    return results[:max_results]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_amazon(
    query: str,
    max_results: int = 50,
    min_price: float = None,
    max_price: float = None,
) -> list[dict]:
    """
    Search Amazon for products matching the query.

    Tries ScraperAPI first (structured JSON, reliable).
    Falls back to Playwright scraping if ScraperAPI fails.

    Returns list of dicts: title, price, currency, url, image_url,
    asin, rating, review_count, prime, seller, badge.
    """
    # Try ScraperAPI first (sync call in thread to not block)
    try:
        results = await asyncio.to_thread(
            _search_scraperapi, query, max_results, min_price, max_price
        )
        if results is not None and len(results) > 0:
            logger.info("ScraperAPI returned %d Amazon results", len(results))
            return results
        logger.warning("ScraperAPI returned no results, falling back to Playwright")
    except Exception as e:
        logger.warning("ScraperAPI failed (%s), falling back to Playwright", e)

    # Fallback to Playwright
    return await _search_playwright(query, max_results, min_price, max_price)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search Amazon for products")
    parser.add_argument("query", type=str, help="Search query")
    parser.add_argument("--max-results", type=int, default=20, help="Maximum results (default: 20)")
    parser.add_argument("--min-price", type=float, default=None, help="Min price USD")
    parser.add_argument("--max-price", type=float, default=None, help="Max price USD")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--playwright-only", action="store_true", help="Skip ScraperAPI, use Playwright only")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.playwright_only:
        results = asyncio.run(_search_playwright(args.query, args.max_results, args.min_price, args.max_price))
    else:
        results = asyncio.run(search_amazon(args.query, args.max_results, args.min_price, args.max_price))

    print(json.dumps(results, indent=2))
