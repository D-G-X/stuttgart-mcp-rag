import sys

from vectorstore import COLLECTION_NAME, get_client
from embeddings import embed_texts


def search(query: str, top_k: int = 3):
    vector = embed_texts([query])[0]
    client = get_client()
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=top_k,
    ).points

    for r in results:
        print(f"score={r.score:.3f}  [{r.payload['title']} — {r.payload['section']}]")
        print(r.payload["text"][:200].replace("\n", " "))
        print()


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "How do I register my address in Stuttgart?"
    search(query)