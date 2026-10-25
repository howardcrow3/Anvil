"""Secret redaction for text that is persisted or forwarded (memory, logs, gateway replies).

Pattern set modeled on Hermes Agent's ``agent/redact.py`` (MIT, Nous Research). Deliberately
conservative: it targets well-known token shapes and ``NAME=value`` secrets, not arbitrary entropy.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),                       # Anthropic
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),                 # OpenAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),                   # GitHub classic
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),                 # GitHub fine-grained
    re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),                          # Hugging Face
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                             # AWS access key id
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),                # Slack
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),                  # Telegram bot token
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]
_BEARER = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._\-~+/]{16,}=*")
_ASSIGN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE[_-]?KEY)[A-Z0-9_]*)(\s*[=:]\s*)(['\"]?)([^\s'\"]{6,})\3"
)


def redact(text: str) -> str:
    """Return ``text`` with recognizable secrets replaced by ``[REDACTED]``."""
    if not text:
        return text
    for pat in _PATTERNS:
        text = pat.sub(REDACTED, text)
    text = _BEARER.sub(lambda m: m.group(1) + REDACTED, text)
    text = _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(3)}", text)
    return text
