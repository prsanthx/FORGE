"""Index a Python repo into a file / symbol / module / dependency / test graph."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import networkx as nx

from forge.db import Database

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    "data",
}


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_test(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


class KnowledgeGraph:
    def __init__(self, db: Database, repo_id: str):
        self.db = db
        self.repo_id = repo_id
        self.graph = nx.DiGraph()

    def clear(self) -> None:
        self.db.execute("DELETE FROM kg_nodes WHERE repo_id = ?", (self.repo_id,))
        self.db.execute("DELETE FROM kg_edges WHERE repo_id = ?", (self.repo_id,))
        self.graph.clear()

    def index(self, root: Path) -> dict:
        root = root.resolve()
        self.clear()
        files = [
            path
            for path in root.rglob("*.py")
            if not any(part in SKIP_DIRS for part in path.parts)
        ]
        modules: dict[str, str] = {}
        for path in files:
            module = _module_name(root, path)
            modules[module] = str(path.relative_to(root))
        for path in files:
            self._index_file(root, path, modules)
        self._persist()
        return self.stats()

    def _add_node(self, node_id: str, **attrs) -> None:
        self.graph.add_node(node_id, **attrs)

    def _add_edge(self, src: str, dst: str, rel: str) -> None:
        if src == dst:
            return
        self.graph.add_edge(src, dst, rel=rel)

    def _index_file(self, root: Path, path: Path, modules: dict[str, str]) -> None:
        rel = str(path.relative_to(root))
        source = path.read_text(errors="replace")
        module = _module_name(root, path)
        file_id = f"file:{rel}"
        module_id = f"module:{module}"
        self._add_node(
            file_id,
            kind="file",
            name=path.name,
            qualname=rel,
            file=rel,
            line=1,
            signature=rel,
            doc="",
            snippet="\n".join(source.splitlines()[:12]),
        )
        self._add_node(
            module_id,
            kind="module",
            name=module.split(".")[-1] if module else path.stem,
            qualname=module,
            file=rel,
            line=1,
            signature=module,
            doc="",
            snippet="",
        )
        self._add_edge(module_id, file_id, "defined_in")
        if _is_test(path):
            test_id = f"test:{rel}"
            self._add_node(
                test_id,
                kind="test",
                name=path.name,
                qualname=rel,
                file=rel,
                line=1,
                signature=rel,
                doc="test module",
                snippet="",
            )
            self._add_edge(test_id, module_id, "tests")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        self._walk(tree, source.splitlines(), rel, module_id, file_id, modules)

    def _walk(
        self,
        tree: ast.AST,
        lines: list[str],
        rel: str,
        module_id: str,
        file_id: str,
        modules: dict[str, str],
    ) -> None:
        for node in tree.body if isinstance(tree, ast.Module) else []:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._index_import(node, module_id, file_id, rel, modules)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._index_symbol(node, lines, rel, module_id, file_id, prefix="")

    def _index_import(
        self,
        node: ast.Import | ast.ImportFrom,
        module_id: str,
        file_id: str,
        rel: str,
        modules: dict[str, str],
    ) -> None:
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            base = node.module or ""
            names = [base] if base else []
            for alias in node.names:
                if base:
                    names.append(f"{base}.{alias.name}")
        is_test = _is_test(Path(rel))
        for name in names:
            if not name:
                continue
            target_module = name
            while target_module and target_module not in modules:
                if "." not in target_module:
                    target_module = ""
                    break
                target_module = target_module.rsplit(".", 1)[0]
            if target_module:
                dst = f"module:{target_module}"
                self._add_node(
                    dst,
                    kind="module",
                    name=target_module.split(".")[-1],
                    qualname=target_module,
                    file=modules.get(target_module, ""),
                    line=1,
                    signature=target_module,
                    doc="",
                    snippet="",
                )
                self._add_edge(module_id, dst, "imports")
                if is_test:
                    self._add_edge(file_id, dst, "tests")
            else:
                root_name = name.split(".")[0]
                dst = f"dep:{root_name}"
                self._add_node(
                    dst,
                    kind="dependency",
                    name=root_name,
                    qualname=root_name,
                    file="",
                    line=node.lineno,
                    signature=root_name,
                    doc="external import",
                    snippet="",
                )
                self._add_edge(module_id, dst, "depends")

    def _index_symbol(
        self,
        node: ast.AST,
        lines: list[str],
        rel: str,
        module_id: str,
        file_id: str,
        prefix: str,
    ) -> None:
        name = getattr(node, "name", "")
        qual = f"{prefix}.{name}" if prefix else name
        kind = "symbol"
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        snippet = "\n".join(lines[start - 1 : min(end, start - 1 + 25)])
        doc = ast.get_docstring(node) or ""
        signature = lines[start - 1].strip() if start - 1 < len(lines) else f"def {name}"
        node_id = f"symbol:{rel}:{qual}"
        self._add_node(
            node_id,
            kind=kind,
            name=name,
            qualname=qual,
            file=rel,
            line=start,
            signature=signature,
            doc=doc.splitlines()[0] if doc else "",
            snippet=snippet,
        )
        self._add_edge(file_id, node_id, "contains")
        self._add_edge(module_id, node_id, "defines")
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._index_symbol(child, lines, rel, module_id, file_id, qual)

    def _persist(self) -> None:
        conn_sql_nodes = []
        for node_id, attrs in self.graph.nodes(data=True):
            conn_sql_nodes.append(
                (
                    self.repo_id,
                    node_id,
                    attrs.get("kind"),
                    attrs.get("name"),
                    attrs.get("qualname"),
                    attrs.get("file"),
                    attrs.get("line") or 0,
                    attrs.get("signature"),
                    attrs.get("doc"),
                    attrs.get("snippet"),
                )
            )
        edges = [
            (self.repo_id, src, dst, data.get("rel") or "related")
            for src, dst, data in self.graph.edges(data=True)
        ]
        # executemany under the db lock
        with self.db._lock:
            self.db._conn.executemany(
                """INSERT OR REPLACE INTO kg_nodes
                   (repo_id, node_id, kind, name, qualname, file, line, signature, doc, snippet)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                conn_sql_nodes,
            )
            self.db._conn.executemany(
                "INSERT OR REPLACE INTO kg_edges (repo_id, src, dst, rel) VALUES (?, ?, ?, ?)",
                edges,
            )
            self.db._conn.commit()

    def load(self) -> None:
        self.graph.clear()
        for row in self.db.query("SELECT * FROM kg_nodes WHERE repo_id = ?", (self.repo_id,)):
            self.graph.add_node(
                row["node_id"],
                kind=row["kind"],
                name=row["name"],
                qualname=row["qualname"],
                file=row["file"],
                line=row["line"],
                signature=row["signature"],
                doc=row["doc"],
                snippet=row["snippet"],
            )
        for row in self.db.query("SELECT * FROM kg_edges WHERE repo_id = ?", (self.repo_id,)):
            self.graph.add_edge(row["src"], row["dst"], rel=row["rel"])

    def stats(self) -> dict:
        if self.graph.number_of_nodes() == 0:
            self.load()
        kinds: dict[str, int] = {}
        for _, attrs in self.graph.nodes(data=True):
            kinds[attrs.get("kind") or "unknown"] = kinds.get(attrs.get("kind") or "unknown", 0) + 1
        rels: dict[str, int] = {}
        for _, _, data in self.graph.edges(data=True):
            rels[data.get("rel") or "related"] = rels.get(data.get("rel") or "related", 0) + 1
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "kinds": kinds,
            "relations": rels,
        }


def index_repo(db: Database, repo_id: str, root: Path) -> dict:
    graph = KnowledgeGraph(db, repo_id)
    return graph.index(root)
