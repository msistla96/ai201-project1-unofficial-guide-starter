"""
retriever.py — Retrieval stage (see Architecture diagram).

Implements the hybrid retrieval approach from planning.md:

  - Semantic search : ChromaDB + all-MiniLM-L6-v2 (cosine distance)
  - Keyword search  : BM25 over the same chunk corpus (rank_bm25)
  - Fusion          : Reciprocal Rank Fusion (RRF) combines the two rankings,
                      avoiding the scale mismatch between cosine distance and
                      BM25 scores
  - Metadata filter : optional `where` clause (e.g. {"source_type": "reddit"})

Each result carries the semantic distance, BM25 score, the fused score, and the
chunk's metadata so they can be displayed (display_results / test_retrieval).

Run the evaluation harness over the planning.md test questions:
    python retriever.py
"""

import re
import logging

from config import N_RESULTS
from embeddings import get_collection, load_chunks, flatten_metadata

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # surface a clear message rather than an obscure NameError
    BM25Okapi = None

logger = logging.getLogger(__name__)

RRF_K = 60          # RRF dampening constant (standard default)
CANDIDATE_POOL = 20  # candidates pulled from each retriever before fusion

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Test questions from the Evaluation Plan in planning.md (specific, off-topic,
# and vague — to check the system uses retrieved context rather than its own
# knowledge).
EVAL_QUESTIONS = [
    "What documents do I need for a greencard application if I am married to a US citizen but I live outside of the US?",
    #"How long does premium processing take for J1 visas and how much does it cost?",
    "How do I know if I will be eligible for H1B lottery in 2026 under Masters degree quota in STEM?",
    "I did not receive my EAD card I applied for under H4 visa. USCIS portal shows that it's mailed. What do I do?",
    #"I got rejected in my F1 visa application and I have classes coming up in a month? How do I reapply with this in mind?",
    "How do I apply for a Schengen Visa?",          # off-topic
    "What is the weather?",                         # off-topic
]



def _tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def _matches(metadata, where):
    """Python-side equality filter for BM25 (mirrors Chroma's simple `where`)."""
    if not where:
        return True
    return all(metadata.get(k) == v for k, v in where.items())

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MetadataFilter:
    sources:    list[str]        = field(default_factory=list)
    date_gte:   Optional[str]    = None  # "YYYY-MM-DD"
    date_lte:   Optional[str]    = None

    def to_where(self) -> dict | None:
        """Convert to a ChromaDB $and where clause. Returns None if empty."""
        conditions = []

        if self.sources:
            conditions.append({"source_type": {"$in": self.sources}})
        if self.date_gte:
            conditions.append({"date": {"$gte": self.date_gte}})
        if self.date_lte:
            conditions.append({"date": {"$lte": self.date_lte}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

class Retriever:
    """Hybrid (semantic + BM25) retriever over the chunk collection."""

    def __init__(self):
        self.collection = get_collection()
        # BM25 needs the full corpus in memory; load it from the same chunks
        # file the index was built from.
        if BM25Okapi is None:
            raise ImportError("rank-bm25 is not installed. `pip install rank-bm25`")
        self.chunks = load_chunks()
        self.bm25 = BM25Okapi([_tokenize(c["text"]) for c in self.chunks])

    # --- individual strategies ---------------------------------------------

    def _fetch_post_context(self, post_id):
        """Return the post-level chunk(s) (title + body) for a given post_id."""
        res = self.collection.get(
            where={"$and": [{"post_id": post_id}, {"level": "post"}]},
            include=["documents", "metadatas"],
        )
        return [
            {"text": doc, "metadata": meta}
            for doc, meta in zip(res.get("documents") or [], res.get("metadatas") or [])
        ]

    def semantic_search(self, query, where=None, n_results=CANDIDATE_POOL,
                        with_parent_context=True):
        """Semantic search, attaching Reddit post context to comment hits.

        Each hit is {chunk_id, text, metadata, distance}. When a hit is a Reddit
        comment chunk, its post (title + body) chunk(s) are fetched once per post
        and attached under "parent_context" so the comment's title can be
        expanded with the original post when more context is needed.
        """
        res = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits = [
            {"chunk_id": cid, "text": doc, "metadata": meta, "distance": dist}
            for cid, doc, meta, dist in zip(
                res["ids"][0], res["documents"][0],
                res["metadatas"][0], res["distances"][0],
            )
        ]

        if with_parent_context:
            cache = {}
            for hit in hits:
                meta = hit["metadata"]
                if meta.get("source_type") == "reddit" and meta.get("level") == "comment":
                    post_id = meta.get("post_id")
                    if post_id and post_id not in cache:
                        cache[post_id] = self._fetch_post_context(post_id)
                    hit["parent_context"] = cache.get(post_id, [])
        return hits

    def keyword_search(self, query, where=None, n_results=CANDIDATE_POOL):
        """BM25 keyword search. Returns dicts with text/metadata/bm25_score."""
        scores = self.bm25.get_scores(_tokenize(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i],
                        reverse=True)
        results = []
        for i in ranked:
            if scores[i] <= 0:
                break
            chunk = self.chunks[i]
            # Flatten to the same shape Chroma returns, so fusion + filtering
            # see identical metadata regardless of which retriever produced it.
            meta = flatten_metadata(chunk)
            if not _matches(meta, where):
                continue
            results.append({
                "chunk_id": chunk["chunk_id"], "text": chunk["text"],
                "metadata": meta, "bm25_score": float(scores[i]),
            })
            if len(results) >= n_results:
                break
        return results

    # --- hybrid fusion ------------------------------------------------------

    def retrieve(self, query, where=None, n_results=N_RESULTS):
        """Hybrid retrieval via Reciprocal Rank Fusion.

        Returns the top `n_results` chunks, each annotated with its semantic
        distance, BM25 score, and the fused RRF score.
        """
        logger.info("")
        semantic = self.semantic_search(query,where, CANDIDATE_POOL)
        keyword = self.keyword_search(query, where,CANDIDATE_POOL)

        fused = {}  # chunk_id -> merged record

        def add(results, score_key):
            for rank, r in enumerate(results):
                cid = r["chunk_id"]
                rec = fused.setdefault(cid, {
                    "chunk_id": cid, "text": r["text"], "metadata": r["metadata"],
                    "distance": None, "bm25_score": None, "rrf_score": 0.0,
                })
                rec["rrf_score"] += 1.0 / (RRF_K + rank + 1)
                if score_key in r:
                    rec[score_key] = r[score_key]
                if r.get("parent_context"):
                    rec["parent_context"] = r["parent_context"]

        add(semantic, "distance")
        add(keyword, "bm25_score")

        ranked = sorted(fused.values(), key=lambda r: r["rrf_score"], reverse=True)
        return ranked[:n_results]


# --- display + evaluation ---------------------------------------------------


def display_results(query, results):
    """Print retrieved chunks with distance score and metadata."""
    print(f"\n{'=' * 80}\nQuery: {query}\n{'=' * 80}")
    if not results:
        print("  (no results — is the index built and non-empty?)")
        return
    for _, r in enumerate(results, 1):
        dist = f"{r['distance']:.4f}" if r.get("distance") is not None else "—"
        bm25 = f"{r['bm25_score']:.3f}" if r.get("bm25_score") is not None else "—"
        meta = r["metadata"]
        level = f"  level={meta['level']}" if meta.get("level") else ""
        rrf = f"{r['rrf_score']:.2f}" if r.get("rrf_score") else ""
        print(f"RRF: {rrf} distance={dist}  bm25={bm25}")
        print(f"    source={meta.get('source')}  source_type={meta.get('source_type')}{level}")
        print(f"    title={meta.get('title')}")
        print(f"    url={meta.get('url')}")
        snippet = " ".join(r["text"].split())[:280]
        print(f"    text: {snippet}{'…' if len(r['text']) > 280 else ''}")
        for p in r.get("parent_context", []):
            ctx = " ".join(p["text"].split())[:200]
            print(f"    ↳ post context: {ctx}{'…' if len(p['text']) > 200 else ''}")


def test_retrieval(n_results=N_RESULTS, where=None):
    """Run first 3 Evaluation Plan questions through all three searches and print."""
    retriever = Retriever()
    if retriever.collection.count() == 0:
        print("Collection is empty. Run `python embeddings.py` to build the index.")
        return
    print(f"Running {len(EVAL_QUESTIONS[:3])} eval question(s) at top-k={n_results}"
          f"{f' with filter {where}' if where else ''}")
    for query in EVAL_QUESTIONS[:3]:
        print(f"\n{'=' * 80}\nSEMANTIC SEARCH: \n{'=' * 80}")
        display_results(query, retriever.semantic_search(query, where,n_results))
        print(f"\n{'=' * 80}\nBM25 KEYWORD SEARCH: \n{'=' * 80}")
        display_results(query, retriever.keyword_search(query, where,n_results))
        print(f"\n{'=' * 80}\nHYBRID SEARCH: \n{'=' * 80}")
        display_results(query, retriever.retrieve(query,where, n_results))


if __name__ == "__main__":
    test_retrieval()
