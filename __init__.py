"""pidgin-gate: Hermes adapter for the pidgin action-gated confidence check.

Thin wrapper over ~/.hermes/pidgin/core.py (the shared, stack-agnostic core).
Injects the shorthand gloss + gate instruction as a context section, the same
mechanism skill-hint-inject uses.

Tunables (env):
  HERMES_PIDGIN_GATE          default 1 (set 0 to disable)
  HERMES_PIDGIN_CODEBOOK      default ~/.hermes/pidgin/codebook.yaml
  HERMES_PIDGIN_SKIP_CRON     default 1 (cron prompts are pre-engineered)

Fail-open everywhere: any exception means no injection, never a block.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# install.sh stamps the clone path over the sentinel when it copies this
# plugin into ~/.hermes/plugins/. Env var wins; default is the classic home.
_raw = os.getenv("HERMES_PIDGIN_DIR") or "__PIDGIN_DIR__"
PIDGIN_DIR = (Path(_raw) if not _raw.startswith("__")
              else Path.home() / ".hermes" / "pidgin")
sys.path.insert(0, str(PIDGIN_DIR))

try:
    from core import (analyze, load_codebook, load_config,  # noqa: E402
                      log_event, render_context, transparency_line)
    _IMPORT_OK = True
except Exception as exc:  # pragma: no cover
    logger.debug("pidgin-gate: core import failed: %s", exc)
    _IMPORT_OK = False

_BOOK = None
_BOOK_MTIME = 0.0


def _flag_on(name: str, default: bool = True) -> bool:
    val = (os.getenv(name) or "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _codebook():
    """Load the codebook, hot-reloading when the file changes (watchdog pattern)."""
    global _BOOK, _BOOK_MTIME
    path = Path(os.getenv("HERMES_PIDGIN_CODEBOOK") or PIDGIN_DIR / "codebook.yaml")
    mtime = path.stat().st_mtime
    if _BOOK is None or mtime != _BOOK_MTIME:
        _BOOK = load_codebook(path)
        _BOOK_MTIME = mtime
    return _BOOK


def _on_pre_llm_call(**kwargs):
    try:
        if not _IMPORT_OK or not _flag_on("HERMES_PIDGIN_GATE"):
            return None
        if not load_config().get("enabled", True):
            return None
        platform = (kwargs.get("platform") or "").lower()
        if _flag_on("HERMES_PIDGIN_SKIP_CRON") and platform == "cron":
            return None
        user_message = kwargs.get("user_message") or ""
        # skip slash commands and system-constructed turns (image descriptions,
        # continuation markers: "[The user sent an image~...", "[System: ...]").
        # Glossing synthetic text has no value and OCR-ish content trips the
        # unknown-shorthand heuristic (real case: VIN/VW from a service photo).
        if len(user_message) < 4 or user_message.startswith(("/", "[")):
            return None
        a = analyze(user_message, _codebook())
        log_event(a, surface=f"hermes:{platform or 'unknown'}")
        ctx = render_context(a)
        if not ctx:
            return None
        if load_config().get("transparency"):
            line = transparency_line(a)
            if line:
                ctx += ("\n\nTRANSPARENCY MODE IS ON: append this exact line, "
                        "in brackets, as the final line of your reply: [" + line + "]")
        return {"context": ctx}
    except Exception as exc:
        logger.debug("pidgin-gate: hook failed: %s", exc)
        return None


def _handle_pidgin(raw_args: str) -> str:
    """Slash command: /pidgin [on|off | egress on|off | show on|off | stats N]."""
    if not _IMPORT_OK:
        return "pidgin core not importable; check " + str(PIDGIN_DIR)
    try:
        from core import load_config, save_config, status_text
        args = (raw_args or "").strip().lower().split()
        if args:
            cfg = load_config()
            if args[0] in ("on", "off"):
                cfg["enabled"] = args[0] == "on"
                save_config(cfg)
                return f"pidgin master switch: {args[0]}"
            if args[0] == "egress" and len(args) > 1 and args[1] in ("on", "off"):
                cfg["egress"] = args[1] == "on"
                save_config(cfg)
                return f"egress compression: {args[1]}"
            if args[0] == "show" and len(args) > 1 and args[1] in ("on", "off"):
                cfg["transparency"] = args[1] == "on"
                save_config(cfg)
                return f"translation line: {'shown' if args[1] == 'on' else 'hidden'}"
            if args[0] == "stats":
                days = float(args[1]) if len(args) > 1 else 7.0
                return status_text(days)
            if args[0] == "proposals":
                import miner
                props = (miner._load_yaml(miner.PROPOSALS).get("proposals") or {})
                if not props:
                    return "no proposals pending. run a scan with: /pidgin scan"
                lines = [f"{len(props)} proposal(s) pending:"]
                for code, p in props.items():
                    exp = p.get("expansion") or "?"
                    lines.append(f"  {code} = {exp} [{p.get('kind','?')}]")
                lines.append("approve: /pidgin approve <code> [expansion]")
                lines.append("reject:  /pidgin reject <code>")
                return "\n".join(lines)
            if args[0] == "scan":
                import miner
                days = float(args[1]) if len(args) > 1 else 30.0
                props = miner.scan(days)
                return f"scanned {days:g}d of history: {len(props)} proposal(s). /pidgin proposals to review."
            if args[0] == "approve" and len(args) > 1:
                import io, contextlib, miner
                # raw_args preserves case for the expansion text
                rest = raw_args.strip().split(None, 2)
                expansion = rest[2] if len(rest) > 2 else None
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    miner.approve(args[1], expansion)
                return buf.getvalue().strip() or "done"
            if args[0] == "reject" and len(args) > 1:
                import io, contextlib, miner
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    miner.reject(args[1])
                return buf.getvalue().strip() or "done"
            return ("Usage: /pidgin | on|off | egress on|off | show on|off | "
                    "stats [days] | proposals | scan [days] | "
                    "approve <code> [expansion] | reject <code>")
        return status_text()
    except Exception as exc:
        return f"pidgin status failed: {exc}"


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    try:
        ctx.register_command(
            "pidgin",
            handler=_handle_pidgin,
            description="Pidgin token layer: status, toggles, stats.",
            args_hint="[on|off | egress on|off | show on|off | stats N]",
        )
    except Exception as exc:  # older cores without register_command: hook still works
        logger.debug("pidgin-gate: command registration failed: %s", exc)
