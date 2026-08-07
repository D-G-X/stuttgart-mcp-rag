# Stuttgart MCP RAG

A terminal chat assistant that answers bureaucracy questions for international
students in Stuttgart (Anmeldung, Aufenthaltstitel, Sperrkonto, health
insurance, university enrollment). It's built as an MCP (Model Context
Protocol) server exposing retrieval tools over a small hand-curated document
corpus, with two interchangeable terminal clients (local Ollama or Anthropic).

## Architecture

The MCP server is not a long-running daemon — each chat client spawns its own
`server.py` subprocess over stdio on startup and tears it down on exit. Qdrant
is the one piece that runs independently and persistently.

```
                       ┌─────────────────────────┐
                       │   TERMINAL (user input)   │
                       └────────────┬───────────────┘
                                    │
              ┌─────────────────────┴──────────────────────┐
              │                                              │
              ▼                                              ▼
   chat.py (Ollama client)                       chat-anthropic.py (Claude client)
   ┌────────────────────────┐                    ┌────────────────────────┐
   │ ClientSession            │                    │ ClientSession            │
   │ + ollama.chat()          │                    │ + anthropic.messages()   │
   └────────────┬──────────────┘                    └────────────┬──────────────┘
                │                                                  │
                └───────────────────┬──────────────────────────────┘
                                    │  spawns subprocess:
                                    │  `uv run python server.py`
                                    │  stdio_client() -> stdin/stdout pipes
                                    ▼
                 ┌────────────────────────────────────────────┐
                 │  server.py — MCPServer("stuttgart-bureaucracy")│
                 │                                                │
                 │  @mcp.tool() search_bureaucracy_docs()         │
                 │  @mcp.tool() get_procedure_checklist()         │
                 └───────────┬─────────────────┬────────────────┘
                             │                 │
          search_bureaucracy_docs        get_procedure_checklist
                             │                 │
                             ▼                 ▼
               ┌─────────────────────┐   ┌──────────────────────┐
               │ embeddings.py          │   │ checklists.py           │
               │ SentenceTransformer     │   │ TOPIC_CHECKLISTS dict   │
               │ (all-MiniLM-L6-v2)      │   │ (static, in-memory)     │
               └──────────┬──────────────┘   └──────────────────────┘
                          │ vector
                          ▼
               ┌─────────────────────┐
               │ vectorstore.py         │
               │ QdrantClient            │
               └──────────┬──────────────┘
                          │ query_points()
                          ▼
               ┌─────────────────────┐
               │ Qdrant (localhost:6333)  │
               │ collection:               │
               │ stuttgart_bureaucracy     │
               │ (populated by ingest.py)  │
               └─────────────────────┘
```

`ingest.py` + `chunking.py` are the offline indexing pipeline: they read
`data/docs/*.md`, split each doc into heading-based chunks with metadata
(from YAML frontmatter), embed the chunks via `embeddings.py`, and
`upsert_chunks()` them into Qdrant. This runs once (and again whenever the
docs change) — it is not part of the live chat request path.

### Request flow (one turn)

1. On startup, the chat client spawns `server.py` as a subprocess and does
   the MCP handshake (`session.initialize()`, `session.list_tools()`), then
   converts the returned tool schemas into the LLM provider's tool format.
2. You type a question; it's appended to the message history and sent to the
   LLM along with the tool definitions.
3. The LLM decides whether to call `search_bureaucracy_docs` (open-ended,
   semantic search over doc chunks) or `get_procedure_checklist` (exact,
   ordered steps for a known topic), and returns a tool call.
4. The client dispatches it via `session.call_tool(...)`, which is sent as a
   JSON-RPC message over stdio to the `server.py` subprocess.
5. `search_bureaucracy_docs` embeds the query, queries Qdrant for the
   nearest chunks, and returns formatted `Source / URL / Last checked / text`
   blocks. `get_procedure_checklist` looks up a static dict — no Qdrant
   involved.
6. The tool result is sent back over stdio, appended to the message history,
   and passed to the LLM again to produce the final answer (except
   `get_procedure_checklist`, whose output is printed directly — see
   `PASSTHROUGH_TOOLS` in `chat.py` — since the local 8B model doesn't
   reliably reproduce long tool output verbatim on a second pass).

## Project structure

```
server.py                  MCP server: registers and implements the two tools
chat.py                    Terminal chat client using a local Ollama model
chat-anthropic.py          Terminal chat client using the Anthropic API
embeddings.py              Local embedding model (sentence-transformers)
embedding-openai-api.py    Alternate OpenAI-based embedding backend (not wired in)
vectorstore.py             Qdrant client, collection setup, upsert
chunking.py                Markdown -> heading-based chunks with metadata
checklists.py              Hand-curated step-by-step checklists per topic
ingest.py                  Offline pipeline: chunk docs -> embed -> upsert to Qdrant
query.py                   Standalone CLI to sanity-check retrieval without an LLM
data/docs/*.md             Source documents (YAML frontmatter + markdown sections)
qdrant_storage/            Qdrant's on-disk data (gitignored, created at runtime)
```

## Setup

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- [Docker](https://www.docker.com/) (to run Qdrant), or a local Qdrant instance
- For `chat.py`: [Ollama](https://ollama.com/) installed and running locally
- For `chat-anthropic.py`: an Anthropic API key

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Fill in `.env` as needed:

| Variable         | Required for                                   |
|------------------|-------------------------------------------------|
| `QDRANT_URL`     | Always. Defaults to `http://localhost:6333` if unset. |
| `ANTHROPIC_API_KEY` | `chat-anthropic.py`                          |
| `OPENAI_API_KEY` | Only if you switch to `embedding-openai-api.py`  |
| `HF_TOKEN`       | Only if the sentence-transformers model requires authenticated download |

### 3. Start Qdrant

```bash
docker run -p 6333:6333 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant
```

### 4. Pull a local model (only needed for `chat.py`)

```bash
ollama pull llama3.1:8b
```

### 5. Ingest the document corpus

Chunks `data/docs/*.md`, embeds them, and loads them into Qdrant. Re-run
this whenever the docs change — it rebuilds the collection from scratch.

```bash
uv run python ingest.py
```

Optionally sanity-check retrieval directly (no LLM involved):

```bash
uv run python query.py "How do I register my address in Stuttgart?"
```

### 6. Run the chat client

```bash
# Local model via Ollama
uv run python chat.py

# Anthropic Claude
uv run python chat-anthropic.py
```

Type your question at the `You:` prompt; type `exit` or `quit` to leave.

Note: you don't need to run `server.py` yourself — each chat client spawns
it automatically as a subprocess over stdio.
