"""Versioned synthetic documents; immutable index generations and atomic pointer swaps.
No pickle, remote-code trust, document execution, or inventory-vector truth.
"""

import fcntl
import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import Field

from .config import settings
from .schemas import Strict


class Document(Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    topic: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    format: str = Field(pattern=r"^(txt|md)$")
    text: str = Field(min_length=1, max_length=32000)

    @property
    def version(self):
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]


class RAGError(Exception):
    pass


def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def chunks(doc):
    words = doc.text.split()
    out = []
    for start in range(0, len(words), 80):
        text = " ".join(words[start : start + 100])
        cid = hashlib.sha256(
            f"{doc.id}:{doc.version}:{start}:".encode() + text.encode()
        ).hexdigest()[:24]
        out.append(
            dict(chunk_id=cid, doc_id=doc.id, version=doc.version, topic=doc.topic, text=text)
        )
        if start + 100 >= len(words):
            break
    return out


@lru_cache(maxsize=2)
def encoder():
    import torch

    torch.set_num_threads(2)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        settings.embedding_model,
        revision=settings.embedding_revision,
        device="cpu",
        trust_remote_code=False,
    )
    model.max_seq_length = 256
    return model


def embedding_dimension():
    model = encoder()
    # sentence-transformers 6 renamed the accessor; support both spellings.
    getter = (
        getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    )
    return getter()


def embed(texts):
    return (
        encoder()
        .encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        .astype("float32")
    )


def identity():
    return {
        "model": settings.embedding_model,
        "revision": settings.embedding_revision,
        "dimension": embedding_dimension(),
        "normalization": "L2",
        "metric": "inner_product",
        "chunker": "words100_stride80_v1",
    }


@lru_cache(maxsize=1)
def reranker():
    import torch

    torch.set_num_threads(2)
    from sentence_transformers import CrossEncoder

    return CrossEncoder(
        settings.reranker_model,
        revision=settings.reranker_revision,
        device="cpu",
        trust_remote_code=False,
    )


class PineconeAdapter:
    """Fail-closed REST adapter. Never reports FAISS work as Pinecone success."""

    def __init__(self):
        import httpx

        if (
            not re.fullmatch(r"https://[a-zA-Z0-9.-]+\.pinecone\.io", settings.pinecone_host)
            or not settings.pinecone_api_key
        ):
            raise RAGError("Pinecone credentials/host missing or invalid")
        self.client = httpx.Client(
            base_url=settings.pinecone_host,
            timeout=20,
            headers={"Api-Key": settings.pinecone_api_key, "X-Pinecone-Api-Version": "2025-10"},
        )

    def post(self, path, data):
        try:
            r = self.client.post(path, json=data)
            r.raise_for_status()
            value = r.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except Exception as exc:
            raise RAGError("Pinecone operation failed; no fallback") from exc

    def replace(self, namespace, records, vectors):
        for i in range(0, len(records), 50):
            self.post(
                "/vectors/upsert",
                {
                    "namespace": namespace,
                    "vectors": [
                        {
                            "id": r["chunk_id"],
                            "values": v.tolist(),
                            "metadata": {"topic": r["topic"]},
                        }
                        for r, v in zip(records[i : i + 50], vectors[i : i + 50], strict=True)
                    ],
                },
            )

    def search(self, namespace, vector, k, topic):
        data = {
            "namespace": namespace,
            "vector": vector.tolist(),
            "topK": k,
            "includeMetadata": True,
        }
        if topic == "rental":
            data["filter"] = {
                "topic": {
                    "$in": ["rental_pickup", "rental_terms", "rental_changes", "rental_documents"]
                }
            }
        elif topic:
            data["filter"] = {"topic": {"$eq": topic}}
        result = self.post("/query", data)
        if not isinstance(result.get("matches"), list):
            raise RAGError("Invalid Pinecone query envelope")
        try:
            return [(str(m["id"]), float(m["score"])) for m in result["matches"]]
        except (TypeError, KeyError, ValueError) as exc:
            raise RAGError("Invalid Pinecone matches") from exc

    def delete_namespace(self, namespace):
        self.post("/vectors/delete", {"namespace": namespace, "deleteAll": True})

    def close(self):
        self.client.close()


class PolicyIndex:
    def __init__(self, path=None):
        self.path = Path(path or settings.rag_path)

    @contextmanager
    def writer(self):
        self.path.mkdir(parents=True, exist_ok=True)
        with (self.path / ".write.lock").open("w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def load(self):
        pointer = self.path / "CURRENT"
        if not pointer.exists():
            raise RAGError("Policy index unavailable; ingest synthetic corpus first")
        generation = pointer.read_text().strip()
        if not re.fullmatch(r"[a-f0-9]{32}", generation):
            raise RAGError("Invalid index generation")
        directory = self.path / generation
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest["identity"] != identity() or manifest["backend"] != settings.rag_backend:
            raise RAGError("Incompatible index configuration; rebuild explicitly")
        raw = (directory / "index.faiss").read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["index_sha256"]:
            raise RAGError("Corrupt FAISS index")
        return manifest, directory

    def ingest(self, documents=(), delete_ids=()):
        docs = [Document.model_validate(d) for d in documents]
        if sum(len(d.text.encode()) for d in docs) > 256000:
            raise RAGError("Ingestion batch exceeds 256KB")
        if len({d.id for d in docs}) != len(docs):
            raise RAGError("Duplicate document ID")
        with self.writer():
            old = None
            current = {}
            if (self.path / "CURRENT").exists():
                old, _ = self.load()
                current = {d["id"]: d for d in old["documents"]}
            for did in delete_ids:
                current.pop(did, None)
            for doc in docs:
                current[doc.id] = doc.model_dump()
            if len(current) > 200:
                raise RAGError("Document limit reached")
            records = [
                c
                for d in sorted(current.values(), key=lambda d: d["id"])
                for c in chunks(Document(**d))
            ]
            if len(records) > 2000:
                raise RAGError("Chunk limit reached")
            ident = identity()
            vectors = (
                embed([r["text"] for r in records])
                if records
                else np.empty((0, ident["dimension"]), dtype="float32")
            )
            import faiss

            index = faiss.IndexFlatIP(ident["dimension"])
            index.add(vectors)
            generation = uuid.uuid4().hex
            directory = self.path / generation
            directory.mkdir()
            faiss.write_index(index, str(directory / "index.faiss"))
            manifest = {
                "generation": generation,
                "identity": ident,
                "backend": settings.rag_backend,
                "documents": list(current.values()),
                "chunks": records,
                "index_sha256": hashlib.sha256(
                    (directory / "index.faiss").read_bytes()
                ).hexdigest(),
            }
            adapter = None
            try:
                if settings.rag_backend == "pinecone":
                    adapter = PineconeAdapter()
                    adapter.replace(generation, records, vectors)
                (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
                (self.path / "CURRENT.tmp").write_text(generation)
                os.replace(self.path / "CURRENT.tmp", self.path / "CURRENT")
                # Generation filtering already excludes stale content; remove remote old vectors explicitly.
                if adapter and old:
                    adapter.delete_namespace(old["generation"])
            finally:
                if adapter:
                    adapter.close()
            # Remove inactive local generations to avoid retaining deleted document text.
            import shutil

            # Only the previously active generation belongs to this replacement operation.
            # Never recursively remove arbitrary directories under a configured RAG_PATH.
            if old and old["generation"] != generation:
                previous = self.path / old["generation"]
                if previous.is_dir() and not previous.is_symlink():
                    shutil.rmtree(previous)
            return {
                "generation": generation,
                "documents": len(current),
                "chunks": len(records),
                "identity": ident,
                "backend": settings.rag_backend,
            }

    def retrieve(self, query, k=4, strategy="hybrid", topic=None, rerank=False):
        if not self.path.exists():
            raise RAGError("Policy index unavailable")
        # Readers hold a shared lock until all generation files are consumed.
        with (self.path / ".write.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            try:
                return self._retrieve(query, k, strategy, topic, rerank)
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise RAGError("Invalid or unavailable index generation") from exc
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _retrieve(self, query, k=4, strategy="hybrid", topic=None, rerank=False):
        if strategy not in {"lexical", "dense", "hybrid"}:
            raise RAGError("Unknown retrieval strategy")
        if not 1 <= k <= 20:
            raise RAGError("Invalid result count")
        manifest, directory = self.load()
        records = manifest["chunks"]
        if not records:
            return []
        import faiss
        from rank_bm25 import BM25Okapi

        vectors = faiss.read_index(str(directory / "index.faiss"))
        if vectors.d != manifest["identity"]["dimension"] or vectors.ntotal != len(records):
            raise RAGError("Index dimension/count mismatch")
        eligible = [
            i
            for i, r in enumerate(records)
            if topic is None
            or r["topic"] == topic
            or (topic == "rental" and r["topic"].startswith("rental_"))
        ]
        if not eligible:
            return []
        q = embed([query])[0]
        dense_scores = {}
        if settings.rag_backend == "pinecone":
            adapter = PineconeAdapter()
            try:
                matches = adapter.search(manifest["generation"], q, min(len(records), 100), topic)
            finally:
                adapter.close()
            lookup = {r["chunk_id"]: i for i, r in enumerate(records)}
            dense_scores = {
                lookup[cid]: score
                for cid, score in matches
                if cid in lookup and lookup[cid] in eligible
            }
        else:
            scores, ids = vectors.search(q.reshape(1, -1), len(records))
            dense_scores = {
                int(i): float(s) for i, s in zip(ids[0], scores[0], strict=True) if i in eligible
            }
        lexical = BM25Okapi([tokenize(records[i]["text"]) for i in eligible]).get_scores(
            tokenize(query)
        )
        lex_scores = dict(zip(eligible, map(float, lexical), strict=True))
        dense = sorted(dense_scores, key=lambda i: (-dense_scores[i], records[i]["chunk_id"]))
        lex = sorted(eligible, key=lambda i: (-lex_scores[i], records[i]["chunk_id"]))
        if strategy == "dense":
            order = dense
            values = dense_scores
        elif strategy == "lexical":
            order = lex
            values = lex_scores
        else:
            values = {i: 0.0 for i in eligible}
            for ranking in [dense, lex]:
                for rank, i in enumerate(ranking):
                    values[i] += 1 / (60 + rank + 1)
            order = sorted(eligible, key=lambda i: (-values[i], records[i]["chunk_id"]))
        if rerank and order:
            candidates = order[: min(12, len(order))]
            scores = reranker().predict([(query, records[i]["text"]) for i in candidates])
            values = {i: float(s) for i, s in zip(candidates, scores, strict=True)}
            order = sorted(candidates, key=lambda i: (-values[i], records[i]["chunk_id"]))
        return [
            {**records[i], "score": float(values[i]), "dense_score": dense_scores.get(i, -1.0)}
            for i in order[:k]
        ]

    def answer(self, query, topic=None):
        hits = self.retrieve(query, k=3, topic=topic, rerank=settings.rag_rerank)
        # Similarity is an abstention heuristic, not a proof of semantic answer support.
        return [h for h in hits if h["dense_score"] >= settings.rag_min_similarity]

    def rental_answer(self, query):
        hits = self.retrieve(query, k=3, topic="rental", rerank=settings.rag_rerank)
        return assess(query, hits)


# Imported last to avoid a cycle: rental_evidence is pure and imports nothing from here.
from .rental_evidence import assess  # noqa: E402


def accepted_rental(query, hits):
    return assess(query, hits)[0]
