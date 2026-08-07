import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from chunking import Chunk
from embeddings import EMBEDDING_DIM

COLLECTION_NAME = "stuttgart_bureaucracy"
# Scraped content is evaluated here, isolated from the live collection, until
# Phase 7.8 confirms retrieval parity and server.py is cut over deliberately.
SCRAPED_COLLECTION_NAME = f"{COLLECTION_NAME}_scraped"
# Fixed namespace so chunk IDs are stable across re-runs (same doc+section -> same id).
_ID_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def get_client() -> QdrantClient:
    return QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))


def ensure_collection(client: QdrantClient) -> None:
    """Rebuild the collection from scratch on every run.

    We recreate rather than reuse: upsert only adds/updates points by ID, so a
    section removed or renamed in a source doc would otherwise leave an orphaned,
    stale point behind. Full rebuild keeps Qdrant in exact sync with data/docs/.
    """
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )


def ensure_collection_exists(client: QdrantClient, collection_name: str = COLLECTION_NAME) -> None:
    """Create a collection if missing, without touching existing data.

    Used by incremental (scraped) ingestion, which manages point-level
    add/delete itself (see scrape_ingest.py) rather than doing the full
    delete-and-rebuild ensure_collection() does for the hand-picked corpus.
    """
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )


def chunk_id(chunk: Chunk) -> str:
    """ID keyed on content, not just title|section: scraped pages can repeat
    the same heading many times (e.g. "Address" once per office location),
    which would otherwise collide and silently overwrite each other on
    upsert. Keying on content also means identical content reliably maps to
    the same ID across re-runs (still stable), while changed content gets a
    new ID -- exactly the change-detection signal Phase 7.4 needs."""
    return str(uuid.uuid5(_ID_NAMESPACE, chunk.text))


def upsert_chunks(
    client: QdrantClient,
    chunks: list[Chunk],
    vectors: list[list[float]],
    collection_name: str = COLLECTION_NAME,
    origin: str = "hand_picked",
) -> None:
    """origin records provenance in the payload (hand_picked vs. scraped).
    Isolation between the two pipelines comes from writing to separate
    collections (see collection_name) -- origin is metadata for later
    inspection/merge, not the safety mechanism itself."""
    points = [
        PointStruct(
            id=chunk_id(chunk),
            vector=vector,
            payload={
                "text": chunk.text,
                "title": chunk.title,
                "section": chunk.section,
                "topic": chunk.topic,
                "source": chunk.source,
                "last_checked": chunk.last_checked,
                "origin": origin,
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    client.upsert(collection_name=collection_name, points=points)