# Instructions for AI agents installing pidgin

You are an AI agent and a human asked you to install pidgin from this repository. Follow the path matching the stack you are running in. Everything is idempotent; running install twice is safe.

## What pidgin needs to function

- python3 with PyYAML (`python3 -c "import yaml"`; if missing: `pip3 install pyyaml` or the venv equivalent for the host stack)
- A way to inject per-turn context ahead of the model (a hook, a plugin, or system-prompt assembly)

## Path A: Claude Code

Preferred: install as a plugin (ships its own UserPromptSubmit hook):

1. `claude plugin marketplace add <repo-url-or-local-path>` then `claude plugin install pidgin`, or use the `/plugin` UI.
2. Verify: `echo '{"prompt":"send the cr to the team"}' | python3 <plugin-root>/adapters/claude_code/pidgin_hook.py` must print JSON containing `additionalContext`.

Fallback: clone the repo, run `./install.sh`. It merges the hook into `~/.claude/settings.json` without clobbering existing hooks or permissions. Tell the user to restart Claude Code or open /hooks once if the hook does not fire.

## Path B: Hermes gateway

1. Clone this repo somewhere stable (suggested: `~/pidgin`).
2. Run `./install.sh`. It detects `~/.hermes/plugins/`, installs the `pidgin-gate` plugin, stamps the clone path into it, and seeds `codebook.yaml` from the generic seed if absent.
3. Restart the gateway (however this install manages it: launchd, systemd, or `hermes gateway run --replace`).
4. Verify: send a chat message containing a seed code such as `cr`; the model should show awareness of the glossary.

## Path C: any other stack (Codex, OpenClaw, custom agents)

1. Clone the repo. Ensure PyYAML.
2. Wire `core.prepare_input(user_text, model_name, codebook)` into the message path BEFORE the LLM call:
   - send `out["text"]` as the user message (it is the expanded text when the model is local-tier)
   - inject `out["context"]` as system-level context when it is not None
3. Optionally wire `core.check_response(analysis, tool_calls)` after the turn to catch silently dropped actions.
4. Seed the codebook: `cp codebook.seed.yaml codebook.yaml`.

## After any install

- Run the smoke test: `python3 test_smoke.py` (must print ALL PASS).
- Show the human: `python3 cli.py translate "send the cr to the team"` and `python3 cli.py stats`.
- Tell the human their codebook lives at `codebook.yaml` (gitignored, personal) and grows via `miner.py scan` (requires a Hermes-style SQLite history at `~/.hermes/state.db` or `PIDGIN_STATE_DB`; on other stacks, add entries manually or via `miner.py approve`).

## Rules

- NEVER commit `codebook.yaml`, `stats.jsonl`, `proposals.yaml`, or `config.yaml` to a shared repository; they contain the user's personal dialect and usage data. The .gitignore already covers this; do not override it.
- Do not auto-approve miner proposals; the human approves their own dialect.
- The master switch is `python3 cli.py enable|disable`; it is hot-read, no restarts needed.
