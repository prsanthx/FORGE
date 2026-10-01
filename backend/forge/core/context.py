"""Keep each model request small, and record the policy that did it.

Spill, de-duplication, and masking are independent. A sweep can turn one of
them off for every variant and compare the runs.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

POLICY_KEYS = ("spill", "dedupe_reads", "mask_old", "agents_md", "prompt_cache")

DEFAULTS: dict[str, Any] = {
    "spill": True,
    "dedupe_reads": True,
    "mask_old": True,
    "agents_md": True,
    "prompt_cache": True,
    "spill_chars": 3500,
    "spill_file_chars": 24000,
    "mask_chars": 12000,
    "preview_chars": 700,
}

_SPILL_ID = re.compile(r"s\d{4}")


def resolve_policy(cfg: dict[str, Any] | None, override: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(DEFAULTS)
    raw = (cfg or {}).get("context") or {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in policy and value is not None:
                policy[key] = value
    if override:
        for key, value in override.items():
            if key in policy and value is not None:
                policy[key] = value
    for key in POLICY_KEYS:
        policy[key] = bool(policy[key])
    for key in ("spill_chars", "spill_file_chars", "mask_chars", "preview_chars"):
        policy[key] = max(200, int(policy[key]))
    return policy


def load_agent_docs(root: Path) -> tuple[str, list[str]]:
    """AGENTS.md and CLAUDE.md, in that order, capped so the prefix stays stable."""
    chunks: list[str] = []
    found: list[str] = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace").strip()
        if not text:
            continue
        found.append(name)
        chunks.append(f"# {name}\n{text[:12000]}")
    return "\n\n".join(chunks), found


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ContextSession:
    def __init__(self, spill_dir: Path, policy: dict[str, Any], *, sandbox: str = "repo"):
        self.policy = policy
        self.sandbox = sandbox
        self.spill_dir = spill_dir
        self.spill_dir.mkdir(parents=True, exist_ok=True)
        self.reads: dict[str, dict[str, Any]] = {}
        self.spills = 0
        self.dedupes = 0
        self.masked = 0
        self.mask_before = 0
        self.mask_bucket = 0
        self.agents_files: list[str] = []
        self.system_prompt = ""
        self.cache_read = 0
        self.cache_write = 0
        self.prompt_tokens = 0

    def bind_system(self, base: str, guide: str) -> str:
        parts = [base.rstrip()]
        if self.policy["agents_md"] and guide.strip():
            parts.append("REPOSITORY_GUIDE:\n" + guide.strip())
        if self.policy["spill"]:
            parts.append(
                'Large incidental output is spilled. Page it with read_spill: {"id": "s0001", "start": 1, "end": 200}.'
            )
        parts.append(
            "Commands run only inside this project. pip install is not available. "
            "Checks import the project through PYTHONPATH and do not install packages."
        )
        self.system_prompt = "\n\n".join(parts)
        return self.system_prompt

    def note_cache(self, response: Any) -> None:
        self.cache_read += int(getattr(response, "cache_read_tokens", 0) or 0)
        self.cache_write += int(getattr(response, "cache_write_tokens", 0) or 0)
        self.prompt_tokens += int(getattr(response, "prompt_tokens", 0) or 0)

    def shape(self, name: str, args: dict[str, Any], result: str, *, root: Path) -> str:
        if name in {"write_file", "terminal"}:
            self.reads.clear()
        if name == "read_file" and self.policy["dedupe_reads"] and not args.get("start") and not args.get("end"):
            pointer = self._dedupe(root, str(args.get("path") or ""))
            if pointer:
                self.dedupes += 1
                return pointer
        if name == "read_spill":
            return result
        limit = int(self.policy["spill_file_chars"] if name == "read_file" else self.policy["spill_chars"])
        if self.policy["spill"] and name != "read_file" and len(result) > limit:
            return self._spill(name, result)
        if self.policy["spill"] and name == "read_file" and len(result) > limit:
            return self._spill(name, result)
        if name == "read_file":
            self._remember(root, str(args.get("path") or ""))
        return result

    def read_spill(self, spill_id: str, start: int | None, end: int | None) -> str:
        if not _SPILL_ID.fullmatch(spill_id or ""):
            return f"no spill {spill_id}"
        path = self.spill_dir / f"{spill_id}.txt"
        if not path.is_file():
            return f"no spill {spill_id}"
        lines = path.read_text(errors="replace").splitlines()
        first = max(1, int(start or 1))
        last = int(end or first + 199)
        if last < first:
            last = first
        chunk = lines[first - 1 : last]
        shown_last = first + len(chunk) - 1 if chunk else first - 1
        body = "\n".join(chunk)
        return f"{spill_id} lines {first}-{shown_last} of {len(lines)}\n{body}"

    def present_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.policy["mask_old"]:
            total = sum(len(str(step.get("result") or "")) for step in steps)
            threshold = int(self.policy["mask_chars"])
            bucket = total // threshold if threshold else 0
            if bucket > self.mask_bucket and len(steps) > 1:
                # Move the cut once per bucket so the cached prefix stays put between crossings.
                self.mask_bucket = bucket
                self.mask_before = max(self.mask_before, len(steps) - 1)
            self.masked = self.mask_before
        public = []
        for index, step in enumerate(steps):
            full = (not self.policy["mask_old"]) or index >= self.mask_before
            public.append(_public_step(step, full=full))
        return public

    def report(self) -> dict[str, Any]:
        prompt = self.prompt_tokens
        hit = round(self.cache_read / prompt, 4) if prompt else None
        return {
            "policy": {key: bool(self.policy[key]) for key in POLICY_KEYS},
            "thresholds": {
                "spill_chars": self.policy["spill_chars"],
                "spill_file_chars": self.policy["spill_file_chars"],
                "mask_chars": self.policy["mask_chars"],
            },
            "sandbox": self.sandbox,
            "agents_files": list(self.agents_files),
            "spills": self.spills,
            "dedupes": self.dedupes,
            "masked_observations": self.masked,
            "cache_read_tokens": self.cache_read,
            "cache_write_tokens": self.cache_write,
            "prompt_tokens": prompt,
            "hit_rate": hit,
            "checks": "pytest runs inside the project with PYTHONPATH set. pip install is blocked.",
        }

    def _dedupe(self, root: Path, relative: str) -> str | None:
        path = _safe(root, relative)
        if path is None or not path.is_file():
            return None
        digest = file_digest(path)
        previous = self.reads.get(relative)
        if previous and previous["digest"] == digest:
            return (
                f"unchanged: {relative} matches the earlier read ({previous['digest'][:12]}). "
                "Body omitted. A write or command clears this."
            )
        self.reads[relative] = {"digest": digest, "step": self.spills + self.dedupes + len(self.reads)}
        return None

    def _remember(self, root: Path, relative: str) -> None:
        path = _safe(root, relative)
        if path is None or not path.is_file() or relative in self.reads:
            return
        self.reads[relative] = {"digest": file_digest(path), "step": len(self.reads) + 1}

    def _spill(self, name: str, result: str) -> str:
        self.spills += 1
        spill_id = f"s{self.spills:04d}"
        (self.spill_dir / f"{spill_id}.txt").write_text(result)
        preview = int(self.policy["preview_chars"])
        head = result[:preview]
        tail = result[-preview:] if len(result) > preview else ""
        lines = result.count("\n") + 1
        tail_block = f"\n--- tail ---\n{tail}" if tail else ""
        return (
            f"spilled {name} ({len(result)} chars, {lines} lines) as {spill_id}. "
            f"Page the rest with read_spill.\n--- head ---\n{head}{tail_block}"
        )


def _public_step(step: dict[str, Any], *, full: bool) -> dict[str, Any]:
    result = str(step.get("result") or "")
    if not full:
        first = ""
        for line in result.splitlines():
            if line.strip():
                first = line.strip()[:160]
                break
        action = step.get("action") or "tool"
        flag = "ok" if step.get("ok") else "failed"
        result = f"[masked] {action} {flag} {first}".strip()
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    return {
        "action": step.get("action"),
        "args": {key: value for key, value in args.items() if key != "content"},
        "ok": step.get("ok"),
        "thought": step.get("thought") or "",
        "result": result,
    }


def _safe(root: Path, relative: str) -> Path | None:
    rel = (relative or "").strip().lstrip("/")
    if not rel:
        return None
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        return None
    return candidate
