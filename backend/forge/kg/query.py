"""Graph retrieval and compressed context packs for small models."""

from __future__ import annotations

import re

from forge.db import Database
from forge.kg.indexer import KnowledgeGraph

_STOP = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "your",
    "todo",
    "when",
    "please",
    "add",
    "keep",
    "working",
}


def _tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", text or "")
    out = []
    for token in raw:
        low = token.lower()
        if low in _STOP or len(low) < 3:
            continue
        out.append(low)
    return out


class GraphRetriever:
    def __init__(self, db: Database, repo_id: str):
        self.kg = KnowledgeGraph(db, repo_id)
        self.kg.load()

    def search(self, query: str, limit: int = 8) -> list[dict]:
        tokens = _tokens(query)
        if self.kg.graph.number_of_nodes() == 0:
            return []
        scored: list[tuple[float, str]] = []
        for node_id, attrs in self.kg.graph.nodes(data=True):
            if attrs.get("kind") not in {"symbol", "file", "module", "test"}:
                continue
            blob = " ".join(
                str(attrs.get(key) or "")
                for key in ("name", "qualname", "file", "signature", "doc")
            ).lower()
            score = 0.0
            name = str(attrs.get("name") or "").lower()
            for token in tokens:
                if token == name:
                    score += 6
                elif token in name:
                    score += 3
                elif token in blob:
                    score += 1
            if attrs.get("kind") == "symbol" and score:
                score += 0.5
            if score > 0:
                scored.append((score, node_id))
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen: list[str] = []
        seen: set[str] = set()
        for _, node_id in scored[:limit]:
            if node_id not in seen:
                chosen.append(node_id)
                seen.add(node_id)
            # One-hop graph RAG: pull neighbors so a small model sees the module
            # around a symbol, not only the symbol that matched the query.
            for neighbor in list(self.kg.graph.successors(node_id)) + list(self.kg.graph.predecessors(node_id)):
                if neighbor in seen:
                    continue
                if self.kg.graph.nodes[neighbor].get("kind") in {"symbol", "file", "module"}:
                    chosen.append(neighbor)
                    seen.add(neighbor)
                if len(chosen) >= limit * 2:
                    break
        hits = []
        for node_id in chosen[: limit * 2]:
            attrs = dict(self.kg.graph.nodes[node_id])
            attrs["id"] = node_id
            hits.append(attrs)
        return hits

    def context_pack(self, query: str, budget: int = 2800) -> str:
        hits = self.search(query, limit=6)
        if not hits:
            return ""
        lines = ["CONTEXT PACK:"]
        used = len(lines[0])
        for hit in hits:
            header = f"- {hit.get('kind')} {hit.get('qualname') or hit.get('name')} ({hit.get('file')}:{hit.get('line')})"
            sig = f"  sig: {hit.get('signature') or ''}".rstrip()
            doc = f"  doc: {hit.get('doc')}" if hit.get("doc") else ""
            snippet = hit.get("snippet") or ""
            snippet_lines = snippet.splitlines()[:12]
            block = "\n".join([header, sig, *([doc] if doc else []), *snippet_lines]).strip()
            if used + len(block) + 1 > budget:
                break
            lines.append(block)
            used += len(block) + 1
        return "\n".join(lines)

    def file_hints(self) -> list[str]:
        files = [
            attrs.get("file")
            for _, attrs in self.kg.graph.nodes(data=True)
            if attrs.get("kind") == "file" and attrs.get("file")
        ]
        # Prefer implementation files over tests.
        files = sorted(files, key=lambda path: (path.startswith("tests/"), path))
        return files[:8]

    def summary(self) -> str:
        stats = self.kg.stats()
        files = self.file_hints()
        symbols = [
            attrs.get("qualname")
            for _, attrs in self.kg.graph.nodes(data=True)
            if attrs.get("kind") == "symbol"
        ][:12]
        return (
            f"nodes={stats['nodes']} edges={stats['edges']} kinds={stats['kinds']}\n"
            f"files: {', '.join(files)}\n"
            f"symbols: {', '.join(symbols)}"
        )
