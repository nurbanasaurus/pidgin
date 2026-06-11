# Installing pidgin

Pick your stack. Every path is idempotent; running an install twice is safe.
If you are an AI agent doing this for a human, AGENTS.md is written for you.

## Requirements (all stacks)

- python3 (3.9+) with PyYAML: `python3 -c "import yaml"`. If that fails:
  `pip3 install pyyaml` (or your stack's venv equivalent).
- That's it. No other dependencies, no network calls, no model downloads.

## Claude Code (recommended: plugin)

The plugin ships the hook and the /pidgin command; nothing to edit.

```
claude plugin marketplace add nurbanasaurus/pidgin
claude plugin install pidgin@pidgin
```

Or from the UI: `/plugin marketplace add nurbanasaurus/pidgin`, then
`/plugin install pidgin`. Restart your session (hooks register at session
start). Verify: type `/pidgin` and you should get a status block.

What it wires: a UserPromptSubmit hook that analyzes each prompt and injects
the shorthand glossary plus the action gate as model context. Your prompt
text itself is never modified in Claude Code (the hook surface is inject-only
by design).

Manual alternative (no plugin): clone the repo anywhere and run
`./install.sh`. It merges the hook into `~/.claude/settings.json` without
touching your other hooks or permissions. `./install.sh --remove` unwires.
Do not use both the plugin AND the manual hook; you would inject twice.

## Hermes gateway

```
git clone https://github.com/nurbanasaurus/pidgin ~/pidgin
~/pidgin/install.sh
hermes plugins enable pidgin-gate
# restart your gateway however you run it, e.g.:
#   launchd:  launchctl kickstart -k gui/$(id -u)/<your-gateway-label>
#   manual:   hermes gateway run --replace
```

What it wires:
- `pre_llm_call` hook: glossary + action gate injected on chat turns
  (cron turns are skipped by default; their prompts are pre-engineered)
- `/pidgin` slash command on every platform your gateway serves (Telegram,
  Discord, CLI): status, toggles, stats, and the full miner workflow
  (scan / proposals / approve / reject) from your phone
- a starter codebook seeded at `<clone>/codebook.yaml` if you don't have one

Kill switches, no restart needed: `/pidgin off` (master), or env
`HERMES_PIDGIN_GATE=0` (restart required for env).

## Codex CLI / OpenClaw / any custom agent stack

There is no packaged adapter yet, but the core is three functions and zero
exotic dependencies, so wiring one is an afternoon, not a project. You need
ONE of these integration points in your stack:

1. **You can modify the outbound user message** (middleware, proxy, or the
   place your code assembles `messages`): full egress + ingress.

```python
import sys; sys.path.insert(0, "/path/to/pidgin")
from core import compress_text, prepare_input, load_codebook

book = load_codebook("/path/to/pidgin/codebook.yaml")

# EGRESS: user typed normal, tighten the outbound copy
r = compress_text(user_text, book)
outbound = r["text"]            # falls back to user_text on any doubt

# INGRESS: make sure the model reads any shorthand correctly
prep = prepare_input(outbound, model_name, book)
messages.append({"role": "user", "content": prep["text"]})
if prep["context"]:             # glossary + action gate, when relevant
    messages.insert(-1, {"role": "system", "content": prep["context"]})
```

2. **You can only inject context, not modify the message** (hook systems like
   Claude Code): skip `compress_text`, use only `prepare_input`'s context.

3. **You sit in front of an OpenAI-compatible API** (LiteLLM-style proxies):
   apply pattern 1 inside your request middleware. A packaged proxy mode is
   on the roadmap; until then it is the same ten lines.

Rules that keep you safe (the same ones our adapters follow):
- Store the ORIGINAL user text in your history/database, send the compressed
  copy. Never persist pidgin output as if the user wrote it; your search
  index and any learning loops should see real words.
- Keep compression away from paths where another component judges or learns
  from "what the user said".
- `model_tier()` matters: small local models (7B class) measurably misread
  dense text. `prepare_input` already expands for them; don't bypass it.

## Uninstall

- Claude Code plugin: `/plugin uninstall pidgin`
- Manual hook or Hermes: `./install.sh --remove`
- Your codebook, stats, and config stay in the clone directory; delete the
  directory to remove every trace.
