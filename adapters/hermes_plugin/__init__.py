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
        if len(user_message) < 4 or user_message.startswith("/"):
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


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
