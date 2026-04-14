"""
Generic product information extractor.

Given a product URL, extracts canonical product attributes that can be used
for similarity search across Amazon and eBay.

Extraction strategies (tried in order):
1. Shopify JSON endpoint (/products/{handle}.json)
2. JSON-LD structured data (schema.org Product)
3. Open Graph / meta tags
4. HTML parsing fallback

Output: a canonical ProductInfo dict.
"""

import argparse
import asyncio
import json
import re
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth


@dataclass
class ProductInfo:
    """Canonical product representation for similarity search."""
    # Identity
    title: str = ""
    brand: str = ""
    url: str = ""

    # Pricing
    price: float | None = None
    compare_at_price: float | None = None
    currency: str = ""

    # Classification
    product_type: str = ""          # e.g. "Shirt", "Electronics"
    category: str = ""              # e.g. "Clothing > Loungewear > Tops"
    tags: list[str] = field(default_factory=list)

    # Description
    description: str = ""           # plain text, cleaned
    features: list[str] = field(default_factory=list)  # bullet point features

    # Specifications
    material: str = ""              # e.g. "60% Cotton, 40% Polyester"
    color: str = ""
    size: str = ""
    available_colors: list[str] = field(default_factory=list)
    available_sizes: list[str] = field(default_factory=list)
    fit: str = ""                   # e.g. "Relaxed Fit"
    care_instructions: str = ""

    # Media
    images: list[str] = field(default_factory=list)     # image URLs

    # Identifiers
    sku: str = ""
    source_platform: str = ""       # "shopify", "amazon", "ebay", "generic"
    source_product_id: str = ""

    # Rating
    rating: float | None = None
    review_count: int | None = None

    def to_search_query(self) -> str:
        """Generate a generic search query for Amazon/eBay.

        Intentionally drops brand name (other marketplaces won't carry it)
        and focuses on product type, fabric, and style keywords that match
        across sellers.
        """
        parts = []

        # Title is the core — but strip the brand from it if present
        title = self.title
        if self.brand and title.lower().startswith(self.brand.lower()):
            title = title[len(self.brand):].strip()

        if title:
            parts.append(title)

        # Add material keywords (e.g. "cotton polyester waffle knit")
        if self.material:
            # Extract material names without percentages
            mat_words = re.sub(r"\d+%\s*", "", self.material)
            mat_words = mat_words.replace(",", " ").strip()
            if mat_words:
                parts.append(mat_words)

        # Add product type if not already in title
        if self.product_type:
            pt_lower = self.product_type.lower()
            title_lower = title.lower()
            if pt_lower not in title_lower:
                parts.append(self.product_type)

        query = " ".join(parts)
        # Trim to reasonable length for search
        if len(query) > 120:
            query = query[:120].rsplit(" ", 1)[0]
        return query

    def to_dict(self) -> dict:
        d = asdict(self)
        d["search_query"] = self.to_search_query()
        return d


def _clean_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _extract_features(text: str) -> list[str]:
    """Pull bullet-point features from description text."""
    features = []
    # Split on common separators
    for line in re.split(r"[•\-\*\n]", text):
        line = line.strip()
        if 10 < len(line) < 200:
            features.append(line)
    return features


# ---------------------------------------------------------------------------
# Strategy 1: Shopify JSON
# ---------------------------------------------------------------------------

async def _try_shopify_json(page, url: str, info: ProductInfo) -> bool:
    """Try fetching /products/{handle}.json for Shopify stores."""
    parsed = urlparse(url)
    path = parsed.path

    # Extract handle from path like /en-ca/products/waffle-lounge-long-sleeve
    match = re.search(r"/products/([^/?#]+)", path)
    if not match:
        return False

    handle = match.group(1)
    json_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.json"

    try:
        resp = await page.goto(json_url, wait_until="domcontentloaded", timeout=15000)
        if not resp or resp.status != 200:
            return False

        text = await page.inner_text("body")
        data = json.loads(text)
        product = data.get("product", {})
    except Exception:
        return False

    info.source_platform = "shopify"
    info.title = product.get("title", "")
    info.brand = product.get("vendor", "")
    info.product_type = product.get("product_type", "")
    info.tags = [t.strip() for t in product.get("tags", "").split(",") if t.strip()] if isinstance(product.get("tags"), str) else product.get("tags", [])
    info.source_product_id = str(product.get("id", ""))

    body_html = product.get("body_html", "")
    if body_html:
        info.description = _clean_html(body_html)
        info.features = _extract_features(info.description)

    # Images
    for img in product.get("images", []):
        src = img.get("src", "")
        if src:
            info.images.append(src)

    # Variants — extract options and find the selected variant
    options = product.get("options", [])
    for opt in options:
        name = opt.get("name", "").lower()
        values = opt.get("values", [])
        if "color" in name or "colour" in name:
            info.available_colors = values
        elif "size" in name:
            info.available_sizes = values

    # Extract variant matching the URL's ?variant= param
    variant_id = None
    variant_match = re.search(r"variant=(\d+)", url)
    if variant_match:
        variant_id = int(variant_match.group(1))

    variants = product.get("variants", [])
    selected = None
    if variant_id:
        selected = next((v for v in variants if v.get("id") == variant_id), None)
    if not selected and variants:
        selected = variants[0]

    if selected:
        info.sku = selected.get("sku", "")
        try:
            info.price = float(selected.get("price", 0))
        except (ValueError, TypeError):
            pass
        try:
            cap = selected.get("compare_at_price")
            if cap:
                info.compare_at_price = float(cap)
        except (ValueError, TypeError):
            pass

        opt1 = selected.get("option1", "")
        opt2 = selected.get("option2", "")
        # Determine which option is color vs size
        for opt in options:
            pos = opt.get("position", 0)
            name = opt.get("name", "").lower()
            val = selected.get(f"option{pos}", "")
            if "color" in name or "colour" in name:
                info.color = val
            elif "size" in name:
                info.size = val

    return True


# ---------------------------------------------------------------------------
# Strategy 2: JSON-LD structured data
# ---------------------------------------------------------------------------

def _extract_jsonld(soup: BeautifulSoup, info: ProductInfo) -> bool:
    """Extract product info from JSON-LD script tags."""
    scripts = soup.select('script[type="application/ld+json"]')
    product_data = None

    for script in scripts:
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        # Handle arrays
        if isinstance(data, list):
            for item in data:
                if item.get("@type") in ("Product", "ProductGroup"):
                    product_data = item
                    break
        elif data.get("@type") in ("Product", "ProductGroup"):
            product_data = data

        if product_data:
            break

    if not product_data:
        return False

    info.title = info.title or product_data.get("name", "")
    info.description = info.description or _clean_html(product_data.get("description", ""))

    brand = product_data.get("brand", {})
    if isinstance(brand, dict):
        info.brand = info.brand or brand.get("name", "")
    elif isinstance(brand, str):
        info.brand = info.brand or brand

    # Material
    mat = product_data.get("material", "")
    if mat:
        info.material = mat

    # Category
    cat = product_data.get("category", "")
    if cat:
        info.category = cat

    # Images
    if not info.images:
        imgs = product_data.get("image", [])
        if isinstance(imgs, str):
            imgs = [imgs]
        elif isinstance(imgs, dict):
            imgs = [imgs.get("url", "")]
        info.images = [i for i in imgs if i]

    # Rating
    rating_data = product_data.get("aggregateRating", {})
    if rating_data:
        try:
            info.rating = float(rating_data.get("ratingValue", 0))
            info.review_count = int(rating_data.get("reviewCount", 0))
        except (ValueError, TypeError):
            pass

    # Price from offers
    offers = product_data.get("offers", product_data.get("hasVariant", []))
    if isinstance(offers, dict):
        offers = [offers]
    if offers and isinstance(offers, list):
        first = offers[0]
        if not info.price:
            try:
                price_val = first.get("price") or first.get("lowPrice")
                if price_val:
                    info.price = float(price_val)
            except (ValueError, TypeError):
                pass
        if not info.currency:
            info.currency = first.get("priceCurrency", "")

    return True


# ---------------------------------------------------------------------------
# Strategy 3: Meta tags (Open Graph + standard meta)
# ---------------------------------------------------------------------------

def _extract_meta(soup: BeautifulSoup, info: ProductInfo) -> bool:
    """Extract from og: and standard meta tags."""
    found_anything = False

    def meta(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag["content"].strip() if tag and tag.get("content") else ""

    og_title = meta("og:title")
    if og_title and not info.title:
        info.title = og_title
        found_anything = True

    og_desc = meta("og:description") or meta("description")
    if og_desc and not info.description:
        info.description = og_desc
        found_anything = True

    og_image = meta("og:image")
    if og_image and not info.images:
        info.images = [og_image]
        found_anything = True

    og_price = meta("product:price:amount") or meta("og:price:amount")
    if og_price and not info.price:
        try:
            info.price = float(og_price)
            found_anything = True
        except ValueError:
            pass

    og_currency = meta("product:price:currency") or meta("og:price:currency")
    if og_currency and not info.currency:
        info.currency = og_currency

    og_brand = meta("product:brand") or meta("og:brand")
    if og_brand and not info.brand:
        info.brand = og_brand

    return found_anything


# ---------------------------------------------------------------------------
# Strategy 4: HTML fallback
# ---------------------------------------------------------------------------

def _extract_html_fallback(soup: BeautifulSoup, info: ProductInfo) -> bool:
    """Last resort: scrape common HTML patterns."""
    found = False

    if not info.title:
        h1 = soup.select_one("h1")
        if h1:
            info.title = h1.get_text(strip=True)
            found = True

    if not info.images:
        # Look for product images
        for img in soup.select("img[src*='cdn.shopify'], img[src*='product'], img.product-image, img[data-zoom]"):
            src = img.get("src") or img.get("data-src") or ""
            if src and src not in info.images:
                info.images.append(src)
                found = True

    if not info.description:
        for sel in [".product-description", "#product-description", "[data-product-description]", ".product__description"]:
            el = soup.select_one(sel)
            if el:
                info.description = el.get_text(separator=" ", strip=True)
                found = True
                break

    return found


# ---------------------------------------------------------------------------
# Material / care extraction from page text
# ---------------------------------------------------------------------------

def _extract_material_and_care(soup: BeautifulSoup, info: ProductInfo):
    """Search page text for material composition and care instructions."""
    text = soup.get_text(separator="\n", strip=True)

    # Material patterns
    if not info.material:
        mat_patterns = [
            r"(\d+%\s*\w+(?:\s*,\s*\d+%\s*\w+)+)",       # "60% Cotton, 40% Polyester"
            r"((?:\d+%\s+\w+\s*)+)",                        # "60% Cotton 40% Polyester"
            r"Material:\s*(.+?)(?:\n|$)",
            r"Fabric:\s*(.+?)(?:\n|$)",
            r"Composition:\s*(.+?)(?:\n|$)",
        ]
        for pat in mat_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                info.material = m.group(1).strip()
                break

    # Care instructions
    if not info.care_instructions:
        care_patterns = [
            r"(?:Care|Care Instructions|Wash):\s*(.+?)(?:\n\n|\n[A-Z]|$)",
            r"(Machine wash.+?)(?:\n\n|\n[A-Z]|$)",
        ]
        for pat in care_patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                info.care_instructions = re.sub(r"\s+", " ", m.group(1)).strip()
                break

    # Fit
    if not info.fit:
        fit_patterns = [
            r"((?:Relaxed|Slim|Regular|Oversized|Loose)\s+Fit[^.]*\.)",
        ]
        for pat in fit_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                info.fit = m.group(1).strip()
                break


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

async def extract_product(url: str) -> ProductInfo:
    """
    Extract canonical product information from a product URL.

    Tries multiple strategies in order:
    1. Shopify JSON API
    2. JSON-LD structured data
    3. Open Graph / meta tags
    4. HTML parsing fallback

    Returns a ProductInfo with as many fields filled as possible.
    """
    info = ProductInfo(url=url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
        )
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        page = await context.new_page()

        # Strategy 1: Shopify JSON (fast, structured)
        shopify_ok = await _try_shopify_json(page, url, info)
        if shopify_ok:
            info.source_platform = "shopify"

        # Now load the actual product page for remaining strategies
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_selector("h1, [data-product-title]", timeout=5000)
            except Exception:
                pass
            html = await page.content()
        except Exception:
            html = ""

        await browser.close()

    if not html:
        return info

    soup = BeautifulSoup(html, "lxml")

    # Strategy 2: JSON-LD
    _extract_jsonld(soup, info)

    # Strategy 3: Meta tags
    _extract_meta(soup, info)

    # Strategy 4: HTML fallback
    _extract_html_fallback(soup, info)

    # Extract material/care from full page text
    _extract_material_and_care(soup, info)

    # Derive features from description if not already set
    if not info.features and info.description:
        info.features = _extract_features(info.description)

    # Determine platform if not set
    if not info.source_platform:
        domain = urlparse(url).netloc.lower()
        if "amazon" in domain:
            info.source_platform = "amazon"
        elif "ebay" in domain:
            info.source_platform = "ebay"
        else:
            info.source_platform = "generic"

    return info


async def _main():
    parser = argparse.ArgumentParser(description="Extract product info from a URL")
    parser.add_argument("url", help="Product URL to extract from")
    parser.add_argument("--search-query", action="store_true", help="Print generated search query instead of full JSON")
    args = parser.parse_args()

    info = await extract_product(args.url)

    if args.search_query:
        print(info.to_search_query())
    else:
        print(json.dumps(info.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_main())
