"""Re-ingestion pipeline (Phase 7.5): fetch -> extract -> review -> targeted
Qdrant sync, without the full delete-and-rebuild ingest.py does for the
hand-picked corpus.

Writes to vectorstore.SCRAPED_COLLECTION_NAME, a separate collection from the
live one server.py/chat.py query -- per PLAN.md Phase 7.8, scraped content is
evaluated in isolation until retrieval parity is confirmed and server.py is
cut over deliberately. It never touches the live collection.

Content-hash chunk IDs (vectorstore.chunk_id) mean unchanged content keeps
the same ID, so syncing a doc only embeds/upserts chunks that are actually
new, and explicitly deletes points whose chunk disappeared (section removed
or renamed) instead of leaving them as orphans -- the correctness gap noted
when this pipeline was planned (PLAN.md Phase 7.5).
"""

from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from chunking import Chunk, chunk_document
from embeddings import embed_texts
from scrape_extract import ExtractError, extract_one
from scrape_fetch import FetchError, fetch_and_snapshot
from scrape_review import PUBLISHED_DIR, SCRAPED_DIR, review_one
from scrape_sources import unique_sources
from vectorstore import (
    SCRAPED_COLLECTION_NAME,
    chunk_id,
    ensure_collection_exists,
    get_client,
    upsert_chunks,
)


def _existing_ids_for_source(client: QdrantClient, source_url: str) -> set[str]:
    """Points for one scraped source URL.

    Filtered on origin as well as source: several hand-picked docs cite the
    same official URLs the scraper fetches (e.g. 01_anmeldung.md and
    06_offices.md both cite the stuttgart.de Anmeldung page). Without the
    origin condition this swept up those hand-picked points, found them
    absent from the scraped doc's chunk set, and deleted them as "removed
    sections" -- silently wiping the entire hand-picked half of the shared
    live collection on every scrape run.
    """
    ids: set[str] = set()
    offset = None
    source_filter = Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value=source_url)),
            FieldCondition(key="origin", match=MatchValue(value="scraped")),
        ]
    )
    while True:
        points, offset = client.scroll(
            collection_name=SCRAPED_COLLECTION_NAME,
            scroll_filter=source_filter,
            with_payload=False,
            with_vectors=False,
            limit=256,
            offset=offset,
        )
        ids.update(str(p.id) for p in points)
        if offset is None:
            break
    return ids


def sync_published_doc(client: QdrantClient, path: Path) -> dict:
    chunks: list[Chunk] = chunk_document(path)
    if not chunks:
        return {"path": path.name, "added": 0, "deleted": 0, "unchanged": 0}

    source_url = chunks[0].source
    existing_ids = _existing_ids_for_source(client, source_url)
    new_by_id = {chunk_id(c): c for c in chunks}

    to_add = [c for cid, c in new_by_id.items() if cid not in existing_ids]
    to_delete = existing_ids - set(new_by_id)

    if to_add:
        vectors = embed_texts([c.text for c in to_add])
        upsert_chunks(client, to_add, vectors, collection_name=SCRAPED_COLLECTION_NAME, origin="scraped")

    if to_delete:
        client.delete(collection_name=SCRAPED_COLLECTION_NAME, points_selector=list(to_delete))

    return {
        "path": path.name,
        "added": len(to_add),
        "deleted": len(to_delete),
        "unchanged": len(new_by_id) - len(to_add),
    }


def run(do_fetch: bool = True) -> None:
    client = get_client()
    ensure_collection_exists(client, SCRAPED_COLLECTION_NAME)

    if do_fetch:
        for source in unique_sources():
            try:
                fetch_and_snapshot(source.url)
                extract_one(source)
            except (FetchError, ExtractError) as exc:
                print(f"SKIP [{source.topic}] {source.url}: {exc}")

    for scraped_path in sorted(SCRAPED_DIR.glob("*.md")):
        result = review_one(scraped_path)
        print(f"{result.status:15s} {result.slug}")
        if result.reason:
            print(f"                {result.reason}")

    for published_path in sorted(PUBLISHED_DIR.glob("*.md")):
        stats = sync_published_doc(client, published_path)
        print(
            f"synced {stats['path']}: "
            f"+{stats['added']} new, -{stats['deleted']} removed, {stats['unchanged']} unchanged"
        )

    count = client.count(SCRAPED_COLLECTION_NAME).count
    print(f"\nCollection '{SCRAPED_COLLECTION_NAME}' now has {count} points.")


if __name__ == "__main__":
    run()
