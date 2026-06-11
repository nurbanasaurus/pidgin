#!/usr/bin/env python3
"""pidgin codebook miner: propose new shorthand entries from real chat history.

Walks state.db user messages (self-extending: no hand-registry, the data is
the source) and surfaces three candidate classes:

  1. explicit definitions   "WMB (Work MacBook)", "WMB=work macbook"
                            -> highest confidence, expansion known
  2. recurring shorthand    unknown abbreviation-shaped tokens (per core
                            heuristics) used in >= MIN_TOKEN_HITS distinct
                            messages -> expansion unknown, needs human fill
  3. repeated phrases       2-4 word content phrases used in >= MIN_PHRASE_HITS
                            distinct messages -> proposes an initials code

Nothing lands in the codebook automatically. Proposals go to proposals.yaml;
a human approves/rejects via:
    miner.py scan [days]        mine and (re)write proposals.yaml
    miner.py list               show pending proposals
    miner.py approve <code> [expansion...]   move into codebook.yaml
    miner.py reject <code>      remember rejection, never re-propose

Collision safety: a proposed code colliding with the codebook, the common-word
or tech-acronym stoplists, or action verbs is flagged and never auto-coded.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import ACTION_VERBS, COMMON, _looks_like_shorthand, load_codebook

import yaml

PIDGIN = Path(__file__).parent
STATE_DB = Path(os.getenv("PIDGIN_STATE_DB") or Path.home() / ".hermes" / "state.db")
PROPOSALS = PIDGIN / "proposals.yaml"
REJECTED = PIDGIN / "rejected.yaml"
CODEBOOK = PIDGIN / "codebook.yaml"

MIN_TOKEN_HITS = 3      # distinct messages an unknown token must appear in
MIN_PHRASE_HITS = 5     # distinct messages a phrase must appear in
PHRASE_STOP = COMMON | {"i", "im", "id", "ive", "dont", "cant", "wont", "lets"}

DEF_PATTERNS = [
    re.compile(r"\b([A-Z]{2,5})\s*\(([A-Za-z][^)]{2,40})\)"),   # WMB (Work MacBook)
    re.compile(r"\b([A-Z]{2,8})\s*=\s*([A-Za-z][\w /-]{2,40})"),  # WMB=work macbook
]
# Both definition patterns require an ALL-CAPS code: lowercase `x = y` and
# `word (aside)` constructions are overwhelmingly prose/technical, not coinage.


def _user_messages(days: float) -> list[str]:
    cutoff = time.time() - days * 86400
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    rows = con.execute(
        "select content from messages where role='user' and timestamp > ? "
        "and content not like '[%' and length(content) between 10 and 2000",
        (cutoff,)).fetchall()
    con.close()
    # dedup exact repeats (retries, replays)
    seen, out = set(), []
    for (c,) in rows:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _load_yaml(path: Path) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _initials_code(phrase: str) -> str:
    return "".join(w[0] for w in phrase.split())


def scan(days: float) -> dict:
    msgs = _user_messages(days)
    book = load_codebook(CODEBOOK)
    rejected = set((_load_yaml(REJECTED).get("rejected") or []))
    known = set(book) | set(ACTION_VERBS)

    defs: dict[str, str] = {}
    tok_hits: Counter = Counter()
    tok_samples: dict[str, str] = {}
    phrase_hits: Counter = Counter()

    for msg in msgs:
        # 1. explicit definitions
        for pat in DEF_PATTERNS:
            for code, exp in pat.findall(msg):
                lc = code.lower()
                if lc not in known and lc not in COMMON and lc not in rejected:
                    defs.setdefault(lc, exp.strip())
        # 2. unknown shorthand tokens (count distinct messages)
        toks = set(re.findall(r"[A-Za-z][A-Za-z0-9/'-]+", msg))
        for tok in toks:
            low = tok.lower()
            if (low not in known and low not in COMMON and low not in rejected
                    and _looks_like_shorthand(tok)):
                tok_hits[low] += 1
                tok_samples.setdefault(low, msg[:120])
        # 3. repeated content phrases (2-4 grams over lowercased words)
        words = [w for w in re.findall(r"[a-z][a-z'-]+", msg.lower())]
        grams = set()
        for n in (2, 3, 4):
            for i in range(len(words) - n + 1):
                g = words[i:i + n]
                if g[0] in PHRASE_STOP or g[-1] in PHRASE_STOP:
                    continue
                if sum(1 for w in g if w not in PHRASE_STOP) < n - 0:
                    continue
                grams.add(" ".join(g))
        for g in grams:
            phrase_hits[g] += 1

    proposals = {}
    for code, exp in defs.items():
        proposals[code] = {"expansion": exp, "kind": "definition", "confidence": 0.9}
    for tok, n in tok_hits.items():
        if n >= MIN_TOKEN_HITS and tok not in proposals:
            proposals[tok] = {"expansion": None, "kind": "recurring-shorthand",
                              "hits": n, "sample": tok_samples[tok],
                              "note": "expansion unknown, fill on approve"}
    # keep longest phrases first so subphrases of an accepted phrase get pruned
    accepted_phrases: list[str] = []
    for phrase, n in sorted(phrase_hits.items(), key=lambda kv: (-len(kv[0]), -kv[1])):
        if n < MIN_PHRASE_HITS:
            continue
        if any(phrase in longer for longer in accepted_phrases):
            continue  # subphrase of an already-proposed longer phrase
        accepted_phrases.append(phrase)
        code = _initials_code(phrase)
        collision = code in known or code in COMMON or code in proposals
        proposals[phrase if collision else code] = {
            "expansion": phrase, "kind": "phrase", "hits": n,
            **({"note": f"code '{code}' collides, pick one manually"} if collision
               else {})}

    PROPOSALS.write_text(
        "# pidgin miner proposals. Review with: miner.py list / approve / reject\n"
        + yaml.safe_dump({"scanned_days": days, "messages": len(msgs),
                          "proposals": proposals}, sort_keys=False, allow_unicode=True))
    return proposals


def approve(code: str, expansion: str | None) -> int:
    props = _load_yaml(PROPOSALS).get("proposals") or {}
    if code not in props:
        print(f"no proposal '{code}'")
        return 1
    exp = expansion or props[code].get("expansion")
    if not exp:
        print(f"'{code}' has no expansion; supply one: miner.py approve {code} <expansion>")
        return 1
    raw = _load_yaml(CODEBOOK)
    raw.setdefault("codes", {})[code] = exp
    CODEBOOK.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    props.pop(code)
    PROPOSALS.write_text(yaml.safe_dump({"proposals": props}, sort_keys=False))
    print(f"approved: {code} = {exp}")
    return 0


def reject(code: str) -> int:
    rej = _load_yaml(REJECTED)
    rej.setdefault("rejected", [])
    if code not in rej["rejected"]:
        rej["rejected"].append(code)
    REJECTED.write_text(yaml.safe_dump(rej, sort_keys=False))
    props = _load_yaml(PROPOSALS).get("proposals") or {}
    props.pop(code, None)
    PROPOSALS.write_text(yaml.safe_dump({"proposals": props}, sort_keys=False))
    print(f"rejected: {code} (won't re-propose)")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "scan":
        days = float(args[1]) if len(args) > 1 else 30.0
        props = scan(days)
        print(f"{len(props)} proposal(s) -> {PROPOSALS}")
        for code, p in list(props.items())[:25]:
            exp = p.get("expansion") or "?"
            print(f"  {code:28s} [{p['kind']:20s}] {exp[:50]}"
                  + (f"  ({p.get('hits')} msgs)" if p.get("hits") else ""))
        return 0
    if args[0] == "list":
        props = _load_yaml(PROPOSALS).get("proposals") or {}
        for code, p in props.items():
            print(f"  {code:28s} [{p.get('kind','?'):20s}] {p.get('expansion') or '?'}")
        print(f"{len(props)} pending")
        return 0
    if args[0] == "approve" and len(args) >= 2:
        return approve(args[1], " ".join(args[2:]) or None)
    if args[0] == "reject" and len(args) >= 2:
        return reject(args[1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
