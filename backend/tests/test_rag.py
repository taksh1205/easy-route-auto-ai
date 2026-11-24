import json
import os
from pathlib import Path

import httpx
import pytest
from app.config import settings
from app.rag import Document, PineconeAdapter, PolicyIndex, RAGError, chunks


def test_chunking_stable_and_safe_limits():
    doc = Document(
        id="sample",
        topic="procedures",
        format="txt",
        text=" ".join("word" + str(i) for i in range(220)),
    )
    assert chunks(doc) == chunks(doc) and len(chunks(doc)) == 3
    assert len(chunks(doc)[0]["text"].split()) == 100
    with pytest.raises(ValueError):
        Document(id="../secret", topic="x", format="pdf", text="x")
    with pytest.raises(ValueError):
        Document(id="x", topic="x", format="txt", text="x" * 32001)


def test_pinecone_explicit_errors_and_contract(monkeypatch):
    monkeypatch.setattr(settings, "pinecone_host", "https://demo.svc.pinecone.io")
    monkeypatch.setattr(settings, "pinecone_api_key", "mock")
    requests = []
    original = httpx.Client

    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200, json={"matches": [{"id": "chunk", "score": 0.8}]})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    import numpy as np

    adapter = PineconeAdapter()
    assert adapter.search("generation", np.array([1.0, 0.0]), 3, "warranties") == [("chunk", 0.8)]
    assert requests[0]["filter"] == {"topic": {"$eq": "warranties"}}
    adapter.close()
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kw),
    )
    with pytest.raises(RAGError, match="no fallback"):
        PineconeAdapter().search("generation", np.array([1.0, 0.0]), 3, None)


NEURAL = pytest.mark.skipif(
    os.environ.get("EASY_RUN_NEURAL") != "1",
    reason="Actual learned-model tests require EASY_RUN_NEURAL=1; no mocked substitute",
)


@pytest.mark.neural
@NEURAL
def test_actual_neural_ingestion_retrieval_update_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "rag_backend", "faiss")
    index = PolicyIndex(tmp_path / "index")
    docs = [
        {
            "id": "appointments",
            "topic": "appointments",
            "format": "md",
            "text": "Synthetic appointments require an explicit confirmation and a committed booking record. Appointments start at nine in the morning.",
        },
        {
            "id": "warranty",
            "topic": "warranties",
            "format": "txt",
            "text": "Synthetic warranty coverage must be checked in the written agreement. No coverage is guaranteed by this demo.",
        },
    ]
    unrelated = index.path / "unrelated-user-data"
    unrelated.mkdir(parents=True)
    (unrelated / "keep.txt").write_text("keep")
    meta = index.ingest(docs)
    assert meta["identity"]["dimension"] == 384 and meta["backend"] == "faiss"
    for strategy in ["lexical", "dense", "hybrid"]:
        hits = index.retrieve("When do appointments start?", strategy=strategy, k=2)
        assert hits[0]["doc_id"] == "appointments" and all(h["chunk_id"] for h in hits)
    assert all(h["topic"] == "warranties" for h in index.retrieve("booking", topic="warranties"))
    before = {c["chunk_id"] for c in index.load()[0]["chunks"] if c["doc_id"] == "appointments"}
    docs[0]["text"] = "Updated synthetic appointments start at ten in the morning."
    index.ingest([docs[0]])
    assert not before & {c["chunk_id"] for c in index.load()[0]["chunks"]}
    index.ingest(delete_ids=["appointments"])
    assert {c["doc_id"] for c in index.load()[0]["chunks"]} == {"warranty"}
    index.ingest(delete_ids=["warranty"])
    assert index.retrieve("booking") == []
    assert (unrelated / "keep.txt").read_text() == "keep"


@pytest.mark.neural
@NEURAL
def test_incompatible_index_rejected(tmp_path, monkeypatch):
    index = PolicyIndex(tmp_path / "index")
    index.ingest(
        [
            {
                "id": "x",
                "topic": "x",
                "format": "txt",
                "text": "Synthetic test policy for appointments.",
            }
        ]
    )
    manifest, directory = index.load()
    manifest["identity"]["dimension"] = 3
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RAGError, match="Incompatible"):
        index.retrieve("appointments")


@pytest.mark.neural
@NEURAL
def test_assistant_policy_citations_and_abstention(client, tmp_path, monkeypatch):
    from .test_workflows import chat, session

    monkeypatch.setattr(settings, "rag_path", str(tmp_path / "index"))
    docs = json.loads(
        (Path(__file__).resolve().parents[1] / "corpus/synthetic_policies.json").read_text()
    )
    index = PolicyIndex()
    index.ingest(docs)
    cid, h = session(client)
    r = chat(client, cid, h, "What is the warranty policy?")
    assert r.status_code == 200, r.text
    assert r.json()["citations"] and any(c["doc_id"] == "warranties" for c in r.json()["citations"])
    monkeypatch.setattr(settings, "rag_min_similarity", 1.1)
    r = chat(client, cid, h, "What is the warranty policy?").json()
    assert not r["citations"] and "sufficient" in r["reply"]


@pytest.mark.neural
@NEURAL
def test_neural_vehicle_preference_matching(client, monkeypatch):
    from app.db import SessionLocal
    from app.schemas import Search
    from app.services import inventory

    monkeypatch.setattr(settings, "semantic_ranking", True)
    with SessionLocal() as db:
        rows = inventory(db, Search(max_price=20000, semantic_query="fuel economy hybrid car"))
    assert rows and all(v["price"] <= 20000 for v in rows)
    assert any(v["score_components"]["semantic"] > 0 for v in rows)
