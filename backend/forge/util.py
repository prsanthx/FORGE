"""Small helpers shared across the harness."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any


def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:12]
    return f"{prefix}{token}" if not prefix else f"{prefix}_{token}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_tokens(text: str) -> int:
    """Rough token estimate used when a provider does not report usage."""
    return max(1, (len(text) + 3) // 4) if text else 0


def extract_json(text: str) -> Any:
    """Pull a JSON object out of a model response, including fenced blocks."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response did not contain a JSON object")
    blob = raw[start : end + 1]
    blob = re.sub(r",\s*([}\]])", r"\1", blob)
    return json.loads(blob)


def shorten(text: str, limit: int = 90) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def redact(text: str, secret: str | None) -> str:
    if not text or not secret:
        return text or ""
    return text.replace(secret, "***")
