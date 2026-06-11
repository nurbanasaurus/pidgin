# pidgin

**Grammarly in reverse.** It makes your writing worse for humans and perfect for machines.

pidgin is a learned shorthand layer between you and your AI. You type telegraphic, abbreviated, half-lazy messages; your AI reads them perfectly, because pidgin maintains a personal codebook of *your* shorthand and injects the glossary right where the model needs it. Over time, you and your AI develop a shared dialect that nobody else speaks.

```
you type:    remind 8d: circle back w/ CC re stale tasks, no me
model sees:  remind 8 days: circle back with Claude Code re stale tasks, no me
             (plus your glossary, plus a safety gate on the action)
```

## Why

Every word you type at an AI costs tokens, latency, and your own attention. Most of those words are social padding the model never needed. Trimming them by hand feels rude and reads ambiguous; pidgin makes it safe to be terse.

## What it actually does

1. **Codebook**: a plain YAML dictionary of your shorthand (`wmb: work MacBook`). Human-readable, portable, shareable, diffable. No ML weights, no embeddings required, no lock-in.
2. **Glossary injection**: each message is scanned; matched codes are injected as context so any model recovers your intent. Frontier models get your dense text untouched.
3. **Action-gated confirmation**: the safety idea that makes terseness trustworthy. A misread *question* costs one clarifying turn, so it never interrupts. A misread *instruction* could send the wrong email, so when a message requests an action AND contains uncertain shorthand, the model must echo its reading in one line before acting. In measurement on real traffic this fires on roughly 0% of normal messages.
4. **Model tiers**: small local models demonstrably misread dense input (in our paired-task bench a 7B model was intent-equivalent on only 1 of 5 dense tasks). pidgin detects the model class: frontier models get dense text + glossary; local models get the text deterministically expanded first.
5. **The miner**: scans your own chat history for shorthand you already invented and phrases you repeat, then proposes codebook entries. Nothing lands without your approval. Your dialect grows out of how you already talk.

## Honest expectations

- Measured on 20 real messages with tiktoken: **~62% input-token savings (2.6x)** vs the verbose equivalent. Best case ~74% on chatty status messages; worst case ~49% on already-dense technical asks.
- Input tokens are the cheap side of the ledger. The bigger wins are your keystrokes, your attention, and (roadmap) dense *output* you read natively.
- This is a young project. The gate heuristics are deliberately simple and auditable; expect to approve/reject miner proposals rather than trust them blindly.

## Install (AI-first)

The fastest path: **paste this repo URL at your AI agent and say "install this".** AGENTS.md contains step-by-step instructions written for agents. Verified flows:

### Claude Code (as a plugin)

```
/plugin marketplace add <this-repo-url>   # or: clone + point at the directory
/plugin install pidgin
```

The plugin ships a UserPromptSubmit hook; no settings editing. Alternatively clone anywhere and run `./install.sh`, which merges the hook into `~/.claude/settings.json` idempotently.

### Hermes gateway

```
git clone <this-repo-url> ~/pidgin && ~/pidgin/install.sh
```

Detects Hermes, installs the `pre_llm_call` plugin into `~/.hermes/plugins/pidgin-gate`, seeds a starter codebook. Active on the next gateway restart.

### Anything else (Codex, OpenClaw, custom stacks)

`core.py` is dependency-light (stdlib + PyYAML) and stack-agnostic. One call does everything:

```python
from core import prepare_input, load_codebook
out = prepare_input(user_text, model_name, load_codebook("codebook.yaml"))
# out["text"]    -> what to send as the user message
# out["context"] -> glossary + gate instruction to inject (None if not needed)
```

If your stack can inject system context per turn, you can host pidgin.

## Use

```
python3 cli.py "remind 8d: review cr w/ oscar"   # see the gate decision
python3 cli.py translate "getting wmb + coffee"  # preview the expansion
python3 cli.py stats                             # your reduction gauge
python3 cli.py show on                           # display translations inline
python3 cli.py enable|disable                    # master switch, no restarts
python3 miner.py scan                            # mine your history (Hermes/SQLite today)
python3 miner.py approve <code> [expansion]      # grow your dialect
```

## The bet

Compression research keeps trying to shrink machine context with lossy ML. pidgin bets the other direction: the human side of the conversation is the most compressible part, the user's own history is the best training data, and a transparent dictionary beats an opaque model. Your codebook is a file you can read, edit, share with a friend, or carry to a different AI entirely.

## Roadmap

- Dense output mode (the model answers in your dialect on surfaces you choose)
- OpenAI-compatible proxy mode (host pidgin in front of any API)
- Codebook merge tooling (swap dialects between users)
- Embedding-based code matching

## License

MIT
