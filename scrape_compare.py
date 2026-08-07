"""Retrieval comparison (Phase 7.7/7.8): run a fixed set of test questions
against both the live hand-picked collection and the isolated scraped
collection, side by side, so quality can be eyeballed before any cutover
decision. Doesn't change server.py or either collection -- read-only.
"""

from embeddings import embed_texts
from vectorstore import COLLECTION_NAME, SCRAPED_COLLECTION_NAME, get_client

TEST_QUESTIONS = [
    "How do I register my address in Stuttgart?",
    "How do I extend my residence permit as a student?",
    "How much money do I need in a blocked account?",
    "What health insurance do I need as an international student?",
    "How do I enroll at the University of Stuttgart?",
]


def top_results(client, collection_name: str, vector, top_k: int = 3):
    return client.query_points(collection_name=collection_name, query=vector, limit=top_k).points


def compare(question: str, client, top_k: int = 3) -> None:
    vector = embed_texts([question])[0]
    print(f"\n=== {question} ===")
    for name in (COLLECTION_NAME, SCRAPED_COLLECTION_NAME):
        print(f"--- {name} ---")
        for r in top_results(client, name, vector, top_k):
            p = r.payload
            print(f"  {r.score:.3f}  [{p['title']} — {p['section']}]")


if __name__ == "__main__":
    client = get_client()
    for question in TEST_QUESTIONS:
        compare(question, client)
