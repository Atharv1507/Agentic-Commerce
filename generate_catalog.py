"""Generate the demo catalogue: 300 shirts and T-shirts.

`catalog.json` is the source of truth for the whole system — it is what gets
embedded into ChromaDB at startup and what every search scores against. This
script is how that file is produced, so the catalogue's composition is a
deliberate, reviewable thing rather than whatever a scrape happened to contain.

Why generated rather than scraped: the previous catalogue had 400 products
spread over ~40 product types, which left 13 shirts and exactly ONE linen item
in the entire file. Any request with two constraints ("linen shirt under 2k")
was unanswerable — not because the agent was wrong, but because the shelf was
empty. Depth in one category beats breadth for both testing and demoing.

What the composition guarantees (verified by `--report`, and asserted at the end
of a build):
  * ~160 shirts / ~140 T-shirts, kept as distinct product types
  * every colour family the search knows about, with enough of each to filter on
  * real fabric coverage, linen included, so "preferably linen" has a true answer
  * four populated price bands, so budget / premium / range asks all resolve
  * enough brands that no single one can fill a result page

Usage:
    python generate_catalog.py                 # writes catalog.json
    python generate_catalog.py --report        # show composition, write nothing
    python generate_catalog.py --count 500     # a bigger shelf

Fields match exactly what `rag.load_catalog` reads — id, name, brand, gender,
price, description, color, tags, image — and nothing else. A field the system
doesn't read is dead weight in the source of truth.
"""

import argparse
import json
import logging
import random
import sys
from collections import Counter
from typing import Any, Optional
from urllib.parse import quote

from vocab import GARMENT_TOKENS, MATERIAL_TOKENS, canonical_color, tokenize

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Vocabulary. Every fabric and colour word here is one `vocab.py` recognises,
# because a fabric the tokeniser can't see is a fabric the shopper can't filter
# on — the words have to survive into `tags` to be searchable.
# --------------------------------------------------------------------------

# (display name, hex, how many slots it gets in the deal deck). Hex only drives
# the placeholder swatch. Display names are
# chosen so `canonical_color` maps them into the right family, which is what
# makes "something in grey" also accept Charcoal and Slate.
#
# Weights exist because families have unequal numbers of spellings: brown has
# six (Beige, Tan, Khaki, Camel...) and black has two, so an unweighted deck
# handed brown 40 products and black 13 — leaving the single most-requested
# colour in the catalogue the hardest one to filter on.
COLORS: list[tuple[str, str, int]] = [
    ("Black", "#1a1a1a", 6), ("Jet Black", "#111111", 3),
    ("White", "#f4f2ee", 5), ("Off White", "#ece7dd", 2), ("Ivory", "#efe7d6", 2), ("Cream", "#f0e6d2", 2),
    ("Grey", "#8a8d91", 4), ("Charcoal", "#3f4448", 3), ("Slate", "#5c6b73", 2), ("Steel Grey", "#71797e", 2),
    ("Navy Blue", "#1f2a44", 5), ("Blue", "#2f5da8", 4), ("Sky Blue", "#7cb6e0", 3),
    ("Teal", "#1f6f6b", 2), ("Cobalt Blue", "#2a4bd7", 1), ("Indigo", "#2b3a67", 2),
    ("Olive Green", "#5f6b3a", 3), ("Green", "#2f6b3f", 2), ("Sage Green", "#9aa87b", 2),
    ("Mint Green", "#a8d5b5", 1), ("Emerald Green", "#146b4a", 1),
    ("Maroon", "#5c1a26", 3), ("Red", "#a82f2f", 3), ("Burgundy", "#5d2033", 1),
    ("Wine", "#5b2233", 1), ("Rust", "#a35a2a", 2),
    ("Pink", "#d98ba5", 3), ("Blush Pink", "#e5b7bd", 2), ("Rose", "#c9697e", 1), ("Fuchsia", "#a8367c", 1),
    ("Beige", "#cdbb9c", 3), ("Brown", "#6b4a35", 3), ("Tan", "#b58a5e", 1),
    ("Khaki", "#9c8b62", 2), ("Camel", "#b98c58", 1), ("Coffee Brown", "#4a352a", 1),
    ("Yellow", "#ddb135", 2), ("Mustard", "#c39227", 2), ("Lemon Yellow", "#e3cf5a", 1),
    ("Lavender", "#a99bc1", 2), ("Purple", "#5f3d78", 2), ("Lilac", "#bda6cf", 1),
    ("Peach", "#e8b393", 2), ("Coral", "#dd7b62", 2), ("Orange", "#cf6a2a", 2),
]

# (fabric words, price tier 0-2, weight for shirts, weight for T-shirts)
# Tier drives price: linen and silk genuinely cost more than polyester, and a
# catalogue where fabric doesn't move the price makes "premium" meaningless.
# `genders` is None when the fabric suits everyone. Restricted where a real shop
# wouldn't stock it otherwise — a men's georgette formal shirt is not a thing,
# and an obviously wrong product undermines the demo more than a missing one.
ALL_GENDERS = None
FABRICS: list[dict[str, Any]] = [
    {"name": "Pure Cotton", "tier": 1, "shirt": 10, "tshirt": 12, "genders": ALL_GENDERS},
    {"name": "Cotton", "tier": 0, "shirt": 8, "tshirt": 14, "genders": ALL_GENDERS},
    {"name": "Cotton Blend", "tier": 0, "shirt": 5, "tshirt": 8, "genders": ALL_GENDERS},
    # Linen shirts yes, linen T-shirts no — nobody makes those.
    {"name": "Linen", "tier": 2, "shirt": 10, "tshirt": 0, "genders": ALL_GENDERS},
    {"name": "Cotton Linen", "tier": 1, "shirt": 7, "tshirt": 0, "genders": ALL_GENDERS},
    # Chambray covers the denim-look shirt. Actual "Denim" is deliberately absent:
    # vocab.CANONICAL_TOKENS folds denim -> jean so the garment "denims" can match
    # jeans, which means a shirt described as Denim records NO fabric and could
    # never answer a fabric request. Chambray tokenises as itself.
    {"name": "Chambray", "tier": 1, "shirt": 7, "tshirt": 0, "genders": ALL_GENDERS},
    {"name": "Corduroy", "tier": 1, "shirt": 3, "tshirt": 0, "genders": ALL_GENDERS},
    {"name": "Khadi Cotton", "tier": 1, "shirt": 3, "tshirt": 0, "genders": ALL_GENDERS},
    {"name": "Silk", "tier": 2, "shirt": 4, "tshirt": 0, "genders": ALL_GENDERS},
    {"name": "Satin", "tier": 2, "shirt": 3, "tshirt": 0, "genders": ("Women",)},
    {"name": "Georgette", "tier": 1, "shirt": 4, "tshirt": 0, "genders": ("Women",)},
    {"name": "Crepe", "tier": 1, "shirt": 4, "tshirt": 0, "genders": ("Women",)},
    {"name": "Viscose Rayon", "tier": 1, "shirt": 5, "tshirt": 1, "genders": ALL_GENDERS},
    {"name": "Rayon", "tier": 0, "shirt": 3, "tshirt": 1, "genders": ALL_GENDERS},
    {"name": "Polyester", "tier": 0, "shirt": 4, "tshirt": 4, "genders": ALL_GENDERS},
    {"name": "Jersey Cotton", "tier": 0, "shirt": 0, "tshirt": 8, "genders": ALL_GENDERS},
    {"name": "Cotton Lycra", "tier": 0, "shirt": 0, "tshirt": 5, "genders": ALL_GENDERS},
    {"name": "Organic Cotton", "tier": 2, "shirt": 2, "tshirt": 5, "genders": ALL_GENDERS},
    {"name": "Wool Blend", "tier": 2, "shirt": 2, "tshirt": 0, "genders": ALL_GENDERS},
]

PATTERNS_SHIRT = [
    ("Solid", 16), ("Striped", 10), ("Checked", 10), ("Printed", 8),
    ("Floral Print", 6), ("Textured", 5), ("Self Design", 5),
    ("Geometric Print", 3), ("Polka Dot", 2), ("Colourblocked", 2),
]
PATTERNS_TSHIRT = [
    ("Solid", 16), ("Printed", 12), ("Graphic Print", 9), ("Striped", 8),
    ("Typography Print", 6), ("Colourblocked", 4), ("Tie & Dye", 3), ("Textured", 2),
]

FITS_SHIRT = [("Slim Fit", 10), ("Regular Fit", 10), ("Relaxed Fit", 6), ("Tailored Fit", 4), ("Oversized", 3)]
FITS_TSHIRT = [("Regular Fit", 10), ("Slim Fit", 7), ("Oversized", 7), ("Boxy Fit", 3), ("Relaxed Fit", 5)]

# Details that make two products with the same fabric and colour read as
# genuinely different items.
DETAILS_SHIRT = {
    "Men": ["Casual Shirt", "Formal Shirt", "Half Sleeves Casual Shirt", "Roll-Up Sleeves Casual Shirt",
            "Mandarin Collar Casual Shirt", "Spread Collar Formal Shirt", "Party Shirt",
            "Button-Down Casual Shirt", "Cuban Collar Casual Shirt", "Office Formal Shirt"],
    "Women": ["Casual Shirt", "Formal Shirt", "Puff Sleeves Casual Shirt", "Oversized Casual Shirt",
              "Tie-Up Casual Shirt", "Collared Formal Shirt", "Party Shirt", "Longline Casual Shirt",
              "Sleeveless Casual Shirt", "Office Formal Shirt"],
    # Every entry must end in "Shirt" or "T-shirt": the search identifies a
    # product's type from that head noun, and "Overshirt" left products untyped.
    "Unisex": ["Casual Shirt", "Half Sleeves Casual Shirt", "Utility Casual Shirt",
               "Relaxed Utility Shirt", "Boxy Casual Shirt", "Resort Casual Shirt"],
}
DETAILS_TSHIRT = {
    "Men": ["Round Neck T-shirt", "V-Neck T-shirt", "Polo Collar T-shirt", "Henley Neck T-shirt",
            "Half Sleeves T-shirt", "Full Sleeves T-shirt", "Casual T-shirt", "Lounge T-shirt"],
    "Women": ["Round Neck T-shirt", "V-Neck T-shirt", "Boat Neck T-shirt", "Polo Collar T-shirt",
              "Crop T-shirt", "Half Sleeves T-shirt", "Casual T-shirt", "Lounge T-shirt"],
    "Unisex": ["Round Neck T-shirt", "Oversized T-shirt", "Drop Shoulder T-shirt",
               "Half Sleeves T-shirt", "Casual T-shirt"],
}

# (brand, price tier 0-2, genders it sells to). Tier lines up with fabric tier so
# a ₹5,000 silk shirt doesn't arrive branded as a value label.
BRANDS: list[tuple[str, int, tuple[str, ...]]] = [
    ("Roadster", 0, ("Men", "Women", "Unisex")),
    ("HRX", 0, ("Men", "Women", "Unisex")),
    ("Max", 0, ("Men", "Women")),
    ("Urbano", 0, ("Men",)),
    ("Kook N Keech", 0, ("Men", "Women", "Unisex")),
    ("Dressberry", 0, ("Women",)),
    ("Levis", 1, ("Men", "Women")),
    ("H&M", 1, ("Men", "Women", "Unisex")),
    ("Jack & Jones", 1, ("Men",)),
    ("Peter England", 1, ("Men",)),
    ("Allen Solly", 1, ("Men", "Women")),
    ("Van Heusen", 1, ("Men", "Women")),
    ("U.S. Polo Assn.", 1, ("Men", "Women")),
    ("Only", 1, ("Women",)),
    ("Vero Moda", 1, ("Women",)),
    ("W for Woman", 1, ("Women",)),
    ("Fabindia", 2, ("Men", "Women", "Unisex")),
    ("Tommy Hilfiger", 2, ("Men", "Women")),
    ("Calvin Klein", 2, ("Men", "Women", "Unisex")),
    ("Marks & Spencer", 2, ("Men", "Women")),
    ("Anouk", 2, ("Women",)),
    ("Blackberrys", 2, ("Men",)),
]

# Base price by (product type, fabric tier), before brand tier and jitter. Chosen
# so the four bands the agent reasons about — value, mid, upper, premium — are
# all genuinely reachable.
BASE_PRICE = {
    ("shirt", 0): 950,
    ("shirt", 1): 1850,
    ("shirt", 2): 3600,
    ("tshirt", 0): 600,
    ("tshirt", 1): 1250,
    ("tshirt", 2): 2400,
}
BRAND_TIER_MULTIPLIER = {0: 0.85, 1: 1.15, 2: 1.75}

GENDER_SPLIT = [("Men", 0.40), ("Women", 0.40), ("Unisex", 0.20)]
TYPE_SPLIT = [("shirt", 0.535), ("tshirt", 0.465)]


def _weighted(rng: random.Random, options: list[tuple[Any, int]]) -> Any:
    values = [value for value, _ in options]
    weights = [weight for _, weight in options]
    return rng.choices(values, weights=weights, k=1)[0]


def _price(rng: random.Random, kind: str, fabric_tier: int, brand_tier: int) -> int:
    """A price that reflects fabric, brand and a little real-world noise.

    Ends in 9 because every price in Indian retail does, and a catalogue of
    round numbers reads as synthetic at a glance.
    """
    base = BASE_PRICE[(kind, fabric_tier)] * BRAND_TIER_MULTIPLIER[brand_tier]
    jittered = base * rng.uniform(0.78, 1.32)
    rounded = int(round(jittered / 50.0) * 50)
    return max(299, rounded - 1)


def _swatch(color_name: str, hex_code: str, subtitle: str) -> str:
    """An inline SVG tile in the product's real colour.

    A data URI rather than a hosted placeholder on purpose: the demo then has no
    network dependency for images, nothing to rate-limit, and the tile is
    guaranteed to be the colour the product claims to be — which a stock photo
    of a different shirt would not be.

    4:3 to match the card's aspect ratio, so nothing gets cropped.
    """
    red, green, blue = (int(hex_code[i : i + 2], 16) for i in (1, 3, 5))
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    ink = "#101010" if luminance > 0.62 else "#ffffff"
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='480' height='360'>"
        f"<rect width='480' height='360' fill='{hex_code}'/>"
        f"<circle cx='402' cy='58' r='150' fill='{ink}' opacity='0.05'/>"
        f"<rect y='352' width='480' height='8' fill='{ink}' opacity='0.10'/>"
        f"<text x='36' y='296' font-family='Helvetica,Arial,sans-serif' font-size='34' "
        f"font-weight='600' fill='{ink}' opacity='0.92'>{color_name}</text>"
        f"<text x='36' y='326' font-family='Helvetica,Arial,sans-serif' font-size='17' "
        f"fill='{ink}' opacity='0.62'>{subtitle}</text>"
        "</svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _build_name(pattern: str, fit: str, fabric: str, detail: str) -> str:
    """Assemble a product name the way a real listing reads.

    Qualifiers first, product type last — which matters, because the search
    identifies what a product IS from the head noun. "Shirt" and "T-shirt" must
    stay distinguishable, so `detail` always ends in one of them.
    """
    parts = [pattern, fit, fabric, detail]
    return " ".join(part for part in parts if part)


def generate(count: int, seed: int) -> list[dict[str, Any]]:
    """Build the catalogue, holding the composition quotas as it goes."""
    rng = random.Random(seed)

    type_targets = {kind: int(round(count * share)) for kind, share in TYPE_SPLIT}
    gender_targets = {gender: int(round(count * share)) for gender, share in GENDER_SPLIT}

    products: list[dict[str, Any]] = []
    used_names: set[str] = set()
    color_cycle = [(name, hex_code) for name, hex_code, weight in COLORS for _ in range(weight)]
    rng.shuffle(color_cycle)
    color_at = 0

    # Filled in a fixed order (all shirts, then all T-shirts) with genders
    # interleaved, so a quota shortfall can never silently land entirely on one
    # gender or one product type.
    plan: list[tuple[str, str]] = []
    for kind, kind_target in type_targets.items():
        genders = []
        for gender, gender_target in gender_targets.items():
            genders += [gender] * max(1, round(gender_target * kind_target / count))
        for index in range(kind_target):
            plan.append((kind, genders[index % len(genders)]))
    rng.shuffle(plan)

    for index, (kind, gender) in enumerate(plan, start=1):
        fabric_choices = [
            ((entry["name"], entry["tier"]), entry[kind])
            for entry in FABRICS
            if entry[kind] > 0 and (entry["genders"] is None or gender in entry["genders"])
        ]
        fabric, fabric_tier = _weighted(rng, fabric_choices)

        # Brand tier tracks fabric tier, with one step of slack either way so the
        # catalogue isn't perfectly stratified.
        wanted_tier = min(2, max(0, fabric_tier + rng.choice((-1, 0, 0, 1))))
        candidates = [b for b in BRANDS if b[1] == wanted_tier and gender in b[2]]
        if not candidates:
            candidates = [b for b in BRANDS if gender in b[2]]
        brand, brand_tier, _ = rng.choice(candidates)

        # Colours are dealt round-robin from a shuffled deck rather than sampled,
        # which is what guarantees every colour family is actually present
        # instead of merely probable.
        color_name, hex_code = color_cycle[color_at % len(color_cycle)]
        color_at += 1

        pattern = _weighted(rng, PATTERNS_SHIRT if kind == "shirt" else PATTERNS_TSHIRT)
        fit = _weighted(rng, FITS_SHIRT if kind == "shirt" else FITS_TSHIRT)
        details = (DETAILS_SHIRT if kind == "shirt" else DETAILS_TSHIRT)[gender]
        detail = rng.choice(details)

        name = _build_name(pattern, fit, fabric, detail)
        attempts = 0
        while name in used_names and attempts < 12:
            detail = rng.choice(details)
            pattern = _weighted(rng, PATTERNS_SHIRT if kind == "shirt" else PATTERNS_TSHIRT)
            fit = _weighted(rng, FITS_SHIRT if kind == "shirt" else FITS_TSHIRT)
            name = _build_name(pattern, fit, fabric, detail)
            attempts += 1
        used_names.add(name)

        price = _price(rng, kind, fabric_tier, brand_tier)
        description = f"{color_name} {name} by {brand}"
        tags = sorted(tokenize(f"{name} {brand} {color_name} {gender}") | {gender.lower()})

        products.append(
            {
                "id": f"prod_{index:04d}",
                "name": name,
                "brand": brand,
                "gender": gender,
                "price": price,
                "description": description,
                "color": color_name,
                "tags": tags,
                "image": _swatch(color_name, hex_code, f"{fabric} · {gender}"),
            }
        )

    return products


def audit(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure what was actually produced, using the search's own tokeniser.

    Deliberately measured through `tokenize` rather than from the generator's
    own variables: the question that matters is not "what did I intend" but
    "what will the search be able to find".
    """
    kinds: Counter = Counter()
    fabrics: Counter = Counter()
    families: Counter = Counter()
    genders: Counter = Counter()
    brands: Counter = Counter()
    bands: Counter = Counter()
    untyped: list[str] = []
    no_color: list[str] = []

    for product in products:
        tokens = tokenize(f"{product['name']} {product['description']}")
        garments = tokens & GARMENT_TOKENS
        if "tshirt" in garments:
            kinds["tshirt"] += 1
        elif "shirt" in garments:
            kinds["shirt"] += 1
        else:
            untyped.append(product["name"])

        found = tokens & MATERIAL_TOKENS
        for fabric in found:
            fabrics[fabric] += 1
        if not found:
            fabrics["(none)"] += 1

        family = canonical_color(product["color"])
        if family:
            families[family] += 1
        else:
            no_color.append(product["color"])

        genders[product["gender"]] += 1
        brands[product["brand"]] += 1

        price = product["price"]
        band = (
            "value <₹900" if price < 900
            else "mid ₹900-1999" if price < 2000
            else "upper ₹2000-3499" if price < 3500
            else "premium ₹3500+"
        )
        bands[band] += 1

    return {
        "total": len(products),
        "kinds": dict(kinds),
        "genders": dict(genders.most_common()),
        "colour_families": dict(families.most_common()),
        "fabrics": dict(fabrics.most_common()),
        "price_bands": dict(bands.most_common()),
        "brands": len(brands),
        "brand_max_share": brands.most_common(1)[0] if brands else None,
        "untyped": untyped,
        "unrecognised_colours": sorted(set(no_color)),
        "duplicate_names": [n for n, c in Counter(p["name"] for p in products).items() if c > 1],
    }


def report(summary: dict[str, Any]) -> None:
    for key in ("total", "kinds", "genders", "price_bands", "colour_families", "fabrics"):
        logger.info(f"{key}: {summary[key]}")
    logger.info(f"brands: {summary['brands']} (largest: {summary['brand_max_share']})")
    if summary["untyped"]:
        logger.info(f"⚠ products with no recognised type: {summary['untyped'][:5]}")
    if summary["unrecognised_colours"]:
        logger.info(f"⚠ colours the search can't group: {summary['unrecognised_colours']}")
    if summary["duplicate_names"]:
        logger.info(f"⚠ duplicate names: {summary['duplicate_names'][:5]}")


def verify(summary: dict[str, Any]) -> list[str]:
    """The guarantees this catalogue exists to provide, checked.

    A catalogue that quietly loses a colour family or drops to two linen shirts
    reintroduces exactly the dead-end the old one had, and it would not be
    obvious until a demo went sideways.
    """
    problems: list[str] = []

    if summary["untyped"]:
        problems.append(f"{len(summary['untyped'])} product(s) have no recognised product type")
    if summary["unrecognised_colours"]:
        problems.append(f"colours not in any family: {summary['unrecognised_colours']}")
    if summary["duplicate_names"]:
        problems.append(f"{len(summary['duplicate_names'])} duplicate product name(s)")

    for kind in ("shirt", "tshirt"):
        if summary["kinds"].get(kind, 0) < 100:
            problems.append(f"only {summary['kinds'].get(kind, 0)} {kind}s — need at least 100")

    if len(summary["colour_families"]) < 10:
        problems.append(f"only {len(summary['colour_families'])} colour families")
    thin = {f: n for f, n in summary["colour_families"].items() if n < 8}
    if thin:
        problems.append(f"colour families too thin to filter on: {thin}")

    linen = summary["fabrics"].get("linen", 0)
    if linen < 25:
        problems.append(f"only {linen} linen products — 'preferably linen' needs a real answer")
    if summary["fabrics"].get("(none)", 0):
        problems.append(f"{summary['fabrics']['(none)']} product(s) record no fabric")

    for band, n in summary["price_bands"].items():
        if n < 25:
            problems.append(f"price band '{band}' has only {n} products")

    if summary["brands"] < 12:
        problems.append(f"only {summary['brands']} brands")
    if summary["brand_max_share"] and summary["brand_max_share"][1] > len(str(summary["total"])) * 20:
        problems.append(f"one brand dominates: {summary['brand_max_share']}")

    return problems


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=300, help="How many products to generate")
    parser.add_argument("--seed", type=int, default=20260828, help="Seed, so builds are reproducible")
    parser.add_argument("--output", default="catalog.json", help="Where to write the catalogue")
    parser.add_argument("--report", action="store_true", help="Show composition without writing")
    args = parser.parse_args(argv)

    products = generate(args.count, args.seed)
    summary = audit(products)
    report(summary)

    problems = verify(summary)
    if problems:
        logger.error("\nComposition check FAILED:")
        for problem in problems:
            logger.error(f"  - {problem}")
        return 1

    logger.info("\nComposition check passed.")

    if args.report:
        logger.info("--report given; nothing written.")
        return 0

    with open(args.output, "w") as handle:
        json.dump(products, handle, indent=1)
    logger.info(f"Wrote {len(products)} products to {args.output}")
    logger.info("Restart the Seller Agent to re-index ChromaDB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
