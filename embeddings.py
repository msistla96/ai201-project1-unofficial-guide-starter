"""
embeddings.py — Embedding + Vector Store stage (see Architecture diagram).

Reads the chunks produced by chunking.py (documents/chunks.jsonl), embeds them
with all-MiniLM-L6-v2 via sentence-transformers, and stores them in a
persistent ChromaDB collection (cosine space).

ChromaDB's SentenceTransformerEmbeddingFunction turns the chunk text into
vectors automatically — we hand over text + metadata + ids and Chroma does the
vector math and persistence.

Parent-child retrieval for Reddit
---------------------------------
The Reddit chunks come in two levels (see chunking.py):

  - level="comment" : the primary, embedded unit = post *title* + a comment.
  - level="post"    : the post *title + body*, a parent chunk for context.

Both levels are embedded and stored. At query time, when a matched comment
chunk needs more context, `retrieve(..., with_parent_context=True)` pulls the
matching post chunk(s) (same post_id, level="post") and attaches them so the
generator can see the original post the comment was replying to.

Run to (re)build the index:
    python embeddings.py
"""

import os
import json
import logging

import chromadb
from chromadb.utils import embedding_functions

from config import CHROMA_COLLECTION, CHROMA_PATH, EMBEDDING_MODEL, N_RESULTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

CHUNKS_PATH = "documents/chunks.jsonl"
BATCH_SIZE = 5461    # sentences encoded per forward pass

_MODEL = None

# Top-level metadata fields kept flat for display + filtering.
_META_FIELDS = ("source_type", "source", "title", "url", "date", "author",
                "token_estimate")
# Fields lifted out of metadata.extra (so retrieval can filter / link on them).
_EXTRA_FIELDS = ("level", "parent_id", "post_id", "comment_id", "kind", "score",
                 "num_comments", "faq_number")


def load_chunks(path=CHUNKS_PATH):
    """Load chunk dicts from a JSONL file produced by chunking.py."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found. Run `python chunking.py` first to generate chunks."
        )
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    logger.info("Loaded %d chunk(s) from %s", len(chunks), path)
    return chunks


def flatten_metadata(chunk):
    """Build a Chroma-safe flat metadata dict (scalars only, no None)."""
    meta = chunk.get("metadata") or {}
    extra = meta.get("extra") or {}
    flat = {}
    for field in _META_FIELDS:
        value = meta.get(field)
        if value is not None:
            flat[field] = value
    for field in _EXTRA_FIELDS:
        value = extra.get(field)
        if value is not None:
            flat[field] = value
    return flat


def get_embedding_function():
    """all-MiniLM-L6-v2 via sentence-transformers (downloads on first use)."""
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )


def get_collection():
    """Return (creating if needed) the persistent ChromaDB collection."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def build_index(path=CHUNKS_PATH, reset=True):
    """Embed every chunk in `path` and store it in the vector database.

    With reset=True the collection is dropped and rebuilt so re-running gives a
    clean index instead of duplicating ids.
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    if reset:
        try:
            client.delete_collection(CHROMA_COLLECTION)
            logger.info("Dropped existing collection %r", CHROMA_COLLECTION)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )

    chunks = load_chunks(path)
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        collection.add(
            ids=[c["chunk_id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[flatten_metadata(c) for c in batch],
        )
        logger.info("Embedded %d/%d chunks", min(start + len(batch), len(chunks)),
                    len(chunks))

    logger.info("Index built: %d chunks in collection %r",
                collection.count(), CHROMA_COLLECTION)
    return collection

if __name__ == "__main__":
    build_index("documents/chunks.jsonl")
