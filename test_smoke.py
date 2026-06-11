#!/usr/bin/env python3
"""pidgin smoke test: generic cases against the seed codebook, no personal data.

Run after install: python3 test_smoke.py  -> must print ALL PASS.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import (analyze, check_response, expand_text, load_codebook,
                  model_tier, prepare_input)

BOOK = load_codebook(Path(__file__).parent / "codebook.seed.yaml")

CASES = [
    # (message, expected decision)
    ("send the cr to the team", "confirm"),            # action + ambiguous code
    ("what's a cr?", "gloss"),                          # question never interrupts
    ("remind me tomorrow to call the bank", "manifest"),  # clean action
    ("thoughts on the dash layout?", "gloss"),          # known code, no action
    ("had coffee this morning", "pass"),                # plain chat
]


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

    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
