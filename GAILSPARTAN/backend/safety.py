"""Small, deterministic input safety checks for the local demo.

This module is intentionally narrow.  It reduces obvious abusive or prompt-
injection-like input before retrieval, but it is not a replacement for
authorization, malware scanning, or a full content-safety system.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SafetyResult:
    allowed: bool
    category: str | None = None
    message: str | None = None


# Keep the list short and explicit for the public demo.  The goal is to catch
# obvious cases without pretending that keyword matching understands context.
_ABUSE_PATTERNS = (
    re.compile(r"\b(?:kill|hurt)\s+(?:yourself|someone)\b", re.IGNORECASE),
    re.compile(r"\bgo\s+to\s+hell\b", re.IGNORECASE),
)
_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|earlier)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:all\s+)?(?:previous|prior|earlier)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\breveal\s+(?:the\s+)?(?:system|hidden)\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+message\b", re.IGNORECASE),
)


def check_input(text: str, *, max_length: int = 4000) -> SafetyResult:
    """Return a stable allow/refuse decision for a user question."""

    normalized = (text or "").strip()
    if not normalized:
        return SafetyResult(False, "empty", "Enter a question before submitting it.")
    if len(normalized) > max_length:
        return SafetyResult(
            False,
            "too_long",
            f"Questions must be {max_length} characters or fewer.",
        )
    if any(pattern.search(normalized) for pattern in _INJECTION_PATTERNS):
        return SafetyResult(
            False,
            "prompt_injection",
            "That instruction cannot be processed as a document question.",
        )
    if any(pattern.search(normalized) for pattern in _ABUSE_PATTERNS):
        return SafetyResult(
            False,
            "abusive_language",
            "Please rephrase the request in neutral language.",
        )
    return SafetyResult(True)
