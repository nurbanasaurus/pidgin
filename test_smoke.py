#!/usr/bin/env python3
"""pidgin smoke test: generic cases against the seed codebook, no personal data.

Run after install: python3 test_smoke.py  -> must print ALL PASS.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import (analyze, check_response, compress_text, expand_text,
                  load_codebook, model_tier, prepare_input)

BOOK = load_codebook(Path(__file__).parent / "codebook.seed.yaml")

CASES = [
    # (message, expected decision)
    ("send the cr to the team", "confirm"),            # action + ambiguous code
    ("what's a cr?", "gloss"),                          # question never interrupts
    ("remind me tomorrow to call the bank", "manifest"),  # clean action
    ("thoughts on the dash layout?", "gloss"),          # known code, no action
    ("had coffee this morning", "pass"),                # plain chat
]


def egress_smoke() -> bool:
    """Deterministic compression must preserve payloads, names, numbers;
    fall back rather than risk meaning."""
    ok = True
    r = compress_text('Hey, could you please send Sam this: "ship it" thanks!', BOOK)
    good = '"ship it"' in r["text"] and "Sam" in r["text"] and "please" not in r["text"]
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] egress strips filler, freezes payload: {r['text']}")
    r2 = compress_text("increase the timeout by 50 percent, not to 50", BOOK)
    good = r2["text"].count("50") == 2 and "not" in r2["text"]
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] egress preserves numbers and negation")
    r3 = compress_text("Could you maybe deploy on Friday? Not sure it's ready.", BOOK)
    good = "maybe" in r3["text"] and "?" in r3["text"]
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] egress never strips modality or questions")
    return ok


def main() -> int:
    ok = True
    for msg, want in CASES:
        a = analyze(msg, BOOK)
        good = a.decision == want
        ok &= good
        print(f"[{'OK ' if good else 'FAIL'}] want={want:8s} got={a.decision:8s} {msg}")

    exp = expand_text("review the cr in the repo, reply y/n", BOOK)
    good = "change request" in exp and "git repository" in exp and "yes/no" in exp
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] expand_text: {exp}")

    good = model_tier("claude-sonnet-4-6") == "frontier" and model_tier("qwen2.5:7b") == "local"
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] model tiers (frontier/local)")

    out = prepare_input("review the cr", "qwen2.5:7b", BOOK)
    good = "change request" in out["text"] and out["context"] is None
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] prepare_input expands for local tier")

    a = analyze("remind me tomorrow to call the bank", BOOK)
    good = check_response(a, []) is not None and check_response(a, ["cron_add"]) is None
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] silent-drop post-check")

    ok &= egress_smoke()
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
