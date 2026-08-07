from mcp.server import MCPServer

from checklists import TOPIC_CHECKLISTS, TOPIC_SOURCES
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
    top_k = max(top_k, 4)  # never let the caller starve retrieval of context
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


@mcp.tool()
def get_procedure_checklist(topic: str) -> str:
    """Get the exact, complete, ordered step-by-step checklist for a known bureaucratic procedure.

    Use this instead of search_bureaucracy_docs when the user wants a full
    step-by-step checklist for a specific known procedure, rather than an
    answer to an open-ended question.

    Valid topics: anmeldung, aufenthaltstitel, sperrkonto, health_insurance,
    university_enrollment.

    Args:
        topic: One of the valid topic keys listed above.
    """
    key = topic.strip().lower()
    steps = TOPIC_CHECKLISTS.get(key)
    if not steps:
        available = ", ".join(TOPIC_CHECKLISTS.keys())
        return f"No checklist found for topic '{topic}'. Available topics: {available}"

    title, source_url = TOPIC_SOURCES[key]
    numbered = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
    return f"Source: {title}\nURL: {source_url}\n\n{numbered}"


if __name__ == "__main__":
    mcp.run()