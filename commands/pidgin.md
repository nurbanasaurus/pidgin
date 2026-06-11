---
description: Pidgin token-layer status and toggles (saved tokens, switches, proposals)
---

The pidgin plugin root is ${CLAUDE_PLUGIN_ROOT}. The user invoked /pidgin with
arguments: "$ARGUMENTS".

- No arguments: run `python3 ${CLAUDE_PLUGIN_ROOT}/cli.py status` and relay the
  block verbatim. Add one short observation only if something looks off.
- `stats [days]` / `audit [days]` / `translate <text>`: pass straight through
  to `python3 ${CLAUDE_PLUGIN_ROOT}/cli.py <args>`.
- `on` / `off`: run `python3 ${CLAUDE_PLUGIN_ROOT}/cli.py enable|disable`.
- `egress on|off` and `show on|off`: pass through to cli.py unchanged.
- `proposals`: run `python3 ${CLAUDE_PLUGIN_ROOT}/miner.py list`, then offer
  approve/reject per entry.

Toggles are hot-read by every pidgin surface; no restart needed. Confirm the
new state after flipping.
