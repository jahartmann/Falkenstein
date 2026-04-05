"""Input guard for prompt injection protection.

Fast regex-based pre-filter that runs BEFORE any LLM call.
Leans toward false negatives — better to let something through
than to block legitimate requests.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field


@dataclass
class GuardResult:
    action: str  # "ALLOW", "WARN", "BLOCK"
    reason: str = ""
    matched_pattern: str = ""


# Patterns that should be blocked outright
_BLOCK_PATTERNS: list[tuple[str, str]] = [
    # Instruction overrides
    (r"ignore\s+(?:all\s+)?previous\s+instructions?", "instruction override"),
    (r"disregard\s+(?:all\s+)?(?:previous\s+)?instructions?", "instruction override"),
    (r"forget\s+(?:all\s+)?(?:your\s+)?(?:previous\s+)?instructions?", "instruction override"),
    (r"override\s+(?:all\s+)?(?:previous\s+)?instructions?", "instruction override"),
    # Role hijacking
    (r"you\s+are\s+now\b", "role hijacking"),
    (r"pretend\s+to\s+be\b", "role hijacking"),
    (r"\bact\s+as\s+(?:a\s+|an\s+)?(?:hacker|ai without|evil|unfiltered|uncensored)", "role hijacking"),
    (r"\bjailbreak\b", "jailbreak attempt"),
    (r"\bDAN\b(?:\s+mode)?", "DAN jailbreak"),
    # System prompt extraction
    (r"show\s+(?:me\s+)?your\s+system\s+prompt", "system prompt extraction"),
    (r"repeat\s+(?:the\s+)?(?:text|instructions?|prompt)\s+(?:above|before)", "prompt extraction"),
    (r"print\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)\s+(?:verbatim|exactly|word for word)", "prompt extraction"),
    # Delimiter injection
    (r"---\s*END\s+SYSTEM\s*---", "delimiter injection"),
    (r"<\s*system\s*>", "system tag injection"),
    (r"\[SYSTEM\]", "system tag injection"),
    # Direct tool manipulation
    (r"call\s+tool\s+\w+\s+with\b", "tool override"),
]

# Patterns that should generate a warning but still allow through
_WARN_PATTERNS: list[tuple[str, str]] = [
    (r"\bsystem\s+prompt\b", "system prompt mention"),
    (r"\bbase64\b", "base64 mention"),
    (r"\beval\s*\(", "code eval"),
    (r"\bexec\s*\(", "code exec"),
]

# Minimum length for a base64 segment to be decoded and checked
_BASE64_MIN_LEN = 16
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


class InputGuard:
    """Regex-based pre-filter for prompt injection attacks."""

    def __init__(self) -> None:
        self._block: list[tuple[re.Pattern[str], str]] = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in _BLOCK_PATTERNS
        ]
        self._warn: list[tuple[re.Pattern[str], str]] = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in _WARN_PATTERNS
        ]

    def check_patterns(self, text: str) -> GuardResult:
        """Check input text against known injection patterns.

        Returns GuardResult with action ALLOW, WARN, or BLOCK.
        Decodes any Base64 segments and checks those too.
        """
        if not text:
            return GuardResult(action="ALLOW")

        # Check raw text first
        result = self._check_text(text)
        if result.action == "BLOCK":
            return result

        # Decode and check any Base64 segments embedded in the text
        decoded_result = self._check_base64_segments(text)
        if decoded_result.action == "BLOCK":
            return decoded_result
        if decoded_result.action == "WARN" and result.action == "ALLOW":
            return decoded_result

        return result

    def _check_text(self, text: str) -> GuardResult:
        """Check plain text against block and warn patterns."""
        for compiled, reason in self._block:
            m = compiled.search(text)
            if m:
                return GuardResult(
                    action="BLOCK",
                    reason=f"Blocked: {reason}",
                    matched_pattern=m.group(0),
                )

        for compiled, reason in self._warn:
            m = compiled.search(text)
            if m:
                return GuardResult(
                    action="WARN",
                    reason=f"Warning: {reason}",
                    matched_pattern=m.group(0),
                )

        return GuardResult(action="ALLOW")

    def _check_base64_segments(self, text: str) -> GuardResult:
        """Find Base64-looking segments, decode them, and re-check."""
        worst = GuardResult(action="ALLOW")

        for match in _BASE64_RE.finditer(text):
            segment = match.group(0)
            # Pad to valid Base64 length
            padding = (4 - len(segment) % 4) % 4
            try:
                decoded_bytes = base64.b64decode(segment + "=" * padding)
                decoded = decoded_bytes.decode("utf-8", errors="ignore")
            except Exception:
                continue

            if not decoded.strip():
                continue

            result = self._check_text(decoded)
            if result.action == "BLOCK":
                return GuardResult(
                    action="BLOCK",
                    reason=f"Base64-encoded injection: {result.reason}",
                    matched_pattern=result.matched_pattern,
                )
            if result.action == "WARN" and worst.action == "ALLOW":
                worst = GuardResult(
                    action="WARN",
                    reason=f"Base64-encoded suspicious content: {result.reason}",
                    matched_pattern=result.matched_pattern,
                )

        return worst
