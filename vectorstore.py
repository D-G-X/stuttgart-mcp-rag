import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from chunking import Chunk
from embeddings import EMBEDDING_DIM

COLLECTION_NAME = "stuttgart_bureaucracy"
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


def chunk_id(chunk: Chunk) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{chunk.title}|{chunk.section}"))


def upsert_chunks(client: QdrantClient, chunks: list[Chunk], vectors: list[list[float]]) -> None:
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
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points)