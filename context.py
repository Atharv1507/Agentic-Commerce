"""Conversation-scoped constraint state: what carries forward, and what must not.

Three separate kinds of state used to be conflated into one durable, global
`preferences` blob, which is why a fabric mentioned once outlived the request
it belonged to:

1. USER DETAILS (email, phone, address, gender) — durable, account-level,
   editable in Settings. Never a search filter, except gender.
2. DURABLE PREFERENCES (colours, brands, style, spend tier) — account-level
   taste. A soft hint, never a hard filter, and always overridable.
3. SEARCH CONSTRAINTS for the thing being shopped for RIGHT NOW (fabric,
   colour, budget for *this* garment) — belong to one conversation and one
   product type, and must die when either changes.

The old build stored (3) as (2) and replayed it into every turn with "apply
these even if not repeated", so "linen shirts" became a standing filter: the
next search for trousers still demanded linen and returned nothing.

Everything here is deterministic and runs in code, not in the prompt. The model
is free to carry constraints forward — it's told to — but the carry-forward is
then checked against what the shopper actually said this turn, so a constraint
can only survive a change of subject if they repeated it.
"""

import logging
import re
from typing import Any, Optional

from negotiation import _TOKEN_TO_COLOR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fabrics a shopper names explicitly. Mirrors the seller's MATERIAL_TOKENS —
# kept local because this check must not depend on the seller service.
MATERIAL_TOKENS = frozenset(
    """
    cotton linen silk wool denim leather polyester rayon viscose chiffon georgette
    satin velvet chambray corduroy khadi jute nylon lycra spandex cashmere tweed
    suede canvas mesh fleece jersey crepe organza lace net
    """.split()
)

# The head noun that decides WHAT is being shopped for. Two searches share a
# subject only if these overlap, so "shirt" → "trouser" is a new subject (drop
# the shirt's constraints) while "shirt" → "grey shirt" is the same one (keep
# them).
SUBJECT_TOKENS = frozenset(
    """
    shirt tshirt top tunic blouse camisole dress nightdress gown saree kurta kurti
    lehenga salwar palazzo dupatta legging tight jean trouser trackpant short
    skirt jumpsuit dungaree blazer jacket coat sweater sweatshirt hoodie cardigan
    bra brief boxer trunk panty robe nightsuit pyjama bedsheet
    shoe sandal slipper flipflop heel flat ballerina boot brogue oxford
    loafer moccasin
    watch belt wallet bag backpack clutch sunglass cap hat scarf stole tie
    sock glove earring necklace bracelet ring
    fragrance deodorant lipstick kajal foundation shampoo cream lotion
    """.split()
)

# Written before the garment gate so "t-shirt" can never be read as "shirt".
COMPOUND_PATTERNS = [
    (re.compile(r"\bt[\s\-]?shirts?\b"), " tshirt "),
    (re.compile(r"\bsweat[\s\-]?shirts?\b"), " sweatshirt "),
    (re.compile(r"\bnight[\s\-]?(dress|suit|wear)s?\b"), r" night\1 "),
    (re.compile(r"\btrack[\s\-]?(pant|suit)s?\b"), r" trackpant "),
    (re.compile(r"\bflip[\s\-]?flops?\b"), " flipflop "),
    (re.compile(r"\bjump[\s\-]?suits?\b"), " jumpsuit "),
]

# Words that name the same subject. Grouping them means a follow-up phrased
# differently ("sneakers" after "shoes") keeps the budget it was given.
SUBJECT_SYNONYMS = {
    "tee": "tshirt",
    "tees": "tshirt",
    "pant": "trouser",
    "pants": "trouser",
    "chino": "trouser",
    "chinos": "trouser",
    "sneaker": "shoe",
    "trainer": "shoe",
    "footwear": "shoe",
    "denims": "jean",
    "frock": "dress",
    "handbag": "bag",
    "purse": "bag",
    "perfume": "fragrance",
    "deo": "deodorant",
    "wristwatch": "watch",
    "spectacle": "sunglass",
    "shades": "sunglass",
    "specs": "sunglass",
}

# "I don't mind", said in the ways people actually say it. Any of these means:
# forget the constraints for this search — mine AND the ones you saved for me —
# and show me what the shop has.
NO_PREFERENCE_PATTERNS = [
    re.compile(p)
    for p in (
        r"\bno (particular |specific |strong |real )?(preference|preferences|prefs)\b",
        r"\bdon'?t (have|got) (any|a) (particular |specific )?preference",
        r"\bno preference\b",
        r"\bdoesn'?t matter\b",
        r"\bdon'?t (really )?(mind|care)\b",
        r"\bany(thing)? (is|works|will do|is fine|goes)\b",
        r"\b(just|simply) show me (what|whatever|some|anything)\b",
        r"\bsurprise me\b",
        r"\bopen to (anything|any)\b",
        r"\bwhatever you (have|got|stock)\b",
        r"\bforget (the|my) (preference|preferences|filters?)\b",
        r"\bignore (the|my) (preference|preferences|filters?)\b",
    )
]

# Constraints that describe the *thing being bought* rather than the shopper.
# These are the ones that must not outlive their subject.
SOFT_CONSTRAINT_KEYS = ("materials", "colors", "brands")
BUDGET_KEYS = ("budget", "budget_min", "budget_max", "budget_flexible", "premium")

# Word-bounded throughout: an unanchored "rs" matched the "rs" inside
# "trousers", so every trousers request looked like it mentioned money and kept
# the previous item's budget.
_BUDGET_HINT = re.compile(
    r"(\d|₹|\b(k|budget|cheap|affordable|afford|premium|luxury|luxurious|expensive|"
    r"spend|under|below|above|around|between|price|priced|cost|costs|rupees?|rs|inr|"
    r"high[\s\-]?end|top[\s\-]?of[\s\-]?the[\s\-]?range)\b)",
    re.IGNORECASE,
)

_WORD = re.compile(r"[a-z0-9]+")


# "-es" is only a two-letter plural after a sibilant ("dresses", "watches").
# Applying it everywhere turned "shoes" into "sho", so a shoe search shared no
# subject token with a sneaker search.
_SIBILANT_ES = ("ses", "xes", "zes", "ches", "shes")


def _singular(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(_SIBILANT_ES):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> set[str]:
    """Lowercase word tokens, singularised, with compounds folded first."""
    lowered = (text or "").lower()
    for pattern, replacement in COMPOUND_PATTERNS:
        lowered = pattern.sub(replacement, lowered)
    tokens = set()
    for raw in _WORD.findall(lowered):
        mapped = SUBJECT_SYNONYMS.get(raw, raw)
        singular = _singular(mapped)
        # Synonyms are listed in whichever form reads naturally, so map again
        # after singularising — otherwise "sneakers" reduces to "sneaker" and
        # never reaches "shoe".
        tokens.add(mapped)
        tokens.add(singular)
        tokens.add(SUBJECT_SYNONYMS.get(singular, singular))
    return tokens


def subject_tokens(query: str) -> set[str]:
    """The product-type tokens a query is about.

    Falls back to nothing when the query names no recognised product type — an
    unrecognisable subject is treated as "unknown", which never matches a
    previous subject and so never inherits its constraints. Losing a carried
    constraint is a much cheaper mistake than silently applying a stale one.
    """
    return {t for t in tokenize(query) if t in SUBJECT_TOKENS}


def expresses_no_preference(text: str) -> bool:
    """True when the shopper has just said they don't have a preference."""
    lowered = (text or "").lower()
    return any(pattern.search(lowered) for pattern in NO_PREFERENCE_PATTERNS)


def mentions_value(text: str, value: str) -> bool:
    """Did this turn's message actually name this constraint value?

    Token-based rather than substring, so "linen" doesn't match "linens" only
    by luck and "CASIO" matches "casio". Multi-word values ("dark grey", "Levi
    Strauss") count as mentioned when any of their meaningful words appear.
    """
    if not value:
        return False
    said = tokenize(text)
    wanted = {t for t in tokenize(str(value)) if len(t) > 2}
    return bool(wanted & said)


def mentions_budget(text: str) -> bool:
    """Did this turn's message say anything about money at all?"""
    return bool(_BUDGET_HINT.search(text or ""))


def _implied_by_text(text: str, keys: tuple[str, ...]) -> dict[str, bool]:
    """Which soft-constraint kinds this message plausibly names at all."""
    said = tokenize(text)
    return {
        "materials": bool(said & MATERIAL_TOKENS),
        "colors": bool(said & set(_TOKEN_TO_COLOR)),
        # Brands can't be enumerated locally, so any capitalised-ish token could
        # be one. Treated as "possibly mentioned" and checked per value instead.
        "brands": True,
    }


def normalize_gender(value: Optional[str]) -> Optional[str]:
    """Map a profile/stated gender onto the catalogue's vocabulary.

    The catalogue labels products Men / Women / Unisex; onboarding collects
    Male / Female / Other. "Other" deliberately becomes None — a shopper who
    didn't pick a side should see the whole catalogue, not an arbitrary half.
    """
    lowered = (value or "").strip().lower()
    if lowered in ("male", "man", "men", "m", "mens", "men's", "gents", "boy"):
        return "Men"
    if lowered in ("female", "woman", "women", "f", "womens", "women's", "ladies", "girl"):
        return "Women"
    if lowered in ("unisex", "any", "all"):
        return "Unisex"
    return None


def durable_hints(preferences: dict[str, Any]) -> dict[str, Any]:
    """The subset of saved preferences that may be applied to any search.

    Fabric is absent by design: it is a property of one garment type, not of a
    person, so it is never stored durably (see `PREFERENCE_FIELDS`). Colours,
    brands and spend tier are genuinely about the shopper and travel fine.
    """
    return {k: v for k, v in (preferences or {}).items() if k != "materials" and v}


def scrub_constraints(
    constraints: dict[str, Any],
    thread: dict[str, Any],
    turn_text: str,
) -> tuple[dict[str, Any], list[str]]:
    """Strip constraints that no longer belong to what the shopper is asking for.

    The model assembles the constraint set for each search and is instructed to
    carry context forward, which is right within one subject and wrong across
    two. This is the check on that: a constraint survives a change of subject
    only if this turn's message actually names it.

    Also honours an explicit "no preference" — that clears every taste
    constraint for the search, including saved ones, which is the only way a
    shopper can ask to just see the shelf.

    Args:
        constraints: The tool arguments the model produced (mutated copy).
        thread: The active conversation's state, holding the previous subject.
        turn_text: The shopper's message for this turn.

    Returns:
        (scrubbed constraints, human-readable notes about what was dropped).
    """
    scrubbed = dict(constraints)
    notes: list[str] = []
    query = scrubbed.get("query") or ""

    new_subject = subject_tokens(query)
    previous = set(thread.get("subject_tokens") or [])
    # No recognised subject on either side is treated as a change: unknown
    # subjects must not inherit.
    subject_changed = not new_subject or not previous or not (new_subject & previous)

    if expresses_no_preference(turn_text):
        dropped = {
            key: scrubbed.pop(key)
            for key in (*SOFT_CONSTRAINT_KEYS, "premium")
            if scrubbed.get(key)
        }
        scrubbed["ignore_saved_preferences"] = True
        if dropped:
            notes.append(
                f"The shopper said they have no preference, so these were dropped for this "
                f"search: {_readable(dropped)}. Saved preferences were not applied either."
            )
        else:
            notes.append(
                "The shopper said they have no preference — saved preferences were not "
                "applied to this search."
            )
        _remember_subject(thread, query, new_subject, scrubbed)
        return scrubbed, notes

    if subject_changed and previous:
        implied = _implied_by_text(turn_text, SOFT_CONSTRAINT_KEYS)
        dropped: dict[str, Any] = {}

        for key in SOFT_CONSTRAINT_KEYS:
            values = scrubbed.get(key)
            if not values:
                continue
            if not implied.get(key, True):
                dropped[key] = values
                scrubbed.pop(key)
                continue
            kept = [v for v in values if mentions_value(turn_text, v)]
            if len(kept) != len(values):
                dropped[key] = [v for v in values if v not in kept]
            if kept:
                scrubbed[key] = kept
            else:
                scrubbed.pop(key)

        if not mentions_budget(turn_text):
            for key in BUDGET_KEYS:
                if scrubbed.get(key):
                    dropped[key] = scrubbed.pop(key)

        if dropped:
            previous_subject = thread.get("subject_query") or "the previous item"
            notes.append(
                f"The shopper moved from {previous_subject} to {query} and did not repeat "
                f"these, so they were NOT applied: {_readable(dropped)}. Do not mention "
                f"{previous_subject} or those constraints in your reply, and do not report "
                f"a shortfall about them."
            )
            logger.info(f"Dropped stale constraints on subject change: {dropped}")

    _remember_subject(thread, query, new_subject, scrubbed)
    return scrubbed, notes


def _remember_subject(
    thread: dict[str, Any],
    query: str,
    tokens: set[str],
    constraints: dict[str, Any],
) -> None:
    """Record what this conversation is currently shopping for.

    Only primary searches count. A cross-sell pass deliberately searches for a
    different product type, and letting it move the subject would make the next
    real search look like a change of topic.
    """
    if (constraints.get("purpose") or "primary") != "primary":
        return
    thread["subject_query"] = query
    thread["subject_tokens"] = sorted(tokens)
    thread["subject_constraints"] = {
        key: constraints[key]
        for key in (*SOFT_CONSTRAINT_KEYS, *BUDGET_KEYS)
        if constraints.get(key)
    }


def _readable(dropped: dict[str, Any]) -> str:
    parts = []
    for key, value in dropped.items():
        if isinstance(value, list):
            parts.append(f"{key}: {', '.join(str(v) for v in value)}")
        else:
            parts.append(f"{key}: {value}")
    return "; ".join(parts)
