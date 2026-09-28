"""Knowledge graph index, neighbor retrieval, and context-pack budget."""

from forge.db import Database
from forge.kg.indexer import index_repo
from forge.kg.query import GraphRetriever
from forge.settings import EXAMPLE_REPO


def test_index_example_repo_finds_symbols_imports_and_tests(tmp_path):
    db = Database(tmp_path / "kg.db")
    stats = index_repo(db, "repo_test", EXAMPLE_REPO)
    assert stats["nodes"] > 5
    assert stats["edges"] > 3
    assert stats["kinds"].get("symbol", 0) >= 4
    assert stats["kinds"].get("test", 0) >= 1
    assert stats["relations"].get("imports", 0) >= 1
    retriever = GraphRetriever(db, "repo_test")
    hits = retriever.search("TodoStore add", limit=5)
    names = {hit["qualname"] for hit in hits}
    assert any("add" in (name or "") for name in names)
    # Graph RAG pulls the file or module sitting next to the symbol.
    kinds = {hit["kind"] for hit in hits}
    assert "symbol" in kinds
    assert kinds & {"file", "module"}
    pack = retriever.context_pack("mark_done TodoStore", budget=500)
    assert "CONTEXT PACK:" in pack
    assert "TodoStore" in pack or "store.py" in pack
    assert len(pack) <= 500
