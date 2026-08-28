from typing import Any

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "find_products",
            "description": (
                "Find products by negotiating with the seller agent on the shopper's "
                "behalf. This runs up to 3 rounds internally: it briefs the seller, "
                "verifies every returned product against the constraints you pass, "
                "pushes back when results don't fit, and excludes anything already "
                "shown to this shopper. It returns ONLY products that passed "
                "verification. Break the shopper's request into explicit constraint "
                "arguments — anything you leave out cannot be enforced."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Product type and style only, e.g. 'analogue wrist watch' or 'floral summer dress'. Never include price, colour or brand here — they have their own arguments.",
                    },
                    "budget": {
                        "type": "integer",
                        "description": "The shopper's budget in INR. '10k' means 10000. Results are ranked towards this figure, so always set it when a budget is stated or known from preferences.",
                    },
                    "budget_min": {
                        "type": "integer",
                        "description": "Lower bound in INR. Use with budget_max when the shopper picked or stated a RANGE (e.g. '₹749 - ₹1,224'). Do not collapse a range into `budget` — that turns the floor into a ceiling.",
                    },
                    "budget_max": {
                        "type": "integer",
                        "description": "Upper bound in INR, paired with budget_min.",
                    },
                    "budget_flexible": {
                        "type": "boolean",
                        "description": "True when the shopper signalled they'd stretch for the right item ('flexible budget', 'happy to pay more'). Only then may results exceed the budget.",
                    },
                    "premium": {
                        "type": "boolean",
                        "description": "True when they asked for premium / high-end / 'something nicer'. Raises the price floor so budget items can't fill the results.",
                    },
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Requested colours, e.g. ['grey']. Matched by colour family.",
                    },
                    "materials": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fabrics the shopper asked for IN THIS REQUEST, e.g. ['linen'] for 'shirts, preferably linen'. Scoped to the product type currently being discussed — when they move to a different product type, drop it unless they say it again. Treated as a strong preference; the result tells you whether anything actually matched so you can be upfront when nothing does.",
                    },
                    "brands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Requested or referenced brands, e.g. ['CASIO'] for 'more like Casio'.",
                    },
                    "gender": {
                        "type": "string",
                        "description": "'Men', 'Women' or 'Unisex'. Only set this when the shopper is shopping for someone else — their own gender comes from their profile and is applied automatically.",
                    },
                    "size": {
                        "type": "string",
                        "description": "XS, S, M, L, XL or XXL. Only set this when the shopper names a DIFFERENT size from their own (shopping for someone else, or 'do you have this in XL?'). Their own size comes from their profile and is applied to every search automatically — do not pass it and do not ask for it.",
                    },
                    "min_results": {
                        "type": "integer",
                        "description": "How many acceptable options to aim for (default 3).",
                    },
                    "include_seen": {
                        "type": "boolean",
                        "description": "By default products already shown to this shopper are hidden so results are always new. Set true ONLY when they're deliberately referring back ('show me that CASIO again', 'what was the second one'), otherwise the search can dead-end.",
                    },
                    "purpose": {
                        "type": "string",
                        "enum": ["primary", "complement"],
                        "description": "'primary' for what the shopper asked for. 'complement' for a cross-sell/upsell pass — these render in a separate 'Goes well with' row.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_preferences",
            "description": (
                "Show the shopper a compact, fully skippable form to narrow a vague "
                "request BEFORE searching. Options are filled in automatically from "
                "what the catalogue actually stocks for this product type, so you do "
                "not supply them. It also drops any facet already known from the "
                "request or saved preferences. Use this once, for a genuinely broad "
                "request like 'some shirts' or 'a dress'. Do NOT use it when the "
                "shopper has already given you enough to search on, when they've "
                "asked to just be shown something, or after a search has run — refine "
                "conversationally instead. After calling it, stop and wait; do not "
                "search in the same turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The garment type only, e.g. 'shirt' or 'dress'. Used to look up which options exist.",
                    },
                    "gender": {"type": "string", "description": "'Men', 'Women' or 'Unisex'"},
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Colours already known — pass them so the form doesn't ask again.",
                    },
                    "brands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Brands already known.",
                    },
                    "materials": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fabrics already known.",
                    },
                    "budget": {
                        "type": "integer",
                        "description": "Budget already known, so the form skips the price question.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_options",
            "description": (
                "Answer a question ABOUT the catalogue rather than searching it: "
                "which brands / colours / fabrics are available for a product type, "
                "and what the price range is. Use this whenever the shopper asks "
                "'which brands do you have?', 'what colours are there?', 'what "
                "fabrics?', 'how much do these cost?' — including when it's scoped "
                "to a style ('for crew neck t-shirts'). It returns the real values "
                "in stock, which you then STATE IN YOUR REPLY as a list. It shows no "
                "product cards, so there is nothing duplicated by naming them. Do "
                "not use find_products for this, and never guess or refuse — call "
                "this and answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The product type, plus a style word if the shopper scoped it, e.g. 'shirt', 't-shirt' or 'crew neck t-shirt'. No price, colour or brand.",
                    },
                    "gender": {
                        "type": "string",
                        "description": "'Men', 'Women' or 'Unisex'. Only when shopping for someone else — otherwise it comes from their profile.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check whether specific products already shown in this conversation are "
                "in stock in a given size. Use this the moment the shopper asks about a "
                "size for a particular item — 'do you have that one in large?', 'is the "
                "blue one available in XL?', 'I want the second one in L'. It is an "
                "exact stock lookup, not a search, and it shows no cards. Defaults to "
                "every product currently on screen and to the shopper's own size. Do "
                "NOT use find_products for this, and never answer a size question from "
                "memory — the same product can be stocked in M and sold out in L."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of the products being asked about, from the cards already shown. Omit to check everything currently on screen.",
                    },
                    "size": {
                        "type": "string",
                        "description": "XS, S, M, L, XL or XXL. Omit to use the shopper's own size from their profile.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a clarifying question. Use when you need more information to formulate a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional quick-reply options for the user",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": (
                "Put products the shopper agreed to into their cart, in the sizes they "
                "asked for. Call this whenever they say to add something — 'add these', "
                "'yes to those', 'the black one in L' — including several items in ONE "
                "call. Only products already shown in this conversation can be added; use "
                "the IDs from SESSION CONTEXT's on-screen listing. A size with no stock is "
                "refused and reported back. Never claim something is in the cart without "
                "calling this and seeing it in the returned cart."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "One entry per product-and-size the shopper wants.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {
                                    "type": "string",
                                    "description": "ID of a product shown in this conversation.",
                                },
                                "size": {
                                    "type": "string",
                                    "description": "XS, S, M, L, XL or XXL. Omit to use the shopper's saved size.",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "Units to add. Defaults to 1.",
                                },
                            },
                            "required": ["product_id"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_cart",
            "description": (
                "Change a cart line the shopper asked you to change: swap its size, set "
                "its quantity, or remove it. Use this when they answer a refused "
                "checkout ('make it M then', 'drop that one', 'just one of those') or "
                "ask for a cart change in conversation. A size with no stock is "
                "rejected, and moving a line onto a size already in the cart merges "
                "them. After changing it, call checkout_cart again if they were "
                "mid-checkout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "ID of the product to change, from SESSION CONTEXT's cart listing.",
                    },
                    "size": {
                        "type": "string",
                        "description": "Which line, when the product is in the cart in more than one size. Omit when there's only one line for it.",
                    },
                    "new_size": {
                        "type": "string",
                        "description": "Size to move the line to: XS, S, M, L, XL or XXL.",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "New unit count for the line. 0 removes it.",
                    },
                    "remove": {
                        "type": "boolean",
                        "description": "True to drop the line entirely.",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkout_cart",
            "description": (
                "Check out the user's current cart. Reads cart contents and buyer "
                "details from session automatically. Call this when the user "
                "confirms they want to pay/checkout. If buyer email, phone, "
                "address, or payment_method are missing, this will return an "
                "error listing what's missing — use ask_user to collect it, then "
                "call update_profile to save it, then call checkout_cart again."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile",
            "description": (
                "Save/update the user's account details (name, phone, address, "
                "payment_method, email, gender) after collecting them "
                "conversationally, e.g. during checkout when info is missing. These "
                "are DETAILS, not preferences — they persist to the shopper's profile "
                "and show up in their settings, so call this every time they give you "
                "one rather than using it for this order only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "User's full name"},
                    "email": {"type": "string", "description": "User's email"},
                    "phone": {"type": "string", "description": "User's phone number"},
                    "address": {"type": "string", "description": "User's delivery address"},
                    "payment_method": {"type": "string", "description": "User's preferred payment method"},
                    "gender": {"type": "string", "description": "User's gender"},
                    "size": {"type": "string", "description": "User's clothing size: XS, S, M, L, XL or XXL. Save it whenever they tell you ('I'm a large') — it then filters every future search."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_preferences",
            "description": (
                "Persist a LASTING taste that is true of the shopper, not of the item "
                "they happen to be searching for right now: 'I always wear black', 'I'm "
                "a Nike person', 'I shop premium', 'I never wear heels'. Saved "
                "preferences apply as a soft default to future searches across every "
                "conversation, so anything one-off must NOT be saved here.\n"
                "Do NOT call this for the constraints of the current request — 'a black "
                "linen shirt under 2k' is a search, not a preference; pass those to "
                "find_products instead. Fabric is never a lasting preference and is "
                "rejected. If unsure whether something is lasting, don't save it. "
                "List values merge with what's already saved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Colours they gravitate to, e.g. ['grey']",
                    },
                    "brands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Brands they like or referenced approvingly, e.g. ['CASIO']",
                    },
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Product categories they shop for, e.g. ['watches']",
                    },
                    "budget_level": {
                        "type": "string",
                        "description": "Typical spend tier, e.g. 'premium', 'mid-range', 'around 10k for watches'",
                    },
                    "style": {
                        "type": "string",
                        "description": "Style leaning, e.g. 'minimal', 'classic', 'sporty'",
                    },
                    "avoid": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Things they've rejected as a rule, e.g. ['digital displays']",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_preferences",
            "description": (
                "Forget saved preferences when the shopper takes one back ('actually I "
                "don't only wear black', 'forget the Nike thing', 'clear my "
                "preferences'). Omit `fields` to clear all of them. Use this rather "
                "than working around a stale preference — a preference the shopper has "
                "disowned must stop affecting results immediately.\n"
                "You do NOT need this for a one-off 'no preference for this search': "
                "saying that in chat already disables saved preferences for that search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["colors", "brands", "categories", "budget_level", "style", "avoid"],
                        },
                        "description": "Which preference fields to forget. Omit to clear everything.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_payment",
            "description": "Verify payment status for an order after user completes payment in frontend.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The Razorpay order ID to verify (starts with 'order_')",
                    },
                    "payment_id": {
                        "type": "string",
                        "description": "The Razorpay payment ID, if the user provided one (starts with 'pay_'). Pass this whenever available — it's checked in preference to order_id.",
                    },
                },
                "required": ["order_id"],
            },
        },
    },
]
