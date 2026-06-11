# pidgin

**Grammarly in reverse.** It makes your writing worse for humans and perfect for machines.

pidgin is a token-compression layer between you and your AI. **You type like a normal person; the model receives a tightened version; nothing changes for you.**

```
you type:    Hey, could you please send Luis this exact message: "the build is
             fixed, ship it" and please cc Oscar on the git repository thread. Thanks!

model sees:  send Luis this exact message: "the build is fixed, ship it"
             and cc Oscar on repo thread.
```

Notice what survived untouched: the quoted payload (byte-identical), every name, the meaning. That's the design constraint everything else serves.

## Two directions, one codebook

**Egress (default on): you type normal, pidgin compresses outbound.** Deterministic only, provably meaning-preserving:
- *Span freezing*: quoted text, code fences, URLs, file paths, and emails are untouchable
- *Filler strip*: politeness and throat-clearing only ("could you please", greetings, trailing thanks); never modals or auxiliaries, so a musing can't become an order
- *Transparent-code substitution*: only codebook entries any frontier model reads without a glossary
- *Verification*: every number and proper noun must survive into the compressed form, or your original text ships unchanged. Fallback-on-any-doubt is the rule.

**Ingress: if you drift into shorthand yourself (most people do, fast), pidgin makes it safe.** A glossary of your personal codes is injected so any model recovers your intent, and the action gate interrupts only when an *action* rides on an *ambiguous* reading: a misread question costs one clarifying turn, so questions never interrupt. Measured interrupt rate on real traffic: 0%.

**The codebook** is a plain YAML file of your shorthand, mined from your own chat history by `miner.py` (you approve every entry). Human-readable, diffable, shareable, portable to a different AI entirely. No weights, no lock-in.

## Honest expectations

We had this design adversarially reviewed (two independent AI reviewers, full code access) before building, and the numbers below reflect that loop, not marketing:

- **Egress on natural chatty messages: 10-25% of message tokens.** Deterministic, zero meaning risk, zero latency. On already-terse messages it does nothing, by design.
- **Ingress with adopted shorthand: up to ~60% (2.6x), measured with tiktoken on real messages.** That ceiling needs *you* to type dense; pidgin makes that safe rather than forcing it.
- **Your message is the smallest part of the API call.** System prompts, history, and injected context dominate. pidgin's biggest single win in our own stack was compressing a 109-token scheduler boilerplate that rode every automated job, down to 41. Hunt your templates; `cli.py audit` shows the assembled-call picture so you measure the right denominator.
- **What we deliberately did NOT build**: an LLM that paraphrases your words in the hot path. A token-survival check is structurally blind to role reversal ("Oscar pays Luis" vs "Luis pays Oscar"), question-to-imperative flips, modality loss, and by-vs-to on numbers. Until that's solved, paraphrase compression stays out of the send path. Deterministic or nothing.
- Small local models misread dense text (measured: a 7B was intent-equivalent on 1 of 5 dense tasks), so pidgin's tier switch *expands* text for them instead. Compression is for models that can take it.

## Install (AI-first)

Fastest path: **paste this repo URL at your AI agent and say "install this".** AGENTS.md has agent-directed instructions. Flows:

**Claude Code** (plugin, ships its own hook): `/plugin marketplace add <repo-url>` then `/plugin install pidgin`, or clone and run `./install.sh`.

**Hermes gateway**: `git clone <repo-url> ~/pidgin && ~/pidgin/install.sh` then restart the gateway.

**Any other stack**: `core.py` is stdlib + PyYAML. Egress: `compress_text(text, codebook)`. Ingress: `prepare_input(text, model, codebook)`. If your stack can modify an outbound message or inject context, you can host pidgin.

## Use

```
python3 cli.py stats              # what egress + ingress saved, separately
python3 cli.py audit              # assembled-call accounting (the honest denominator)
python3 cli.py translate "msg"    # preview a reading
python3 cli.py egress on|off      # outbound compression toggle
python3 cli.py show on            # display translations inline
python3 cli.py enable|disable     # master switch, hot-read, no restarts
python3 miner.py scan             # mine your history for codebook candidates
python3 test_smoke.py             # verify an install
```

## The bet

Compression research keeps shrinking machine context with lossy ML. pidgin bets the other way: the human side of the conversation is the most compressible part, your own history is the best training data, and a transparent dictionary you can read beats an opaque model you can't audit. When the stakes are your own instructions, lossless-or-nothing wins.

## Roadmap

- Exact-match re-quote dedup wired into more surfaces (function exists: `dedup_exact`)
- Dense output mode (the model answers in your dialect on surfaces you choose; output tokens are where the money is)
- OpenAI-compatible proxy mode
- Codebook merge tooling
- Offline (never hot-path) LLM rewrite experiments, judged by paired-task equivalence benching

## License

MIT
