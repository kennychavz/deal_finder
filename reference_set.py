"""Reference set of authentic Comfrt products.

These serve as ground-truth for similarity comparisons when scoring
marketplace candidates for potential infringement.

Product data and images collected from https://comfrt.com/products.json
"""

from __future__ import annotations

BRAND = "Comfrt"
BRAND_URL = "https://comfrt.com"

# 8 authentic products with verified working image URLs from Shopify CDN
REFERENCE_PRODUCTS: list[dict] = [
    {
        "title": "Camo Crop Zip Hoodie",
        "brand": BRAND,
        "product_type": "hoodie",
        "price": 49.00,
        "currency": "USD",
        "material": "cotton blend",
        "color": "camo",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/1_b1b09492-1788-42b7-ab1d-5c349d685453.jpg?v=1774414567",
        ],
        "description": "Camo crop zip hoodie",
        "url": "https://comfrt.com/products/camo-crop-zip-hoodie",
    },
    {
        "title": "You Matter Hoodie",
        "brand": BRAND,
        "product_type": "hoodie",
        "price": 49.00,
        "currency": "USD",
        "material": "cotton blend",
        "color": "multi",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/1_87c88fce-9d79-42ba-a1e8-26dbd04bca7d.jpg?v=1762181942",
        ],
        "description": "You Matter hoodie with graphic print",
        "url": "https://comfrt.com/products/you-matter-hoodie",
    },
    {
        "title": "Signature Crew",
        "brand": BRAND,
        "product_type": "sweatshirt",
        "price": 39.00,
        "currency": "USD",
        "material": "french terry cotton",
        "color": "multi",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/1_2074389a-341a-476f-9ba1-c5327a68bc46.jpg?v=1762181945",
        ],
        "description": "Signature crewneck sweatshirt",
        "url": "https://comfrt.com/products/signature-crew",
    },
    {
        "title": "VIP Airplane Mode Travel Hoodie",
        "brand": BRAND,
        "product_type": "hoodie",
        "price": 65.00,
        "currency": "USD",
        "material": "cotton blend",
        "color": "multi",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/1_-_2026-01-30T142925.389.jpg?v=1769812322",
        ],
        "description": "Travel hoodie with built-in eye mask and neck pillow",
        "url": "https://comfrt.com/products/vip-airplane-mode-travel-hoodie",
    },
    {
        "title": "Dreamday Plush Robe",
        "brand": BRAND,
        "product_type": "robe",
        "price": 55.00,
        "currency": "USD",
        "material": "plush fleece",
        "color": "multi",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/1_74b53d33-b498-44f1-bd39-6b87f9adc9b0.jpg?v=1771881817",
        ],
        "description": "Dreamday plush robe",
        "url": "https://comfrt.com/products/unisex-dreamday-plush-robe",
    },
    {
        "title": "Waffle Lounge Jogger",
        "brand": BRAND,
        "product_type": "sweatpants",
        "price": 35.00,
        "currency": "USD",
        "material": "waffle knit cotton",
        "color": "multi",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/3_-_2026-02-18T080627.083_176c5d14-36bd-4e4a-b888-8af9d9760280.jpg?v=1771433482",
        ],
        "description": "Waffle knit lounge jogger",
        "url": "https://comfrt.com/products/waffle-lounge-jogger",
    },
    {
        "title": "Waffle Lounge 7\" Short",
        "brand": BRAND,
        "product_type": "shorts",
        "price": 35.00,
        "currency": "USD",
        "material": "waffle knit cotton",
        "color": "multi",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/1_-_2026-02-16T135915.601.jpg?v=1771279598",
        ],
        "description": "Waffle knit lounge short",
        "url": "https://comfrt.com/products/waffle-lounge-7-short",
    },
    {
        "title": "Basic Wide Leg Sweatpants",
        "brand": BRAND,
        "product_type": "sweatpants",
        "price": 39.00,
        "currency": "USD",
        "material": "french terry cotton",
        "color": "multi",
        "images": [
            "https://cdn.shopify.com/s/files/1/0569/4029/8284/files/1_363f3128-c883-4470-ac2b-fa2bd480f544.jpg?v=1774559314",
        ],
        "description": "Basic wide leg sweatpants",
        "url": "https://comfrt.com/products/basic-wide-leg-sweatpants",
    },
]


# Pre-built search queries (6 distinct variations as required)
SEARCH_QUERIES: list[str] = [
    "comfrt blanket hoodie",
    "comfrt hoodie wearable blanket",
    "comfrt sweatshirt",
    "comfrt cloud hoodie",
    "comfrt joggers shorts",
    "comfrt sherpa hoodie oversized",
]


def get_reference_source() -> dict:
    """Return a combined source dict representing the Comfrt brand.

    Used as the 'source' input for the scoring engine — contains
    brand info and images from all reference products.
    """
    all_images = []
    for p in REFERENCE_PRODUCTS:
        all_images.extend(p.get("images", []))

    return {
        "title": "Comfrt — Blanket Hoodies, Loungewear & Apparel",
        "brand": BRAND,
        "url": BRAND_URL,
        "price": 49.00,  # median product price
        "currency": "USD",
        "product_type": "hoodie",
        "material": "cotton blend",
        "description": "Comfrt makes oversized wearable blanket hoodies and loungewear",
        "images": all_images,
        "search_query": " | ".join(SEARCH_QUERIES),
    }
