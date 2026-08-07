from pathlib import Path

from dotenv import load_dotenv

from chunking import chunk_corpus
from embeddings import embed_texts
from vectorstore import COLLECTION_NAME, ensure_collection, get_client, upsert_chunks

load_dotenv()


def main() -> None:
    docs_dir = Path(__file__).parent / "data" / "docs"
    chunks = chunk_corpus(docs_dir)
    print(f"Chunked {len(chunks)} sections from {docs_dir}")

    vectors = embed_texts([c.text for c in chunks])
    print(f"Embedded {len(vectors)} chunks (dim={len(vectors[0])})")

    client = get_client()
    ensure_collection(client)
    upsert_chunks(client, chunks, vectors)

    count = client.count(COLLECTION_NAME).count
    print(f"Upserted into '{COLLECTION_NAME}'. Collection now has {count} points.")


if __name__ == "__main__":
    main()