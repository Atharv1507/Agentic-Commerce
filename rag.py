import json
import logging
import re
from typing import Any, Optional

import chromadb

from vocab import (
    GARMENT_TOKENS,
    MATERIAL_TOKENS,
    SIZES,
    _ADJACENCY,
    canonical_color,
    canonical_size,
    style_families,
    tokenize,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = chromadb.Client()
collection = client.get_or_create_collection(name="products")

# Relative pull of each ranking signal. Weights are renormalised over whichever
# signals are actually active for a given call, so a query with no colour
# preference doesn't quietly hand 12% of the score to a constant.
W_SEMANTIC = 0.32
W_LEXICAL = 0.22
W_BUDGET = 0.20
W_STYLE = 0.18
W_COLOR = 0.11
W_MATERIAL = 0.09
W_BRAND = 0.06

# Without this a single brand can take every slot, which reads as a broken
# search even when each individual hit is reasonable.
MAX_PER_BRAND = 2

# id -> product dict, kept alongside Chroma so lexical scoring and brand/colour
# checks read real Python values instead of round-tripping through metadata.
_catalog: dict[str, dict[str, Any]] = {}
_product_tokens: dict[str, set[str]] = {}
_product_styles: dict[str, set[str]] = {}




def _normalize_size_map(raw: Any) -> dict[str, int]:
    """Coerce a product's size map onto the canonical rail, in ladder order.

    Missing sizes become an explicit 0. A product that records no sizes at all
    is treated as stocked in every size — that keeps a hand-written or legacy
    catalogue entry sellable instead of silently vanishing from every search
    the moment size filtering is switched on.
    """
    if not raw:
        return {size: 1 for size in SIZES}

    counts: dict[str, int] = {size: 0 for size in SIZES}
    for key, value in raw.items():
        canonical = canonical_size(key)
        if not canonical:
            continue
        try:
            counts[canonical] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return counts


def available_sizes(product: dict[str, Any]) -> list[str]:
    """Which sizes of this product can actually be bought right now."""
    sizes = product.get("sizes") or {}
    return [size for size in SIZES if sizes.get(size, 0) > 0]


def load_catalog() -> int:
    """Load products from catalog.json into ChromaDB and the in-memory index.

    Returns:
        Number of products loaded.
    """
    with open("catalog.json", "r") as f:
        products = json.load(f)

    documents = []
    for p in products:
        # Name and brand carry most of the signal but are short, so they'd be
        # drowned out by a long description in the embedding. Repeating them
        # weights them up without needing a custom embedding function.
        searchable = " ".join(
            [
                p["name"],
                p["name"],
                p["brand"],
                p["color"],
                p["gender"],
                p["description"],
                " ".join(p.get("tags", [])),
            ]
        )
        documents.append(searchable)

        # Normalised once here rather than at every read: a catalogue built by
        # hand can spell sizes any way it likes, and every downstream check
        # ("do you have this in large?") compares against the canonical key.
        p["sizes"] = _normalize_size_map(p.get("sizes"))

        _catalog[p["id"]] = p
        tokens = tokenize(searchable)
        _product_tokens[p["id"]] = tokens
        _product_styles[p["id"]] = style_families(tokens)

    # upsert, not add: the collection is fetched with get_or_create, so a reload
    # (or a reimport under the dev server's reloader) must not trip over IDs
    # that are already there.
    collection.upsert(
        ids=[p["id"] for p in products],
        documents=documents,
        metadatas=[
            {
                "name": p["name"],
                "brand": p["brand"],
                "price": p["price"],
                "color": p["color"],
                "gender": p["gender"],
                "image": p["image"],
                "description": p["description"],
            }
            for p in products
        ],
    )

    logger.info(f"Loaded {len(products)} products into ChromaDB")
    return len(products)


load_catalog()


def _budget_score(
    price: int, target_price: Optional[int], max_price: Optional[int]
) -> Optional[float]:
    """Score how well a price uses the shopper's stated budget.

    A ₹10,000 budget means "spend roughly ₹10,000" far more often than it means
    "anything at all, so long as it's cheaper" — ranking purely on the ceiling
    is what surfaced ₹1,239 watches for a ₹10k ask. Returns None when no budget
    was given so the caller can drop this signal from the weighting entirely.
    """
    if target_price:
        return max(0.0, 1.0 - abs(price - target_price) / target_price)
    if max_price:
        return min(1.0, price / max_price)
    return None


def _color_score(product_color: str, wanted: list[str]) -> float:
    """1.0 for an exact colour-group hit, 0.5 for an adjacent shade, else 0."""
    actual = canonical_color(product_color)
    if not actual:
        return 0.0
    wanted_groups = {canonical_color(c) or c.lower() for c in wanted}
    if actual in wanted_groups:
        return 1.0
    if _ADJACENCY.get(actual, set()) & wanted_groups:
        return 0.5
    return 0.0


def _material_score(product_tokens: set[str], wanted: list[str]) -> float:
    """1.0 when the product is made of a requested fabric, else 0."""
    wanted_tokens = {t for w in wanted for t in tokenize(w)} & MATERIAL_TOKENS
    return 1.0 if wanted_tokens & product_tokens else 0.0


def _brand_score(product_brand: str, wanted: list[str]) -> float:
    """1.0 for a brand the shopper named, else 0 — matched loosely on substring.

    "like Casio" should reward "CASIO" without the caller having to know the
    catalogue's exact casing or full brand string.
    """
    actual = (product_brand or "").lower()
    for brand in wanted:
        brand = brand.strip().lower()
        if brand and (brand in actual or actual in brand):
            return 1.0
    return 0.0


def _gender_ok(product_gender: str, wanted: Optional[str]) -> bool:
    if not wanted:
        return True
    actual = (product_gender or "").lower()
    return actual == wanted.strip().lower() or actual == "unisex"


def search_catalog(
    query: str,
    top_k: int = 5,
    max_price: Optional[int] = None,
    min_price: Optional[int] = None,
    target_price: Optional[int] = None,
    gender: Optional[str] = None,
    colors: Optional[list[str]] = None,
    materials: Optional[list[str]] = None,
    brands: Optional[list[str]] = None,
    size: Optional[str] = None,
    exclude_ids: Optional[list[str]] = None,
    require_keyword_match: bool = True,
) -> list[dict]:
    """Search the catalogue with hybrid semantic + lexical + constraint ranking.

    Price, gender, size, exclusions, product kind and product purpose are hard
    filters; semantics, keywords, budget fit, colour and brand are blended into
    a score that decides ordering. Purpose is a filter, not a preference: a
    formal shoe is not a cheap running shoe, so name the use in `query`
    ("running shoes", not "shoes") and the wrong families drop out.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return.
        max_price: Hard ceiling in INR.
        min_price: Hard floor in INR — use it to keep a "premium" ask off the
            bargain shelf.
        target_price: The price to rank *towards*. Usually the shopper's stated
            budget, or slightly under it.
        gender: Gender filter (Men, Women, Unisex). Unisex always passes.
        colors: Preferred colours, matched by colour family.
        brands: Preferred brands, matched loosely.
        size: Hard filter — only products with stock in this size come back.
            A shopper who wears L has no use for a shirt that only exists in S,
            so this is a filter rather than a ranking signal. An unrecognised
            value is ignored rather than guessed at.
        exclude_ids: Product IDs to leave out — already shown to this shopper.
        require_keyword_match: Drop products that share no content word with the
            query. Nearest-neighbour search always returns *something*, so
            without this a query for "watch strap" happily comes back with yoga
            tights. Returning nothing is the honest answer when the catalogue
            has nothing.

    Returns:
        List of matching products, best first, each with a `relevance` score.
    """
    try:
        colors = [c for c in (colors or []) if c]
        materials = [m for m in (materials or []) if m]
        brands = [b for b in (brands or []) if b]
        wanted_size = canonical_size(size)
        excluded = set(exclude_ids or [])

        # The catalogue is small enough to rank end to end, which beats
        # top-N-then-filter: constraints get applied to every product rather
        # than to whichever handful the embedding happened to rank first.
        total = collection.count()
        results = collection.query(query_texts=[query], n_results=total)

        ids = results["ids"][0]
        distances = results["distances"][0]
        if not ids:
            logger.info(f"No results for query: {query}")
            return []

        query_tokens = tokenize(query)
        # Material words asked for in the query itself count as material
        # preferences too, so "linen shirt" doesn't need the caller to also
        # remember to fill in `materials`.
        query_materials = query_tokens & MATERIAL_TOKENS
        if query_materials:
            materials = list({*materials, *query_materials})
        # The kind of thing being asked for. Everything else in the query
        # (fabric, style, occasion) only influences ranking.
        query_garments = query_tokens & GARMENT_TOKENS
        # What the shopper wants the thing FOR. Hard-filters incompatible
        # purposes below — "running shoes" must not return formal oxfords.
        query_styles = style_families(query_tokens)

        # Normalise similarity across this result set so the semantic term
        # occupies the same 0..1 range as every other signal regardless of the
        # distance metric's absolute scale.
        sims = [1.0 / (1.0 + d) for d in distances]
        lo, hi = min(sims), max(sims)
        span = (hi - lo) or 1.0

        active_weights = {"semantic": W_SEMANTIC, "lexical": W_LEXICAL}
        if target_price or max_price:
            active_weights["budget"] = W_BUDGET
        if query_styles:
            active_weights["style"] = W_STYLE
        if colors:
            active_weights["color"] = W_COLOR
        if materials:
            active_weights["material"] = W_MATERIAL
        if brands:
            active_weights["brand"] = W_BRAND
        weight_total = sum(active_weights.values())

        scored: list[tuple[float, dict[str, Any]]] = []
        for pid, sim in zip(ids, sims):
            if pid in excluded:
                continue
            product = _catalog.get(pid)
            if not product:
                continue

            price = product["price"]
            if max_price and price > max_price:
                continue
            if min_price and price < min_price:
                continue
            if not _gender_ok(product["gender"], gender):
                continue
            if wanted_size and product["sizes"].get(wanted_size, 0) <= 0:
                continue

            product_tokens = _product_tokens.get(pid, set())

            # Category gate: asking for a shirt must not return a saree that
            # merely shares the word "linen", nor a T-shirt, nor a T-shirt bra.
            if query_garments and not (product_tokens & query_garments):
                continue

            # Purpose gate. An unlabelled product stays in — the catalogue
            # doesn't tag everything, and dropping the untagged would empty
            # whole categories — but it ranks below a confirmed match.
            product_styles = _product_styles.get(pid, set())
            if query_styles and product_styles and not (product_styles & query_styles):
                continue

            overlap = len(query_tokens & product_tokens)
            if require_keyword_match and not query_garments and query_tokens and not overlap:
                continue

            parts = {
                "semantic": (sim - lo) / span,
                "lexical": overlap / len(query_tokens) if query_tokens else 0.0,
            }
            if "budget" in active_weights:
                parts["budget"] = _budget_score(price, target_price, max_price) or 0.0
            if "style" in active_weights:
                parts["style"] = 1.0 if product_styles & query_styles else 0.35
            if "color" in active_weights:
                parts["color"] = _color_score(product["color"], colors)
            if "material" in active_weights:
                parts["material"] = _material_score(product_tokens, materials)
            if "brand" in active_weights:
                parts["brand"] = _brand_score(product["brand"], brands)

            score = sum(active_weights[k] * v for k, v in parts.items()) / weight_total
            scored.append((score, product, parts.get("material", 0.0) > 0))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        products: list[dict] = []
        brand_counts: dict[str, int] = {}
        for score, product, material_ok in scored:
            brand = (product["brand"] or "").lower()
            # A brand cap would fight the shopper if they asked for that brand.
            if not brands and brand_counts.get(brand, 0) >= MAX_PER_BRAND:
                continue
            brand_counts[brand] = brand_counts.get(brand, 0) + 1

            products.append(
                {
                    "id": product["id"],
                    "name": product["name"],
                    "brand": product["brand"],
                    "price": product["price"],
                    "color": product["color"],
                    "gender": product["gender"],
                    "description": product["description"],
                    "image": product["image"],
                    # Both the map and the derived list travel with the product:
                    # the caller needs the counts to say "only 2 left in M" and
                    # the list to check a size without re-deriving it.
                    "sizes": dict(product["sizes"]),
                    "available_sizes": available_sizes(product),
                    "relevance": round(score, 4),
                    # Lets the caller say "none of these are actually linen"
                    # instead of quietly presenting cotton as a match.
                    **({"matches_material": material_ok} if materials else {}),
                }
            )
            if len(products) >= top_k:
                break

        logger.info(
            f"Query '{query}' (budget={target_price or max_price}, colors={colors}, "
            f"brands={brands}, size={wanted_size}, excluded={len(excluded)}) "
            f"returned {len(products)} products"
        )
        return products

    except Exception as e:
        logger.error(f"Search error: {e}")
        return []


def get_product_by_id(product_id: str) -> Optional[dict]:
    """Get a single product by ID.

    Args:
        product_id: The product ID to lookup.

    Returns:
        Product dict if found, None otherwise.
    """
    product = _catalog.get(product_id)
    if not product:
        return None

    return {
        "id": product["id"],
        "name": product["name"],
        "brand": product["brand"],
        "price": product["price"],
        "color": product["color"],
        "gender": product["gender"],
        "description": product["description"],
        "image": product["image"],
        "sizes": dict(product["sizes"]),
        "available_sizes": available_sizes(product),
    }


def catalog_facets(
    query: str, gender: Optional[str] = None, sample: int = 60, full: bool = False
) -> dict[str, Any]:
    """Report which colours, brands, fabrics and price bands actually exist.

    Used to build the clarifying question the shopper sees before a search, so
    the options offered are real stock rather than plausible-sounding guesses.
    Asking "grey, navy or olive?" when the catalogue only has grey wastes the
    shopper's time and produces an unanswerable follow-up search.

    Args:
        query: Natural language description of the product type.
        gender: Optional gender filter.
        sample: How many of the top matches to derive facets from.
        full: When True, answer "what do you stock?" rather than "what should I
            ask?" — every distinct value, untruncated, including facets with a
            single option. The default trims to a form-sized set of choices.

    Returns:
        Dict with `count` and the distinct values available for each facet,
        most common first. Facets with nothing to choose between are omitted
        unless `full`.
    """
    matches = search_catalog(query, top_k=sample, gender=gender)
    if not matches:
        return {"count": 0}

    def ranked(values: list[str]) -> list[str]:
        counts: dict[str, int] = {}
        for value in values:
            if value:
                counts[value] = counts.get(value, 0) + 1
        return [v for v, _ in sorted(counts.items(), key=lambda kv: -kv[1])]

    colors = ranked([canonical_color(p["color"]) or p["color"] for p in matches])
    brands = ranked([p["brand"] for p in matches])

    materials: list[str] = []
    for product in matches:
        materials.extend(sorted(_product_tokens.get(product["id"], set()) & MATERIAL_TOKENS))
    materials = ranked(materials)

    stocked_sizes = [size for size in SIZES if any(size in p["available_sizes"] for p in matches)]

    prices = sorted(p["price"] for p in matches)
    # Terciles, so the bands describe this category's real spread instead of
    # some fixed ladder that might sit entirely above or below it.
    low, mid = prices[len(prices) // 3], prices[2 * len(prices) // 3]
    bands = []
    if prices[0] < low:
        bands.append({"label": f"₹{prices[0]:,} - ₹{low:,}", "min_price": prices[0], "max_price": low})
    if low < mid:
        bands.append({"label": f"₹{low:,} - ₹{mid:,}", "min_price": low, "max_price": mid})
    if mid < prices[-1]:
        # Spelled as a closed range, not "and above" — an open-ended label reads
        # as a ceiling to the agent consuming the answer, which inverts it.
        bands.append({"label": f"₹{mid:,} - ₹{prices[-1]:,}", "min_price": mid, "max_price": prices[-1]})

    facets: dict[str, Any] = {
        "count": len(matches),
        "min_price": prices[0],
        "max_price": prices[-1],
    }
    if full:
        # Answering a direct question ("which brands do you have?"), so a
        # single option is still the honest answer and a cut-off list is not.
        facets["colors"] = colors
        facets["brands"] = brands
        facets["materials"] = materials
        facets["sizes"] = stocked_sizes
        facets["price_bands"] = bands
        return facets

    # A facet with one option isn't a choice — don't ask about it.
    if len(colors) > 1:
        facets["colors"] = colors[:6]
    if len(brands) > 1:
        facets["brands"] = brands[:6]
    if len(materials) > 1:
        facets["materials"] = materials[:5]
    if len(bands) > 1:
        facets["price_bands"] = bands
    # Not offered as a question — size comes from the shopper's profile, not
    # from a form — but reported so the caller can say what the rail holds.
    if stocked_sizes:
        facets["sizes"] = stocked_sizes

    return facets


def price_range(
    query: str, gender: Optional[str] = None, sample: int = 40
) -> dict[str, Any]:
    """Report what a query actually costs in this catalogue.

    Lets the caller tell a shopper "nothing here goes above ₹6,000" instead of
    silently returning cheap items and looking like it ignored the budget.

    Args:
        query: Natural language description of the product type.
        gender: Optional gender filter.
        sample: How many of the top semantic matches to measure.

    Returns:
        Dict with min/max/median price over the matching sample.
    """
    matches = search_catalog(query, top_k=sample, gender=gender)
    prices = sorted(p["price"] for p in matches)
    if not prices:
        return {"count": 0}

    return {
        "count": len(prices),
        "min_price": prices[0],
        "max_price": prices[-1],
        "median_price": prices[len(prices) // 2],
    }
