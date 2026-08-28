"""The product vocabulary: how text becomes comparable tokens.

Split out of `rag.py` so anything that has to speak the catalogue's language can
share one copy. Search uses it to score products against a query; the catalogue
builder (`build_catalog.py`) uses it to read gender, colour, fabric and garment
type out of raw product names. Two copies of these tables would drift, and a
builder that tokenised text differently from the searcher would quietly produce
a catalogue the search can't match.

Pure data and pure functions only — importing this must never touch ChromaDB or
read a catalogue file.
"""

import re
from typing import Optional

# Query words that carry no product signal. Dropping them keeps the lexical
# score honest: "show me some watches" should score as "watch", not as 20%
# matched because "some" happened to appear in a description.
STOPWORDS = frozenset(
    """
    a an the and or but for with without in on at of to from by me my mine i we our you your
    want wants need needs looking look show find get give suggest recommend see
    some something anything someone please could would should can will
    under below above over around near about between upto up
    like similar prefer preferably rather more less very really quite just also
    that this those these there here it its is are was were be been being am
    budget price priced cost costs costing rs inr rupee rupees k thousand
    option options product products item items thing things one ones
    good nice best better great top new
    """.split()
)

# Collapsed BEFORE tokenising, because splitting on non-alphanumerics turns
# "T-shirt" into {t, shirt} — which is how a search for shirts came back full
# of T-shirts and a "T-shirt Bra". These garments have to survive as one token.
COMPOUND_PATTERNS = [
    (re.compile(r"\bt[\s\-]?shirts?\b"), " tshirt "),
    (re.compile(r"\bsweat[\s\-]?shirts?\b"), " sweatshirt "),
    (re.compile(r"\bnight[\s\-]?(dress|suit|wear)s?\b"), r" night\1 "),
    (re.compile(r"\btrack[\s\-]?(pant|suit)s?\b"), r" track\1 "),
    (re.compile(r"\bflip[\s\-]?flops?\b"), " flipflop "),
    (re.compile(r"\bjump[\s\-]?suits?\b"), " jumpsuit "),
]

# The head noun that decides what KIND of thing a product is. A query naming one
# of these must only match products of that kind: "shirt" must not return a
# saree because both mention linen, and must not return a T-shirt either.
GARMENT_TOKENS = frozenset(
    """
    shirt tshirt top tunic blouse camisole dress nightdress gown saree kurta kurti
    lehenga salwar palazzo dupatta legging tight jean trouser pant trackpant short
    skirt jumpsuit dungaree blazer jacket coat sweater sweatshirt hoodie cardigan
    bra brief boxer trunk panty robe nightsuit pyjama
    shoe sneaker sandal slipper flipflop heel flat ballerina boot brogue oxford
    loafer moccasin
    watch belt wallet bag backpack clutch purse sunglass cap hat scarf stole tie
    sock glove earring necklace bracelet ring
    fragrance perfume deodorant lipstick kajal foundation shampoo cream lotion
    """.split()
)

# What an item is FOR, within its category. The garment gate above only fixes
# the head noun, which is why "running shoes" came back full of formal oxfords
# and trekking boots: they are all shoes, and a well-priced oxford outscored a
# real running shoe on every remaining signal. Purpose is not a near miss —
# a formal shoe is the wrong product for a running ask, at any price — so
# naming one family rules the others out rather than merely demoting them.
#
# Deliberately qualifiers, not head nouns: "loafer" and "oxford" stay out so a
# bare "loafers" query doesn't drop the formal ones. Products are recognised
# through their catalogue tags (sports / casual / formal / heels / flats), which
# is where this signal actually lives.
STYLE_FAMILIES = {
    "athletic": """
        running jogging sport training gym workout walking trekking hiking
        athletic marathon tennis badminton basketball football cricket cycling
        """.split(),
    "formal": "formal semiformal".split(),
    "casual": ["casual"],
    "open": "sandal slipper flipflop thong floater clog slide".split(),
    "dressy": "heel wedge pump stiletto peeptoe ballerina bellie flat".split(),
}

_TOKEN_TO_STYLE: dict[str, str] = {
    token: family for family, tokens in STYLE_FAMILIES.items() for token in tokens
}

# Fabrics a shopper will name explicitly ("preferably linen").
MATERIAL_TOKENS = frozenset(
    """
    cotton linen silk wool denim leather polyester rayon viscose chiffon georgette
    satin velvet chambray corduroy khadi jute nylon lycra spandex cashmere tweed
    suede canvas mesh fleece jersey crepe organza lace net
    """.split()
)

# Applied to both query and product tokens so the two sides meet in the middle.
# "analogue" vs "analog" is the exact miss that made a CASIO "Analog Watch"
# rank below unrelated items for an "analogue watch" query.
CANONICAL_TOKENS = {
    "analog": "analogue",
    "gray": "grey",
    "colour": "color",
    "coloured": "color",
    "tshirt": "tshirt",
    "tee": "tshirt",
    "sneaker": "shoe",
    "trainer": "shoe",
    "footwear": "shoe",
    "spectacle": "sunglass",
    "shade": "sunglass",
    "wristwatch": "watch",
    "denim": "jean",
    "frock": "dress",
    "handbag": "bag",
    "purse": "bag",
    "perfume": "fragrance",
    "deo": "deodorant",
}

# Colours the catalogue spells a dozen ways. Each group's key is the canonical
# name; membership is what a request for that colour will accept.
COLOR_GROUPS = {
    "grey": {"grey", "gray", "charcoal", "slate", "graphite", "gunmetal", "steel"},
    "silver": {"silver", "chrome", "metallic", "platinum"},
    "black": {"black", "jet", "onyx", "ebony"},
    "white": {"white", "ivory", "cream", "off white", "offwhite"},
    "blue": {"blue", "navy", "teal", "turquoise", "cobalt", "indigo", "denim"},
    "green": {"green", "olive", "mint", "sage", "emerald"},
    "red": {"red", "maroon", "burgundy", "wine", "crimson", "rust"},
    "pink": {"pink", "rose", "blush", "fuchsia", "magenta"},
    "brown": {"brown", "tan", "beige", "khaki", "camel", "coffee", "taupe"},
    "yellow": {"yellow", "mustard", "gold", "golden", "lemon"},
    "purple": {"purple", "lavender", "violet", "lilac", "mauve"},
    "orange": {"orange", "peach", "coral", "apricot"},
}

# Colours a shopper will usually accept as "close enough" — a grey ask should
# rank a silver watch above a yellow one, but still below an actual grey.
ADJACENT_COLORS = {
    ("grey", "silver"),
    ("grey", "black"),
    ("brown", "yellow"),
    ("pink", "red"),
    ("purple", "pink"),
}

_TOKEN_TO_COLOR: dict[str, str] = {
    token: canonical for canonical, tokens in COLOR_GROUPS.items() for token in tokens
}

_ADJACENCY: dict[str, set[str]] = {}
for _a, _b in ADJACENT_COLORS:
    _ADJACENCY.setdefault(_a, set()).add(_b)
    _ADJACENCY.setdefault(_b, set()).add(_a)

def _singular(token: str) -> str:
    """Crude English singulariser — enough to make 'watches' meet 'watch'."""
    if len(token) <= 3:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("ches", "shes", "xes", "ses")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> set[str]:
    """Split text into canonical, stopword-free content tokens."""
    lowered = (text or "").lower()
    for pattern, replacement in COMPOUND_PATTERNS:
        lowered = pattern.sub(replacement, lowered)
    raw = re.findall(r"[a-z0-9]+", lowered)
    tokens = set()
    for token in raw:
        if token.isdigit() or token in STOPWORDS or len(token) < 2:
            continue
        token = _singular(token)
        token = CANONICAL_TOKENS.get(token, token)
        tokens.add(token)
    return tokens


def style_families(tokens: set[str]) -> set[str]:
    """Which purpose families a token set belongs to (empty = unlabelled)."""
    return {_TOKEN_TO_STYLE[t] for t in tokens if t in _TOKEN_TO_STYLE}


def canonical_color(value: str) -> Optional[str]:
    """Map a free-text colour onto its canonical group name, if any."""
    for token in re.findall(r"[a-z]+", (value or "").lower()):
        if token in _TOKEN_TO_COLOR:
            return _TOKEN_TO_COLOR[token]
    return None


# The size rail, smallest first. Mirrors generate_catalog.SIZES; kept here too
# because everything downstream of the catalogue file needs the canonical order
# and must not import the build script to get it.
SIZES = ("XS", "S", "M", "L", "XL", "XXL")

# Every way a shopper or another agent might name a size. "Large" and "l" and
# "size L" all have to land on the same key as the catalogue's, or a perfectly
# stocked product looks out of stock.
_SIZE_ALIASES = {
    "xs": "XS", "extrasmall": "XS", "extra small": "XS", "xsmall": "XS",
    "s": "S", "small": "S",
    "m": "M", "medium": "M", "med": "M",
    "l": "L", "large": "L", "lrg": "L",
    "xl": "XL", "extralarge": "XL", "extra large": "XL", "xlarge": "XL",
    "xxl": "XXL", "2xl": "XXL", "double xl": "XXL", "doublexl": "XXL",
    "xxlarge": "XXL", "extra extra large": "XXL",
}


def canonical_size(value: Optional[str]) -> Optional[str]:
    """Map any spelling of a size onto the catalogue's key, or None.

    None means "not a size I recognise" — the callers treat that as no size
    filter at all, which shows the shopper everything rather than silently
    filtering on a guess.
    """
    if not value:
        return None
    cleaned = str(value).strip().lower().replace("-", " ")
    cleaned = re.sub(r"\bsizes?\b", "", cleaned).strip()
    if cleaned in _SIZE_ALIASES:
        return _SIZE_ALIASES[cleaned]
    return _SIZE_ALIASES.get(cleaned.replace(" ", ""))
