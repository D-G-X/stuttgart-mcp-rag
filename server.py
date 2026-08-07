from mcp.server import MCPServer

from embeddings import embed_texts
from vectorstore import COLLECTION_NAME, get_client

mcp = MCPServer("stuttgart-bureaucracy")


@mcp.tool()
def search_bureaucracy_docs(query: str, top_k: int = 3) -> str:
    """Search official Stuttgart bureaucracy documents for international students.

    Covers: address registration (Anmeldung), residence permits/visa extension
    (Aufenthaltstitel), blocked accounts (Sperrkonto), health insurance, university
    enrollment, and relevant office locations/addresses.

    Args:
        query: The question or topic to search for.
        top_k: Number of top matching chunks to return (default 3).
    """
    top_k = max(top_k, 3)  # never let the caller starve retrieval of context
    vector = embed_texts([query])[0]
    client = get_client()
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=top_k,
    ).points

    if not results:
        return "No relevant documents found."

    blocks = []
    for r in results:
        payload = r.payload
        blocks.append(
            f"Source: {payload['title']} — {payload['section']}\n"
            f"URL: {payload['source']}\n"
            f"Last checked: {payload['last_checked']}\n"
            f"Relevance: {r.score:.3f}\n\n"
            f"{payload['text']}"
        )
    return "\n\n---\n\n".join(blocks)


if __name__ == "__main__":
    mcp.run()