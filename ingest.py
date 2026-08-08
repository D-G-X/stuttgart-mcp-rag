"""Ingest the hand-picked data/docs/ corpus.

Writes to two collections on every run:

1. COLLECTION_NAME -- hand-picked only, fully rebuilt. Not what server.py
   queries since the Phase 7.8 cutover; kept as a clean fallback/reference.
2. SCRAPED_COLLECTION_NAME -- the live collection server.py actually queries,
   shared with scrape_ingest.py. Synced (add/delete diff), never rebuilt,
   since rebuilding would wipe the scraped pipeline's points.

Both are written here so editing a doc in data/docs/ and re-running this
script can't leave the live collection silently stale -- the failure mode
this file previously had, when the hand-picked -> live merge only existed as
an ad-hoc command run once by hand.
"""

from pathlib import Path

from dotenv import load_dotenv

from chunking import chunk_corpus
from embeddings import embed_texts
from vectorstore import (
    COLLECTION_NAME,
    SCRAPED_COLLECTION_NAME,
    ensure_collection,
    ensure_collection_exists,
    get_client,
    sync_chunks,
    upsert_chunks,
)

load_dotenv()

ORIGIN = "hand_picked"


def main() -> None:
    docs_dir = Path(__file__).parent / "data" / "docs"
    chunks = chunk_corpus(docs_dir)
    print(f"Chunked {len(chunks)} sections from {docs_dir}")

    vectors = embed_texts([c.text for c in chunks])
    print(f"Embedded {len(vectors)} chunks (dim={len(vectors[0])})")

    client = get_client()

    ensure_collection(client)
    upsert_chunks(client, chunks, vectors, COLLECTION_NAME, ORIGIN)
    print(f"Rebuilt '{COLLECTION_NAME}': {client.count(COLLECTION_NAME).count} points")

    ensure_collection_exists(client, SCRAPED_COLLECTION_NAME)
    stats = sync_chunks(client, chunks, vectors, SCRAPED_COLLECTION_NAME, ORIGIN)
    print(
        f"Synced '{SCRAPED_COLLECTION_NAME}' ({ORIGIN}): "
        f"+{stats['added']} new, -{stats['deleted']} removed, {stats['unchanged']} unchanged"
    )
    print(f"Live collection now has {client.count(SCRAPED_COLLECTION_NAME).count} points total")


if __name__ == "__main__":
    main()
