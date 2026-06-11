#!/usr/bin/env bash
# pidgin installer: wires the token layer into whatever stacks exist on this
# machine. Idempotent, detect-and-wire, nothing interactive.
#
#   ./install.sh            wire everything detected
#   ./install.sh --status   show what is wired where
#   ./install.sh --remove   unwire (leaves pidgin/ dir and codebook alone)
set -euo pipefail

PIDGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_DIR="$HOME/.hermes"
HERMES_PLUGIN="$HERMES_DIR/plugins/pidgin-gate"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
HOOK_CMD="python3 $PIDGIN_DIR/adapters/claude_code/pidgin_hook.py"

say() { printf '%s\n' "$*"; }

wire_hermes() {
  if [ ! -d "$HERMES_DIR/plugins" ]; then
    say "hermes: not found, skipping"
    return
  fi
  mkdir -p "$HERMES_PLUGIN"
  cp "$PIDGIN_DIR/adapters/hermes_plugin/plugin.yaml" "$HERMES_PLUGIN/"
  # stamp the actual clone path over the sentinel so the plugin finds core.py
  python3 - "$PIDGIN_DIR/adapters/hermes_plugin/__init__.py" "$HERMES_PLUGIN/__init__.py" "$PIDGIN_DIR" <<'PY'
import sys
src, dst, root = sys.argv[1], sys.argv[2], sys.argv[3]
open(dst, "w").write(open(src).read().replace("__PIDGIN_DIR__", root))
PY
  say "hermes: plugin installed -> $HERMES_PLUGIN (active on next gateway restart)"
}

wire_claude_code() {
  if ! command -v claude >/dev/null 2>&1 && [ ! -d "$HOME/.claude" ]; then
    say "claude code: not found, skipping"
    return
  fi
  python3 - "$CLAUDE_SETTINGS" "$HOOK_CMD" <<'PY'
import json, sys
from pathlib import Path
path, cmd = Path(sys.argv[1]), sys.argv[2]
cfg = json.loads(path.read_text()) if path.exists() else {}
hooks = cfg.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
already = any(h.get("command") == cmd
              for grp in hooks for h in grp.get("hooks", []))
if not already:
    hooks.append({"hooks": [{"type": "command", "command": cmd,
                             "timeout": 10, "statusMessage": "pidgin gate"}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2))
    print(f"claude code: hook wired -> {path}")
else:
    print("claude code: hook already wired")
PY
}

unwire() {
  rm -rf "$HERMES_PLUGIN" && say "hermes: plugin removed"
  python3 - "$CLAUDE_SETTINGS" "$HOOK_CMD" <<'PY'
import json, sys
from pathlib import Path
path, cmd = Path(sys.argv[1]), sys.argv[2]
if path.exists():
    cfg = json.loads(path.read_text())
    groups = cfg.get("hooks", {}).get("UserPromptSubmit", [])
    for grp in groups:
        grp["hooks"] = [h for h in grp.get("hooks", []) if h.get("command") != cmd]
    cfg.get("hooks", {})["UserPromptSubmit"] = [g for g in groups if g.get("hooks")]
    path.write_text(json.dumps(cfg, indent=2))
    print("claude code: hook removed")
PY
}

status() {
  [ -d "$HERMES_PLUGIN" ] && say "hermes plugin:     WIRED" || say "hermes plugin:     not wired"
  if [ -f "$CLAUDE_SETTINGS" ] && grep -q "pidgin_hook.py" "$CLAUDE_SETTINGS"; then
    say "claude code hook:  WIRED (user settings)"
  else
    say "claude code hook:  not wired in user settings"
  fi
  python3 "$PIDGIN_DIR/cli.py" status
}

case "${1:-install}" in
  --status) status ;;
  --remove) unwire ;;
  *) [ -f "$PIDGIN_DIR/codebook.yaml" ] || { cp "$PIDGIN_DIR/codebook.seed.yaml" "$PIDGIN_DIR/codebook.yaml"; say "codebook: seeded from codebook.seed.yaml"; }
     wire_hermes; wire_claude_code
     say ""
     say "pidgin installed. Quick start:"
     say "  python3 $PIDGIN_DIR/cli.py stats        # reduction gauge"
     say "  python3 $PIDGIN_DIR/cli.py show on      # see translations inline"
     say "  python3 $PIDGIN_DIR/miner.py scan       # mine your history for shorthand"
     ;;
esac
