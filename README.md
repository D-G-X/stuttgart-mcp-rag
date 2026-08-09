# Stuttgart MCP RAG

A terminal chat assistant that answers bureaucracy questions for international
students in Stuttgart (Anmeldung, Aufenthaltstitel, Sperrkonto, health
insurance, university enrollment, plus HFT Stuttgart admissions and campus
addresses). It's built as an MCP (Model Context Protocol) server exposing
retrieval tools over a document corpus, with two interchangeable terminal
clients (local Ollama or Anthropic).

The corpus comes from two pipelines that share one live Qdrant collection:

- **Hand-picked** (`data/docs/*.md`) — manually written, tightly structured
  summaries with source URLs in frontmatter.
- **Scraped** (`scrape_*.py`) — fetched from official pages, extracted to the
  same markdown contract, gated by automated sanity checks before publishing.

Every point in the live collection carries an `origin` field (`hand_picked` or
`scraped`) so the two can coexist, be synced independently, and be told apart
when debugging retrieval.

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
               │ (all-MiniLM-L6-v2, 384d)│   │ (static, in-memory)     │
               └──────────┬──────────────┘   └──────────────────────┘
                          │ vector
                          ▼
               ┌─────────────────────┐
               │ vectorstore.py         │
               │ QdrantClient            │
               └──────────┬──────────────┘
                          │ query_points()
                          ▼
        ┌────────────────────────────────────────┐
        │ Qdrant (localhost:6333)                   │
        │                                            │
        │ stuttgart_bureaucracy_scraped  ← LIVE      │
        │   hand_picked + scraped points             │
        │                                            │
        │ stuttgart_bureaucracy                      │
        │   hand-picked only, rebuildable fallback   │
        └────────────────────────────────────────┘
                          ▲              ▲
                          │              │
                  ingest.py        scrape_ingest.py
                  (hand-picked)     (scraped)
```

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

## The two ingestion pipelines

Both are offline — neither is part of the live chat request path.

### Hand-picked: `ingest.py`

Reads `data/docs/*.md`, splits each doc into heading-based chunks with metadata
from YAML frontmatter (`chunking.py`), embeds them, then writes to **both**
collections:

- `stuttgart_bureaucracy` — deleted and rebuilt from scratch each run.
- `stuttgart_bureaucracy_scraped` (live) — synced with an add/delete diff,
  scoped to `origin="hand_picked"` so it never touches scraped points.

The live collection is synced rather than rebuilt because it is shared;
rebuilding would wipe the scraped pipeline's half.

### Scraped: `scrape_ingest.py`

Chains fetch → extract → review → sync:

| Stage | Module | What it does |
|---|---|---|
| Inventory | `scrape_sources.py` | The URL list, with per-domain robots.txt notes and comments recording why dropped sources were dropped |
| Fetch | `scrape_fetch.py` | robots.txt check, polite UA, 1 req/sec rate limit, exponential backoff; snapshots raw HTML to `data/raw/<slug>/<date>.html` before any parsing |
| Extract | `scrape_extract.py` | `trafilatura` HTML → markdown, heading breadcrumbs flattened to the `##` level `chunking.py` expects, plus office-directory consolidation (see below) |
| Review | `scrape_review.py` | Compares candidates in `data/scraped/` against approved copies in `data/published/`; auto-publishes routine edits, holds anomalies in `data/scraped_review/` |
| Sync | `scrape_ingest.py` | Add/delete diff into the live collection, scoped to `origin="scraped"` |

The review gate is risk-based rather than review-everything: a change is held
only if it fails a sanity check (content shrank below 50% or grew past 300% of
the approved length, or under 50% of the approved section names survived). The
reasoning is that a blanket manual-review policy tends to rot unreviewed on a
solo project, while these checks still catch the cases that actually matter —
site redesigns and broken extraction.

Raw snapshots are kept so extraction can be re-run without re-fetching, and so
any chunk can be audited back to the HTML it came from.

#### Office-directory consolidation

The stuttgart.de Anmeldung page embeds a directory of all 22 Bürgerbüros, each
with its own `Address` / `Fax` / `Opening hours` subheadings. Extracted
naively this produced ~7 tiny chunks per office — 96 of 114 chunks in the whole
corpus came from that one page, each too short to embed well.

`split_office_listings()` in `scrape_extract.py` merges each office into one
`## Bürgerbüro X` section, then splits the whole directory out into a separate
document with its own title and `topic: offices`. The split matters as much as
the merge: while the office chunks shared the parent page's title ("Register
residence - as main residence") and each contained a literal `Address:` field,
they lexically outranked the actual registration procedure for queries like
"how do I register my address" — the exact question the page exists to answer.

## Project structure

```
server.py                  MCP server: registers and implements the two tools
chat.py                    Terminal chat client using a local Ollama model
chat-anthropic.py          Terminal chat client using the Anthropic API
embeddings.py              Local embedding model (sentence-transformers)
embedding-openai-api.py    Alternate OpenAI-based embedding backend (not wired in)
vectorstore.py             Qdrant client, collection setup, upsert/sync helpers
chunking.py                Markdown -> heading-based chunks with metadata
checklists.py              Hand-curated step-by-step checklists per topic
ingest.py                  Hand-picked pipeline: chunk -> embed -> both collections
query.py                   Standalone CLI to sanity-check retrieval without an LLM

scrape_sources.py          Scrape target inventory + robots.txt notes
scrape_fetch.py            Polite, rate-limited fetching with raw HTML snapshots
scrape_extract.py          HTML -> chunking.py-compatible markdown
scrape_review.py           Auto-publish vs. hold-for-review gate
scrape_ingest.py           Scraped pipeline: fetch -> extract -> review -> sync
scrape_compare.py          Side-by-side retrieval comparison across collections

crontab.txt                Reference cron entry for a weekly scrape (not installed)
PLAN.md                    Phased build plan and design decisions

data/docs/*.md             Hand-picked source documents (frontmatter + sections)
data/raw/<slug>/*.html     Raw HTML snapshots, one per fetch date (gitignored)
data/scraped/*.md          Latest extraction output, pre-review (gitignored)
data/published/*.md        Approved extractions — what scrape_ingest.py reads
data/scraped_review/*.md   Held for manual review (gitignored)
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

### 5. Ingest the corpus

Hand-picked docs — run this whenever `data/docs/*.md` changes:

```bash
uv run python ingest.py
```

Scraped docs — fetches from the network, so it's slower and rate-limited:

```bash
uv run python scrape_ingest.py
```

Both are safe to re-run in any order; each only manages its own `origin` slice
of the live collection.

Optionally sanity-check retrieval directly (no LLM involved):

```bash
uv run python query.py "How do I register my address in Stuttgart?"
```

Or compare the two collections side by side on a fixed question set:

```bash
uv run python scrape_compare.py
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

### 7. Optional: schedule refreshes

`crontab.txt` holds a reference weekly cron entry for `scrape_ingest.py`. It is
**not installed** — it's a documented starting point. See the comments in that
file for how to install it and what it assumes (notably that Qdrant is already
running).

## Accuracy notes

This answers questions with real consequences — visa deadlines, required
documents, fees — so a few things are deliberate:

- Every chunk carries `source`, `title`, `section`, and `last_checked`, and the
  tools return them so answers can cite sources.
- The system prompt in `chat.py` instructs the model to answer only from
  retrieved content, never to invent a citation when a tool result has none,
  and to say so explicitly when the retrieved text doesn't contain the answer.
- Figures like the Sperrkonto deposit and office opening hours drift over time.
  `last_checked` reflects when a doc was written or last scraped, not that it is
  currently correct. Hand-picked docs are summaries of official pages, not
  verbatim text — verify anything consequential against the linked source.

## Known gaps

- `get_procedure_checklist` covers five topics (`anmeldung`, `aufenthaltstitel`,
  `sperrkonto`, `health_insurance`, `university_enrollment`). There is no
  checklist for the HFT application process, even though its documents are
  indexed and searchable.
- The tool only reliably routes to `get_procedure_checklist` when the user says
  "checklist" — "steps to enroll" goes to semantic search instead. The routing
  is driven entirely by tool docstrings, with no fallback.
- Some scraped pages (the study.eu Sperrkonto guide, both HFT pages) have no
  real `<h2>` structure, so they extract as a single large chunk. Their
  hand-picked counterparts currently outrank them, so this is latent rather
  than user-visible.
- The local 8B model occasionally emits malformed output on the search path
  (e.g. printing a tool call as plain text instead of making one). This is a
  model limitation, not a retrieval one; `chat-anthropic.py` does not show it.
