# Using pidgin

You mostly don't. That's the point: type like a normal person, and pidgin
works underneath. This page is for when you want to look under the hood,
grow your codebook, or verify what it's actually saving you.

## The mental model

Two directions, one dictionary:

- **Egress** (outbound): you type natural English; pidgin sends the model a
  tightened copy. Deterministic rules only; if there is any chance meaning
  changed, your original text is sent instead. You will never see it "guess".
- **Ingress** (inbound): when your message contains shorthand (yours or the
  codebook's), pidgin injects a glossary so the model reads you correctly,
  and arms a safety gate: if an ACTION rides on an AMBIGUOUS reading, the
  model must echo its interpretation in one line before acting. Questions
  never trigger the gate; a misread question costs one clarifying turn.

The dictionary (`codebook.yaml`) is yours: plain YAML, human-readable,
gitignored because it IS personal data.

## Checking on it

Same status block everywhere:

| Surface | How |
|---|---|
| Claude Code | `/pidgin` |
| Telegram / Discord / Hermes CLI | `/pidgin` |
| Terminal | `python3 cli.py status` |
| Hermes dashboard | the Pidgin card (egress/ingress split + toggles) |

```
pidgin ON | egress on | translation hidden
last 7d egress: 41 msgs compressed, ~480 tokens saved (22% of those msgs)
last 7d ingress: 130 turns glossed, ~610 tokens saved by dense typing, 1 confirm interrupt(s)
codebook: 22 codes, 0 proposal(s) pending review
```

Deeper views:
- `cli.py stats [days]` or `/pidgin stats [days]`: egress and ingress broken
  out separately, top codes, interrupt rate.
- `cli.py audit [days]`: daily totals across ALL message traffic. This is the
  honest denominator: your message is usually the smallest part of an API
  call (system prompt, history, and injected context dominate), so
  user-string savings that don't move this number are noise. Watch it
  day-over-day instead of trusting percentages.
- `tail -f stats.jsonl`: raw events as they happen.

## Switches (hot-read, no restarts)

| Command | Effect |
|---|---|
| `/pidgin on` / `off` (or `cli.py enable|disable`) | master switch, all surfaces |
| `/pidgin egress on|off` | outbound compression only |
| `/pidgin show on|off` | one-line translation display per message |

Turn `show on` for a day when you first install. Seeing exactly what was
sent ("pidgin: ha=Home Assistant | ~25% denser") is how you build trust in a
layer that rewrites your words; turn it off once you're bored of it.

## Growing your codebook (the miner)

The miner reads your own chat history and proposes shorthand you already
use plus phrases you repeat. Nothing is ever added without your approval.

```
/pidgin scan            (or: python3 miner.py scan [days])
/pidgin proposals
/pidgin approve ha Home Assistant
/pidgin reject lb
```

Rejections are permanent (stored in `rejected.yaml`); the miner never
re-proposes them. Triage advice from real use:
- Approve recurring entities and project names ("home assistant", your
  servers, your clients).
- Reject anything a frontier model already knows (NIST, USAA, FFS): those
  waste glossary tokens for zero comprehension gain.
- Collisions are flagged, never auto-coded. A code with two meanings (like
  `cr` = change request / code review) gets low confidence, which means the
  action gate will ask before acting on it. That's a feature.

You can also edit `codebook.yaml` directly; every surface hot-reloads it.

Entry format:
```yaml
codes:
  ha: Home Assistant                  # simple: confidence 0.9
  cr:
    expansions: [change request, code review]
    confidence: 0.5                   # collision: gate will confirm on actions
  repo:
    expansions: [git repository]
    transparent: true                 # eligible for egress substitution
```
`transparent: true` marks codes any frontier model reads without a glossary;
only those are used for outbound compression. Personal codes stay
ingress-only, where the glossary earns its cost.

## What egress will and will not touch

Will: greetings, "could you please" padding, trailing thanks, whitespace,
and transparent-code substitution ("git repository" -> "repo").

Will not, ever: anything inside quotes, code blocks, URLs, file paths, or
emails (frozen byte-identical); numbers; names; negations; modal phrasing
("could you maybe deploy?" stays a tentative question, never becomes an
order); duration shorthand (months/minutes ambiguity). If verification
can't prove every number and name survived, the original ships.

There is deliberately no LLM paraphrasing in the send path. A survival
check can't catch "Alex pays Sam" flipping to "Sam pays Alex", so
paraphrase compression stays offline until that's a solved problem.

## Honest expectations, one more time

- Egress on chatty messages: 10-25% of message tokens. On terse messages: ~0.
- Ingress with adopted shorthand: up to ~60% of message tokens.
- Your biggest wins are probably not in your messages at all: repeated
  boilerplate your stack sends on every call (cron preambles, injected
  context blocks). `cli.py audit` is there to keep you measuring the whole
  call rather than admiring a percentage of its smallest part.

## Troubleshooting

- `/pidgin` unknown in Claude Code: hooks/commands register at session
  start; restart the session.
- Hook never fires: `echo '{"prompt":"test the cr"}' | python3 adapters/claude_code/pidgin_hook.py`
  should print JSON. If empty, check python3 and PyYAML.
- Hermes command missing: `hermes plugins list` must show pidgin-gate
  enabled; restart the gateway after enabling.
- Everything off at once: `cli.py disable` (or delete config.yaml to reset
  to defaults: enabled, egress on, translation hidden).
