"""Curated placeholder photography for the demo store.

Every entry is a real Unsplash photo of a person modelling clothing, chosen so
the storefront reads as a womenswear shop. Each was verified to resolve and its
description is used as the image's alt text.

Unsplash photos are free to use commercially under the Unsplash License. These
are stand-ins until real product photography is shot and uploaded through the
dashboard — replace them there, not here.
"""

UNSPLASH = "https://images.unsplash.com/photo-{id}?w={w}&h={h}&fit=crop&crop=entropy&q=80"


def photo_url(photo_id: str, width: int, height: int) -> str:
    return UNSPLASH.format(id=photo_id, w=width, h=height)


# (photo id, description used as alt text)
Photo = tuple[str, str]

# ---------------------------------------------------------------- by category

CATEGORY_POOLS: dict[str, list[Photo]] = {
    "Knitwear": [
        ("1612636676503-77f496c96ef8", "Model wearing a brown knitted sweater"),
        ("1574201635302-388dd92a4c3f", "Model wearing a grey knit sweater"),
        ("1634499913011-86108564b787", "Model wearing a red knitted sweater and trousers"),
        ("1760552069049-600f71fa5bbf", "Model wearing a cream sweater indoors"),
    ],
    "Loungewear": [
        ("1766056278842-b754f1e093c0", "Model wearing soft white loungewear"),
        ("1759229874681-39fb36b01e32", "Model relaxing in comfortable loungewear"),
        ("1779675787669-9b65d225dff5", "Model wearing a soft brown lounge set"),
        ("1766056278798-39cabf7ca628", "Model in loungewear beside a window"),
    ],
    "Dresses": [
        ("1520026582657-4daf5bb60adb", "Model wearing a white dress"),
        ("1721990336298-90832e791b5a", "Model wearing a dress and wide-brimmed hat"),
        ("1551163943-3f6a855d1153", "Model seated wearing a long dress"),
        ("1617019114583-affb34d1b3cd", "Model wearing a white long-sleeved dress"),
    ],
    "Tops & Shirts": [
        ("1614312185032-a96342b80e3d", "Model wearing a white button-up shirt"),
        ("1713812956728-9b4bee399d13", "Model wearing a crisp white shirt"),
        ("1783113298894-eeb3b71315d9", "Model wearing a white linen shirt"),
        ("1773439877855-cd193d949717", "Model wearing a soft grey outfit"),
    ],
    "Trousers": [
        ("1713812964743-f5bc0e117154", "Model wearing a white shirt and tailored trousers"),
        ("1745152046546-9be55fd82717", "Model wearing relaxed trousers by a window"),
        ("1779675789001-1c01b5a8aa30", "Models wearing relaxed wide-leg trousers"),
        ("1766056278986-af4b8a4fdae7", "Model wearing soft tapered trousers"),
    ],
    "Accessories": [
        ("1496747611176-843222e1e57c", "Model carrying a woven bag"),
        ("1618244965061-1d27b208d6e8", "Model wearing a wrap coat and scarf"),
        ("1657373307141-349a3393d4d9", "Model wearing a knitted accessory on a balcony"),
        ("1760552069049-600f71fa5bbf", "Model wearing a cream hat and sweater"),
    ],
}

# Falls back to this when a category has no dedicated pool.
DEFAULT_POOL: list[Photo] = CATEGORY_POOLS["Knitwear"]

# -------------------------------------------------------------- category hero

CATEGORY_HERO: dict[str, Photo] = {
    "Knitwear": ("1612636676503-77f496c96ef8", "Model wearing a brown knitted sweater"),
    "Loungewear": ("1766056278842-b754f1e093c0", "Model wearing soft white loungewear"),
    "Dresses": ("1520026582657-4daf5bb60adb", "Model wearing a white dress"),
    "Tops & Shirts": ("1614312185032-a96342b80e3d", "Model wearing a white button-up shirt"),
    "Trousers": ("1713812964743-f5bc0e117154", "Model wearing tailored trousers"),
    "Accessories": ("1496747611176-843222e1e57c", "Model carrying a woven bag"),
}

FABRIC_HERO: dict[str, Photo] = {
    "Cashmere": ("1574201635302-388dd92a4c3f", "Model wearing a grey cashmere sweater"),
    "Linen": ("1783113298894-eeb3b71315d9", "Model wearing a white linen shirt"),
    "Modal": ("1759229874681-39fb36b01e32", "Model wearing a soft modal lounge set"),
    "Organic Cotton": ("1713812956728-9b4bee399d13", "Model wearing an organic cotton shirt"),
    "Merino": ("1634499913011-86108564b787", "Model wearing a merino knit"),
}

COLLECTION_HERO: dict[str, Photo] = {
    "New Arrivals": ("1760552069049-600f71fa5bbf", "Model wearing this season's new cream knitwear"),
    "Bestsellers": ("1612636676503-77f496c96ef8", "Model wearing a bestselling knitted sweater"),
    "Sale": ("1618244965061-1d27b208d6e8", "Model wearing a wrap coat"),
    "The Gift Guide": ("1496747611176-843222e1e57c", "Model carrying a woven bag"),
}

# ------------------------------------------------------------- home & journal

HOME_HERO: dict[str, Photo] = {
    "hero": ("1760552069049-600f71fa5bbf", "Model wearing a cream sweater and hat"),
    "editorial": ("1612636676503-77f496c96ef8", "Model wearing a brown knitted sweater"),
    "sustainability": ("1759229875274-bd920070ceef", "Models wearing matching beige loungewear"),
}

JOURNAL_POOL: list[Photo] = [
    ("1574201635302-388dd92a4c3f", "Model wearing a grey knit sweater"),
    ("1759229875274-bd920070ceef", "Models wearing beige loungewear in a library"),
    ("1612636676503-77f496c96ef8", "Model wearing a brown knitted sweater"),
    ("1783113298894-eeb3b71315d9", "Model wearing a white linen shirt outdoors"),
    ("1713812956728-9b4bee399d13", "Model wearing an organic cotton shirt"),
    ("1745152046546-9be55fd82717", "Model dressed in relaxed winter layers"),
]


def pool_for_category(category_name: str) -> list[Photo]:
    return CATEGORY_POOLS.get(category_name, DEFAULT_POOL)
