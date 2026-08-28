"""Regression tests for conversation-scoped constraints.

These cover the bug this module exists to prevent: a fabric named for one
product type ("linen shirts") surviving into a search for a different one
("some trousers") and silently returning nothing. Run from this directory:

    ./venv/bin/python test_context.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from context import (
    scrub_constraints, subject_tokens, expresses_no_preference, normalize_gender, durable_hints
)

fails = []
def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r} want {want!r}")
    print(("PASS " if got == want else "FAIL ") + label)

# --- subjects
check("shirt != tshirt", subject_tokens("shirt") & subject_tokens("t-shirt"), set())
check("trousers", subject_tokens("trousers"), {"trouser"})
check("pants==trousers", bool(subject_tokens("pants") & subject_tokens("trousers")), True)
check("sneakers==shoes", bool(subject_tokens("sneakers") & subject_tokens("running shoes")), True)

# --- the reported bug: linen shirts -> trousers
thread = {}
c1, n1 = scrub_constraints({"query": "shirt", "materials": ["linen"], "budget": 2000}, thread, "I want linen shirts under 2000")
check("linen kept for shirts", c1.get("materials"), ["linen"])
c2, n2 = scrub_constraints({"query": "trouser", "materials": ["linen"], "budget": 2000}, thread, "I want to get some trousers")
check("linen dropped for trousers", c2.get("materials"), None)
check("stale budget dropped", c2.get("budget"), None)
check("note emitted", bool(n2 and "trouser" in n2[0]), True)

# same-subject follow-up keeps constraints
thread2 = {}
scrub_constraints({"query": "shirt", "materials": ["linen"], "colors": ["black"]}, thread2, "black linen shirt")
c3, _ = scrub_constraints({"query": "shirt", "materials": ["linen"], "colors": ["black"], "budget": 3000}, thread2, "make it more premium, around 3000")
check("same subject keeps linen", c3.get("materials"), ["linen"])
check("same subject keeps colour", c3.get("colors"), ["black"])

# restated constraint survives subject change
thread3 = {}
scrub_constraints({"query": "shirt", "materials": ["linen"]}, thread3, "linen shirts please")
c4, _ = scrub_constraints({"query": "trouser", "materials": ["linen"]}, thread3, "now linen trousers")
check("restated linen survives", c4.get("materials"), ["linen"])

# partial: colour restated, fabric not
thread4 = {}
scrub_constraints({"query": "shirt", "materials": ["linen"], "colors": ["black"]}, thread4, "black linen shirt")
c5, _ = scrub_constraints({"query": "trouser", "materials": ["linen"], "colors": ["black"]}, thread4, "black trousers now")
check("colour restated kept", c5.get("colors"), ["black"])
check("fabric not restated dropped", c5.get("materials"), None)

# --- no preference overrides, same subject
thread5 = {}
scrub_constraints({"query": "shirt", "materials": ["linen"], "colors": ["black"], "premium": True}, thread5, "black linen shirts, premium")
c6, n6 = scrub_constraints({"query": "shirt", "materials": ["linen"], "colors": ["black"]}, thread5, "no particular preferences — just show me what you have")
check("no-pref clears materials", c6.get("materials"), None)
check("no-pref clears colours", c6.get("colors"), None)
check("no-pref flags saved prefs off", c6.get("ignore_saved_preferences"), True)

for phrase in ["I don't have any preference", "doesn't matter", "just show me some options",
               "anything works", "surprise me", "no preference", "whatever you have"]:
    check(f"no-pref phrase: {phrase}", expresses_no_preference(phrase), True)
check("normal msg is not no-pref", expresses_no_preference("I want black linen shirts"), False)

# --- gender
check("Male->Men", normalize_gender("Male"), "Men")
check("Female->Women", normalize_gender("female"), "Women")
check("Other->None", normalize_gender("Other"), None)
check("blank->None", normalize_gender(""), None)

# --- durable hints never carry fabric
check("fabric not durable", durable_hints({"colors": ["black"], "materials": ["linen"]}), {"colors": ["black"]})

# --- cross-sell must not move the subject
thread6 = {}
scrub_constraints({"query": "shirt", "materials": ["linen"]}, thread6, "linen shirts")
scrub_constraints({"query": "belt", "purpose": "complement"}, thread6, "linen shirts")
check("complement leaves subject alone", thread6["subject_query"], "shirt")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES:\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
