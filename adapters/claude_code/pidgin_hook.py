#!/usr/bin/env python3
"""pidgin Claude Code adapter: UserPromptSubmit hook.

Reads the hook payload from stdin, runs the action-gated confidence check,
and emits JSON:
  - hookSpecificOutput.additionalContext: the gloss + gate instruction
    (model-visible, NOT shown in the transcript)
  - systemMessage: one-line translation + reduction gauge, shown to the user
    ONLY when transparency is toggled on (cli.py show on)

Toggles live in ~/.hermes/pidgin/config.yaml, hot-read every turn:
  enabled: false       -> hook does nothing
  transparency: true   -> show the one-liner

Every analyzed turn appends a stats record to stats.jsonl (cli.py stats).
Fail-open: any error exits 0 with no output, never blocks the prompt.
"""
import json
import sys
from pathlib import Path

# Resolve the pidgin root from this file's location so the hook works from
# any clone path (Claude Code plugin cache, ~/.hermes/pidgin, ~/Code/pidgin).
PIDGIN_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PIDGIN_DIR))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        prompt = (payload.get("prompt") or "").strip()
        if len(prompt) < 4 or prompt.startswith("/") or prompt.startswith("!"):
            return 0
        from core import (analyze, load_codebook, load_config, log_event,
                          render_context, transparency_line)
        cfg = load_config()
        if not cfg.get("enabled", True):
            return 0
        book_path = PIDGIN_DIR / "codebook.yaml"
        if not book_path.exists():
            book_path = PIDGIN_DIR / "codebook.seed.yaml"
        a = analyze(prompt, load_codebook(book_path))
        log_event(a, surface="claude-code")
        ctx = render_context(a)
        if not ctx:
            return 0
        out = {
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": ctx,
            },
        }
        if cfg.get("transparency"):
            line = transparency_line(a)
            if line:
                out["systemMessage"] = line
        print(json.dumps(out))
        return 0
    except Exception:
        return 0  # fail open


if __name__ == "__main__":
    sys.exit(main())
