#!/usr/bin/env python3
"""pidgin core: action-gated confidence check for dense/telegraphic chat input.

Design (see Aria/Plans/Token-Compression-Plugin.md):
  Gate on ACTION, not ambiguity. A misread question costs one clarifying turn,
  so it never interrupts. A misread instruction that would trigger a tool call
  is the dangerous case, so:

    1. action intent + any low-confidence/unknown code  -> CONFIRM
       (model is instructed to echo its reading in one line before acting)
    2. action intent + all codes confident              -> PASS + manifest
       (manifest lists expected action classes; the post-check flags a
        silent drop if the response contains no matching tool call)
    3. no action intent                                  -> PASS + gloss
       (expansions injected as context, zero interruption)

Pure stdlib + yaml. No Hermes imports, no Claude Code imports: adapters
under adapters/ wrap this so the same core serves both stacks.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # codebook can also be loaded pre-parsed via load_codebook(data=...)
    yaml = None

CONFIDENCE_FLOOR = 0.75  # matches below this are "uncertain" for gating purposes

# Verbs that imply an irreversible or outward action when used imperatively.
# Maps verb -> action class used in the manifest / silent-drop post-check.
ACTION_VERBS = {
    "remind": "scheduler", "schedule": "scheduler", "cron": "scheduler",
    "alarm": "scheduler", "snooze": "scheduler",
    "send": "messaging", "email": "messaging", "msg": "messaging",
    "text": "messaging", "dm": "messaging", "reply": "messaging",
    "notify": "messaging", "ping": "messaging", "forward": "messaging",
    "delete": "deletion", "rm": "deletion", "remove": "deletion",
    "purge": "deletion", "wipe": "deletion", "clean": "deletion",
    "cancel": "calendar", "book": "calendar", "reschedule": "calendar",
    "invite": "calendar",
    "pay": "payment", "buy": "payment", "order": "payment",
    "transfer": "payment",
    "post": "publish", "publish": "publish", "tweet": "publish",
    "deploy": "ops", "push": "ops", "restart": "ops", "kill": "ops",
}

# Duration shorthand like 8d / 45m / 2h / 3w: expanded inline, never flagged unknown.
DURATION_RE = re.compile(r"^(\d+)(d|h|m|w|s|min|hr)s?$", re.I)
DURATION_NAMES = {"d": "days", "h": "hours", "m": "minutes", "w": "weeks",
                  "s": "seconds", "min": "minutes", "hr": "hours"}

VOWELS = set("aeiouy")  # y counts: "try"/"shy" are words, not shorthand

# Small common-word set so ordinary short words are never flagged as shorthand.
COMMON = set("""
a i o an as at be by do go he if in is it me my no of on or so to up us we
all and any are but can did for get got had has her him his how its let
may new not now off old one our out own per put say she the too two use
was way who why yes yet you also back been best both come days done down
each even ever fact feel few find first from full give good have here
high into just keep kind know last late left less like line list live
long look made make many more most much must name need next only onto
open over part past plan real rest said same see seem sent show side
some soon stay step still stop such sure take tell test text than that
their them then there these they thing think this time told until upon
very want week well went were what when which while will with word work
your about after again before being below between during makes today
tomorrow morning night start check confirm done report finish wait
right wrong every never always asap fml lol idk btw fyi ok okay yeah
nah pls thanks thx etc via vs am pm est edt utc min max avg key new
""".split())

# Universal tech acronyms: any frontier model reads these natively. They are
# NOT personal shorthand, so they never count as unknown and never gate.
COMMON |= set("""
mvp json yaml xml csv pdf html css js ts py sql db api url uri usb ssl
tls ssh http https ftp dns vpn ip os ui ux ai ml llm gpu cpu ram io
cli gui sdk ide pr ci cd qa dev prod env git diff cron faq eta id ids
2fa mfa sso oauth jwt rss s3 ec2 k8s vm iso mac pc app apps wifi nfc
txt md log yml toml ini sh zsh png jpg jpeg gif svg mp3 mp4 wav zip
ssd hdd nas dns ssl th ll
vin vw bmw gm suv ev rpm mpg mph psi oem abs ac dmv
""".split())


@dataclass
class Match:
    code: str
    expansion: str          # chosen (highest-weight) expansion
    expansions: list        # all known expansions, >1 means collision
    confidence: float

    @property
    def ambiguous(self) -> bool:
        return self.confidence < CONFIDENCE_FLOOR or len(self.expansions) > 1


@dataclass
class Analysis:
    text: str
    matches: list = field(default_factory=list)    # [Match]
    unknowns: list = field(default_factory=list)   # [str] suspected shorthand w/o entry
    durations: list = field(default_factory=list)  # [(token, gloss)]
    action_classes: list = field(default_factory=list)  # e.g. ["scheduler"]
    decision: str = "pass"                          # pass | gloss | manifest | confirm
    reading: str = ""                               # best-effort expanded text

    @property
    def interrupts(self) -> bool:
        return self.decision == "confirm"


def load_codebook(path: str | Path | None = None, data: dict | None = None) -> dict:
    """Load codebook.yaml -> {code: {expansions: [...], confidence: float, ...}}.

    Accepts either a path or a pre-parsed dict (for tests / non-yaml callers).
    Normalizes shorthand entry forms:
      cc: Claude Code                       (string -> single expansion, conf 0.9)
      cr: {expansions: [a, b], confidence: 0.5}
    """
    if data is None:
        if yaml is None:
            raise RuntimeError("pyyaml not available and no pre-parsed data passed")
        p = Path(path)
        if not p.exists():  # fresh install: fall back to the generic seed
            seed = p.parent / "codebook.seed.yaml"
            if seed.exists():
                p = seed
        raw = yaml.safe_load(p.read_text()) or {}
        data = raw.get("codes", raw)
    book = {}
    for code, val in data.items():
        if isinstance(val, str):
            book[code.lower()] = {"expansions": [val], "confidence": 0.9}
        else:
            ent = dict(val)
            ent.setdefault("expansions", [ent.pop("expansion")] if "expansion" in ent else [])
            ent.setdefault("confidence", 0.9 if len(ent["expansions"]) == 1 else 0.5)
            book[code.lower()] = ent
    return book


def _tokens(text: str):
    return re.findall(r"[A-Za-z0-9/'+-]+", text)


def _looks_like_shorthand(tok: str) -> bool:
    """Heuristic for an unrecognized abbreviation worth flagging.

    ALL-CAPS 2-5 chars (WMB, CR) or short vowelless lowercase (tg, pls).
    Capitalized words (Oscar, Luis) are treated as proper nouns and skipped.
    """
    if tok.isupper() and 2 <= len(tok) <= 5 and tok.isalpha():
        return True
    if tok.islower() and 2 <= len(tok) <= 5 and tok.isalpha() and not (set(tok) & VOWELS):
        return True
    return False


def analyze(text: str, codebook: dict) -> Analysis:
    a = Analysis(text=text)
    seen = set()
    expanded = []

    for tok in _tokens(text):
        low = tok.lower().strip("/")
        m = DURATION_RE.match(low)
        if m and m.group(2).lower() in DURATION_NAMES:
            gloss = f"{m.group(1)} {DURATION_NAMES[m.group(2).lower()]}"
            a.durations.append((tok, gloss))
            expanded.append(gloss)
            continue
        if low in codebook and low not in COMMON:
            if low not in seen:
                seen.add(low)
                ent = codebook[low]
                a.matches.append(Match(code=low,
                                       expansion=ent["expansions"][0],
                                       expansions=list(ent["expansions"]),
                                       confidence=float(ent["confidence"])))
            expanded.append(codebook[low]["expansions"][0])
            continue
        # NOTE: no COMMON guard here. "text"/"check"/"clean" are common words
        # AND action verbs; the old guard masked them so "text Luis re dinner"
        # never registered a messaging action (found in 2026-06-11 design
        # review). A false manifest is harmless (non-interrupting context).
        if low in ACTION_VERBS:
            if ACTION_VERBS[low] not in a.action_classes:
                a.action_classes.append(ACTION_VERBS[low])
            expanded.append(tok)
            continue
        if low not in COMMON and _looks_like_shorthand(tok) and low not in seen:
            seen.add(low)
            a.unknowns.append(tok)
        expanded.append(tok)

    a.reading = " ".join(expanded)

    uncertain = bool(a.unknowns) or any(m.ambiguous for m in a.matches)
    if a.action_classes and uncertain:
        a.decision = "confirm"
    elif a.action_classes:
        a.decision = "manifest"
    elif a.matches or a.unknowns or a.durations:
        a.decision = "gloss"
    else:
        a.decision = "pass"
    return a


def render_context(a: Analysis) -> str | None:
    """Render the analysis as a context block for injection ahead of the model.

    Both adapters (Hermes pre_llm_call, Claude Code UserPromptSubmit) inject
    text rather than intercepting execution, so the CONFIRM decision becomes
    a binding instruction to the model: echo your reading, wait for a yes.
    """
    if a.decision == "pass":
        return None

    lines = ["## pidgin: shorthand reading of this message"]
    for m in a.matches:
        alts = f" (could also mean: {', '.join(m.expansions[1:])})" if len(m.expansions) > 1 else ""
        lines.append(f"- `{m.code}` = {m.expansion}{alts} [conf {m.confidence:.2f}]")
    for tok, gloss in a.durations:
        lines.append(f"- `{tok}` = {gloss}")
    for tok in a.unknowns:
        lines.append(f"- `{tok}` = UNRECOGNIZED shorthand, no codebook entry")

    if a.decision == "confirm":
        lines.append("")
        lines.append(
            "GATE: this message requests an action ("
            + ", ".join(a.action_classes)
            + ") but contains uncertain shorthand. Before calling any tool that "
            "acts on the uncertain reading, reply with ONE line stating your "
            "expanded reading and wait for confirmation. If the uncertain code "
            "does not affect the action, proceed and note your reading inline.")
    elif a.decision == "manifest":
        lines.append("")
        lines.append(
            "GATE: expected action classes for this message: "
            + ", ".join(a.action_classes)
            + ". If you finish this turn without a tool call in these classes, "
            "state explicitly why no action was taken.")
    return "\n".join(lines)


PIDGIN_DIR = Path(__file__).parent
CONFIG_PATH = PIDGIN_DIR / "config.yaml"
STATS_PATH = PIDGIN_DIR / "stats.jsonl"

DEFAULT_CONFIG = {"enabled": True, "transparency": False, "egress": True}

# ── model tiers ───────────────────────────────────────────────────────────────
# Frontier-class models read telegraphic input fine with just a gloss; small
# local models demonstrably do not (compat bench 2026-06-11: qwen2.5:7b went
# 1/5 equivalent on dense input). Policy:
#   frontier -> pass dense text through, inject gloss as context
#   local    -> deterministically EXPAND the text before the model sees it
# Detection is pattern-based, not a hand-registry (self-extending): cloud
# suffixes and known frontier families are frontier, everything else is local.
# Override per model in config.yaml:  tier_overrides: {"qwen3-coder:480b": frontier}

FRONTIER_PATTERNS = (":cloud", "claude-", "gemini-", "gpt-", "grok-", "o1", "o3",
                     "deepseek-v", "kimi-", "qwen3-coder:480b", "gpt-oss")


def model_tier(model: str, cfg: dict | None = None) -> str:
    name = (model or "").lower()
    overrides = (cfg or load_config()).get("tier_overrides") or {}
    for pat, tier in overrides.items():
        if pat.lower() in name:
            return tier
    if any(p in name for p in FRONTIER_PATTERNS):
        return "frontier"
    return "local"


def expand_text(text: str, codebook: dict) -> str:
    """Deterministic full expansion of codebook shorthand, preserving the
    original punctuation and casing of everything else. This is what local
    models get instead of dense text + gloss."""
    def sub_token(m: re.Match) -> str:
        tok = m.group(0)
        low = tok.lower()
        d = DURATION_RE.match(low)
        if d and d.group(2).lower() in DURATION_NAMES:
            return f"{d.group(1)} {DURATION_NAMES[d.group(2).lower()]}"
        if low in codebook and low not in COMMON:
            return codebook[low]["expansions"][0]
        return tok
    return re.sub(r"[A-Za-z0-9/'+-]+", sub_token, text)


def prepare_input(text: str, model: str, codebook: dict) -> dict:
    """Tier-aware input prep. Returns {text, context, tier}.

    frontier: text untouched, gloss/gate as injectable context
    local:    text fully expanded, no context needed
    """
    tier = model_tier(model)
    if tier == "local":
        return {"text": expand_text(text, codebook), "context": None, "tier": tier}
    a = analyze(text, codebook)
    return {"text": text, "context": render_context(a), "tier": tier}


def load_config() -> dict:
    """Runtime toggles. Missing/broken file -> defaults (fail open, stay quiet)."""
    try:
        if yaml and CONFIG_PATH.exists():
            cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            return {**DEFAULT_CONFIG, **cfg}
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    lines = [f"{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in cfg.items()]
    CONFIG_PATH.write_text("# pidgin runtime toggles (hot-read every turn)\n" + "\n".join(lines) + "\n")


def _est_tokens(s: str) -> int:
    return max(1, round(len(s) / 4))


def savings_estimate(a: Analysis) -> dict:
    """How many tokens the dense form saved vs its verbose recovery.

    a.reading is the expanded text, a.text the dense original. Heuristic
    chars/4 counting; good enough for a running reduction gauge.
    """
    dense = _est_tokens(a.text)
    verbose = _est_tokens(a.reading)
    saved = max(0, verbose - dense)
    return {"dense_tokens": dense, "verbose_tokens": verbose, "saved": saved,
            "pct": round(100 * saved / verbose, 1) if verbose else 0.0}


def log_event(a: Analysis, surface: str) -> None:
    """Append one stats record per analyzed turn. Best-effort, never raises."""
    try:
        s = savings_estimate(a)
        rec = {"ts": round(time.time(), 1), "surface": surface,
               "decision": a.decision,
               "codes": [m.code for m in a.matches],
               "unknowns": a.unknowns, **s}
        with STATS_PATH.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def transparency_line(a: Analysis) -> str | None:
    """One unobtrusive line showing the translation, for when transparency is on."""
    if a.decision == "pass":
        return None
    parts = [f"{m.code}={m.expansion}" for m in a.matches]
    parts += [f"{t}={g}" for t, g in a.durations]
    parts += [f"{t}=?" for t in a.unknowns]
    s = savings_estimate(a)
    gauge = f" | ~{s['pct']:.0f}% denser than verbose" if s["saved"] else ""
    gate = f" | gate: {a.decision}" if a.decision in ("confirm", "manifest") else ""
    return f"pidgin: {', '.join(parts)}{gauge}{gate}"


def status_text(days: float = 7.0) -> str:
    """One compact status block used by /pidgin (Telegram), /pidgin (Claude
    Code), and cli.py status. Plain text, telegram-safe, no markdown."""
    cfg = load_config()
    n = saved = verbose = interrupts = 0
    eg_n = eg_saved = eg_orig = 0
    codes_hit: dict = {}
    cutoff = time.time() - days * 86400
    if STATS_PATH.exists():
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
            interrupts += 1 if r.get("decision") == "confirm" else 0
    try:
        book = load_codebook(PIDGIN_DIR / "codebook.yaml")
        ncodes = len(book)
    except Exception:
        ncodes = 0
    pending = 0
    try:
        if yaml and (PIDGIN_DIR / "proposals.yaml").exists():
            pending = len((yaml.safe_load((PIDGIN_DIR / "proposals.yaml").read_text())
                           or {}).get("proposals") or {})
    except Exception:
        pass
    state = "ON" if cfg.get("enabled", True) else "OFF (master switch)"
    eg_state = "on" if cfg.get("egress", True) else "off"
    tr_state = "shown" if cfg.get("transparency") else "hidden"
    lines = [
        f"pidgin {state} | egress {eg_state} | translation {tr_state}",
        f"last {days:g}d egress: {eg_n} msgs compressed, ~{eg_saved} tokens saved"
        + (f" ({100*eg_saved/eg_orig:.0f}% of those msgs)" if eg_orig else ""),
        f"last {days:g}d ingress: {n} turns glossed, ~{saved} tokens saved by dense typing, "
        f"{interrupts} confirm interrupt(s)",
        f"codebook: {ncodes} codes, {pending} proposal(s) pending review",
    ]
    return "\n".join(lines)


# ── egress compressor ─────────────────────────────────────────────────────────
# Deterministic ONLY, per the 2026-06-11 two-reviewer design loop (Aria +
# Claude). The LLM-rewrite layer was CUT from the hot path: a token-survival
# gate is structurally blind to role reversal, question-to-imperative flips,
# modality, and by-vs-to on numbers; plus it breaks prompt-cache determinism
# and replay. What remains is provably meaning-preserving:
#   1. span freezing: quoted text, code fences, URLs, paths, emails are
#      untouchable (literal payloads must survive byte-identical)
#   2. conservative filler strip: politeness and throat-clearing only,
#      never modals/auxiliaries (question-to-imperative hazard)
#   3. transparent-code substitution: only codebook entries flagged
#      transparent (readable by frontier models without a glossary),
#      single-expansion only (the cr collision round-trip hazard),
#      never durations (the 3m months-vs-minutes hazard)
#   4. whitespace collapse
# Verification: numbers and capitalized tokens must survive 1:1 or the
# original text ships unchanged (fallback-on-any-doubt).

_FROZEN_RE = re.compile(
    r"```.*?```"            # code fences
    r"|`[^`]*`"             # inline code
    r'|"[^"]*"'             # double-quoted payloads
    r"|https?://\S+"        # URLs
    r"|\S+@\S+\.\S+"        # emails
    r"|(?:~|\.)?/[\w.~/-]+",  # file paths
    re.S)

_FILLER_RES = [
    re.compile(r"^(hey|hi|hello|yo|good (?:morning|afternoon|evening))[,!. ]+", re.I),
    re.compile(r"[ ]?\b(?:please|kindly)\b,?", re.I),
    re.compile(r"\b(?:i would like you to|i'd like you to|i want you to|i need you to|go ahead and)\b[ ]?", re.I),
    re.compile(r"[ ]?\b(?:when you get a chance|if you don't mind|thanks in advance)\b[,.]?", re.I),
    re.compile(r"[ ]?(?:thanks|thank you|thx|cheers)[!. ]*$", re.I),
]

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_CAP_RE = re.compile(r"\b[A-Z][a-zA-Z]+\b")


def compress_text(text: str, codebook: dict) -> dict:
    """Deterministic egress compression. Returns {text, changed, savings_est}.

    Falls back to the original on ANY verification doubt. Never compresses
    inside frozen spans, never emits ambiguous or duration shorthand.
    """
    original = text

    # 1. freeze literal spans
    frozen: list[str] = []
    def _freeze(m: re.Match) -> str:
        frozen.append(m.group(0))
        return f"\x00{len(frozen)-1}\x00"
    work = _FROZEN_RE.sub(_freeze, text)

    # 2. filler strip (remember what we removed so the verifier can exempt it)
    stripped_words: set[str] = set()
    for fr in _FILLER_RES:
        for m in fr.finditer(work):
            stripped_words |= set(_CAP_RE.findall(m.group(0)))
        work = fr.sub("", work)

    # 3. transparent-code substitution, longest expansion first
    subs = []
    for code, ent in codebook.items():
        if not ent.get("transparent") or len(ent.get("expansions", [])) != 1:
            continue
        exp = ent["expansions"][0]
        if len(code) + 3 >= len(exp):   # must be meaningfully shorter
            continue
        subs.append((exp, code))
    for exp, code in sorted(subs, key=lambda s: -len(s[0])):
        work = re.sub(r"\b" + re.escape(exp) + r"\b", code, work, flags=re.I)

    # 4. whitespace collapse + orphan punctuation from stripped trailers
    work = re.sub(r"[ \t]{2,}", " ", work)
    work = re.sub(r"\n{3,}", "\n\n", work).strip()
    work = re.sub(r"[,;]$", ".", work)

    # restore frozen spans
    def _thaw(m: re.Match) -> str:
        return frozen[int(m.group(1))]
    work = re.sub(r"\x00(\d+)\x00", _thaw, work)

    # verify: numbers and capitalized tokens (proper nouns) survive 1:1.
    # Codes may absorb capitalized words ("Claude Code" -> cc), so compare
    # against the re-expanded form, which restores them.
    reexpanded = expand_text(work, codebook)
    caps_needed = set(_CAP_RE.findall(original)) - stripped_words
    ok = (sorted(_NUM_RE.findall(original)) == sorted(_NUM_RE.findall(reexpanded))
          and caps_needed <= set(_CAP_RE.findall(reexpanded) + _CAP_RE.findall(work)))
    if not ok or not work:
        return {"text": original, "changed": False, "savings_est": 0}

    saved = max(0, _est_tokens(original) - _est_tokens(work))
    return {"text": work, "changed": work != original, "savings_est": saved}


def dedup_exact(text: str, context_texts: list[str], min_len: int = 120) -> str:
    """Replace any paragraph that appears byte-identical in recent context
    with a short reference marker. Provably lossless (exact match only)."""
    seen = set()
    for c in context_texts:
        for para in c.split("\n\n"):
            if len(para) >= min_len:
                seen.add(para.strip())
    out = []
    for para in text.split("\n\n"):
        if para.strip() in seen:
            out.append("[unchanged from my earlier message, same paragraph]")
        else:
            out.append(para)
    return "\n\n".join(out)


def log_egress(original: str, sent: str, surface: str) -> None:
    """Stats record for egress compression. Honest accounting note: these are
    user-string deltas; cli.py audit reports the assembled-call denominator."""
    try:
        rec = {"ts": round(time.time(), 1), "surface": surface, "kind": "egress",
               "orig_tokens": _est_tokens(original), "sent_tokens": _est_tokens(sent),
               "saved": max(0, _est_tokens(original) - _est_tokens(sent))}
        with STATS_PATH.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def check_response(a: Analysis, tool_calls: list[str]) -> str | None:
    """Silent-drop post-check: action was expected, did any matching call happen?

    tool_calls: list of tool names invoked during the turn. Mapping from tool
    name to action class is adapter-specific; here we do a substring match
    against class keywords as a prototype heuristic.
    """
    if a.decision not in ("manifest", "confirm") or not a.action_classes:
        return None
    CLASS_HINTS = {
        "scheduler": ("cron", "remind", "schedule", "timer"),
        "messaging": ("send", "message", "mail", "telegram", "notify"),
        "deletion": ("delete", "remove", "rm", "trash"),
        "calendar": ("calendar", "event", "morgen", "graph"),
        "payment": ("pay", "alpaca", "order", "stripe"),
        "publish": ("post", "publish"),
        "ops": ("deploy", "restart", "exec", "bash", "shell"),
    }
    called = " ".join(tool_calls).lower()
    missing = [c for c in a.action_classes
               if not any(h in called for h in CLASS_HINTS.get(c, ()))]
    if missing:
        return (f"pidgin silent-drop check: message implied {missing} action(s) "
                f"but no matching tool call was made. Verify nothing was dropped.")
    return None
