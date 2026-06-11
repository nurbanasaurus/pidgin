#!/usr/bin/env python3
"""pidgin CLI: analyze messages, view reduction stats, toggle transparency.

Usage:
  cli.py <message>            analyze a message, print gate decision + context
  cli.py translate <message>  just show the expanded reading + savings
  cli.py stats [days]         aggregate reduction stats from stats.jsonl
  cli.py show on|off          toggle the visible translation line
  cli.py enable|disable       master kill switch for the whole layer
  cli.py status               current config
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import (STATS_PATH, analyze, load_codebook, load_config,
                  render_context, save_config, savings_estimate,
                  transparency_line)

BOOK_PATH = Path(__file__).parent / "codebook.yaml"


def cmd_analyze(text: str) -> int:
    a = analyze(text, load_codebook(BOOK_PATH))
    out = {
        "decision": a.decision,
        "interrupts": a.interrupts,
        "action_classes": a.action_classes,
        "matches": [{"code": m.code, "expansion": m.expansion,
                     "ambiguous": m.ambiguous, "confidence": m.confidence}
                    for m in a.matches],
        "unknowns": a.unknowns,
        "reading": a.reading,
        "savings": savings_estimate(a),
    }
    print(json.dumps(out, indent=2))
    ctx = render_context(a)
    if ctx:
        print("\n--- injected context ---\n" + ctx)
    return 0


def cmd_translate(text: str) -> int:
    a = analyze(text, load_codebook(BOOK_PATH))
    print(a.reading)
    line = transparency_line(a)
    if line:
        print(line)
    return 0


def cmd_stats(days: float) -> int:
    if not STATS_PATH.exists():
        print("no stats yet (stats.jsonl empty)")
        return 0
    cutoff = time.time() - days * 86400
    n = saved = verbose = 0
    eg_n = eg_saved = eg_orig = 0
    decisions, codes = {}, {}
    for ln in STATS_PATH.read_text().splitlines():
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if r.get("ts", 0) < cutoff:
            continue
        if r.get("kind") == "egress":
            eg_n += 1
            eg_saved += r.get("saved", 0)
            eg_orig += r.get("orig_tokens", 0)
            continue
        n += 1
        saved += r.get("saved", 0)
        verbose += r.get("verbose_tokens", 0)
        decisions[r.get("decision", "?")] = decisions.get(r.get("decision", "?"), 0) + 1
        for c in r.get("codes", []):
            codes[c] = codes.get(c, 0) + 1
    print(f"pidgin stats, last {days:g} day(s):")
    if eg_n:
        print(f"  EGRESS (you type normal, model gets dense):")
        print(f"    messages compressed  {eg_n}")
        print(f"    tokens saved         ~{eg_saved} ({100*eg_saved/eg_orig:.0f}% of those messages)")
        print(f"    note: user-string delta; run 'cli.py audit' for the assembled-call view")
    if n:
        pct = 100 * saved / verbose if verbose else 0
        print(f"  INGRESS (gloss/gate on what you typed):")
        print(f"    turns analyzed   {n}")
        print(f"    dense typing saved you ~{saved} tokens ({pct:.0f}% vs verbose)")
        confirms = decisions.get("confirm", 0)
        print(f"    interrupt rate   {confirms}/{n} = {100*confirms/n:.0f}%")
        if codes:
            top = sorted(codes.items(), key=lambda kv: -kv[1])[:8]
            print(f"    top codes        " + ", ".join(f"{c}({k})" for c, k in top))
    if not n and not eg_n:
        print(f"  no events in the last {days:g} day(s)")
    return 0


def cmd_audit(days: float) -> int:
    """Assembled-call accounting (the honest denominator): daily prompt-token
    totals from the Hermes state.db messages table. Compare days before and
    after enabling egress to see the real win, not the user-string delta."""
    import sqlite3
    import os
    db = Path(os.getenv("PIDGIN_STATE_DB") or Path.home() / ".hermes" / "state.db")
    if not db.exists():
        print("no message db found (audit needs a Hermes-style state.db or PIDGIN_STATE_DB)")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "select date(timestamp,'unixepoch','localtime') d, count(*),"
        " coalesce(sum(token_count),0), sum(length(content))/4 from messages"
        " where timestamp > strftime('%s','now') - ? * 86400"
        " group by d order by d", (days,)).fetchall()
    con.close()
    print(f"assembled-call audit, last {days:g} day(s) (all messages, all surfaces):")
    for d, cnt, toks, est in rows:
        shown = f"{toks:,} tokens" if toks else f"~{est or 0:,} tokens (chars/4 est; token_count unpopulated)"
        print(f"  {d}  {cnt:6d} msgs  {shown}")
    print("compare day-over-day after enabling egress; user-string savings that"
          " don't move this number are noise.")
    return 0


def cmd_toggle(key: str, value: bool) -> int:
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
    print(f"{key} = {value}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    if cmd == "stats":
        return cmd_stats(float(args[1]) if len(args) > 1 else 7.0)
    if cmd == "audit":
        return cmd_audit(float(args[1]) if len(args) > 1 else 7.0)
    if cmd == "show" and len(args) > 1 and args[1] in ("on", "off"):
        return cmd_toggle("transparency", args[1] == "on")
    if cmd == "egress" and len(args) > 1 and args[1] in ("on", "off"):
        return cmd_toggle("egress", args[1] == "on")
    if cmd in ("enable", "disable"):
        return cmd_toggle("enabled", cmd == "enable")
    if cmd == "status":
        from core import status_text
        print(status_text())
        return 0
    if cmd == "translate":
        return cmd_translate(" ".join(args[1:]))
    return cmd_analyze(" ".join(args))


if __name__ == "__main__":
    sys.exit(main())
