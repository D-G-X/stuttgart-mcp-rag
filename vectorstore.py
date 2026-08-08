import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from chunking import Chunk
from embeddings import EMBEDDING_DIM

# Hand-picked-only collection. Since the Phase 7.8 cutover this is no longer
# what server.py queries -- it's kept as a rebuildable fallback/reference.
COLLECTION_NAME = "stuttgart_bureaucracy"
# The live collection server.py actually queries. Despite the name it now
# holds BOTH origins: scraped docs (via scrape_ingest.py) and hand-picked
# docs (via ingest.py), distinguished by the payload's `origin` field.
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


def existing_ids_by_origin(
    client: QdrantClient, collection_name: str, origin: str
) -> set[str]:
    """All point IDs in a collection that came from a given origin.

    Scoped by origin rather than by source URL (which is what
    scrape_ingest.py filters on) because the two pipelines share this
    collection: a hand-picked sync must not see -- or delete -- scraped
    points, and vice versa.
    """
    ids: set[str] = set()
    offset = None
    origin_filter = Filter(must=[FieldCondition(key="origin", match=MatchValue(value=origin))])
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=origin_filter,
            with_payload=False,
            with_vectors=False,
            limit=256,
            offset=offset,
        )
        ids.update(str(p.id) for p in points)
        if offset is None:
            break
    return ids


def sync_chunks(
    client: QdrantClient,
    chunks: list[Chunk],
    vectors: list[list[float]],
    collection_name: str,
    origin: str,
) -> dict:
    """Bring one origin's slice of a shared collection in sync with `chunks`.

    Adds new chunks, deletes points whose chunk no longer exists, leaves
    unchanged ones alone. Used instead of ensure_collection()'s
    delete-and-rebuild because this collection is shared -- rebuilding it
    would wipe the other pipeline's points.
    """
    existing_ids = existing_ids_by_origin(client, collection_name, origin)
    new_by_id = {chunk_id(c): c for c in chunks}

    to_add_ids = [cid for cid in new_by_id if cid not in existing_ids]
    to_delete = existing_ids - set(new_by_id)

    if to_add_ids:
        id_order = {cid: i for i, cid in enumerate(new_by_id)}
        add_chunks = [new_by_id[cid] for cid in to_add_ids]
        add_vectors = [vectors[id_order[cid]] for cid in to_add_ids]
        upsert_chunks(client, add_chunks, add_vectors, collection_name, origin)

    if to_delete:
        client.delete(collection_name=collection_name, points_selector=list(to_delete))

    return {
        "added": len(to_add_ids),
        "deleted": len(to_delete),
        "unchanged": len(new_by_id) - len(to_add_ids),
    }