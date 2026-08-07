# Study Plan: MCP Chat Server with RAG for Stuttgart International Student Bureaucracy

## Goal

Build an understanding of two things by combining them into one real project:

1. **MCP (Model Context Protocol)** — a standard way to expose *tools* and *resources* to an LLM client (Claude Desktop, Claude Code, or your own app), so the model can call out to your server instead of hallucinating answers.
2. **RAG (Retrieval-Augmented Generation)** — grounding LLM answers in real documents by retrieving relevant chunks from a vector database before generating a response.

The applied use case: an assistant that answers questions international students in Stuttgart have about bureaucracy — Anmeldung (city registration), Aufenthaltstitel/visa extension at the Ausländerbehörde, health insurance, blocked account (Sperrkonto), university enrollment/immatriculation, etc.

Stack decided:
- **Language**: Python
- **Vector DB**: Qdrant
- **Clients**: Claude Desktop/Claude Code first (zero UI work), then a custom chat app later
- **Content**: Start with a handful of hand-picked documents; scraping comes later

---

## Core Concepts to Understand First

### MCP — the protocol
- MCP servers expose three main primitive types to a client:
  - **Tools**: functions the model can call (e.g. `search_bureaucracy_docs(query: str)`). This is what you'll use most.
  - **Resources**: addressable read-only data the client can fetch (e.g. raw source documents by URI).
  - **Prompts**: reusable prompt templates the client can surface to the user.
- Transport: MCP servers usually run over **stdio** (spawned as a subprocess by the client — this is what Claude Desktop/Code use) or over **HTTP/SSE** (for remote servers, needed if your own chat app talks to it over a network).
- Your server just needs to: (1) declare its tools with a schema (name, description, input schema), (2) implement the handler that runs when a tool is called, (3) return results as content blocks (text, etc.).
- Study: the official MCP docs (modelcontextprotocol.io) and the Python SDK (`mcp` package on PyPI) — read the "quickstart server" example first, it's short.

### RAG — the pattern
- **Ingestion (offline)**: split documents into chunks → embed each chunk into a vector → store vector + text + metadata (source, section, URL) in a vector DB.
- **Retrieval (online, per query)**: embed the user's query with the *same* embedding model → similarity search (cosine/dot) in the vector DB → get top-k chunks.
- **Generation**: pass the retrieved chunks + the user's question to the LLM as context, instruct it to answer using only that context and to cite sources.
- Key knobs you'll learn to tune: chunk size/overlap, top-k, embedding model choice, re-ranking (optional, later), and prompt structure for grounding + citation.

### Qdrant — the vector DB
- Runs as a server (Docker container is easiest) with a REST/gRPC API; Python client is `qdrant-client`.
- Core objects: **collection** (like a table), **points** (id + vector + payload/metadata).
- You'll create one collection, e.g. `stuttgart_bureaucracy`, with vector size matching your embedding model's output dimension (e.g. 1536 for `text-embedding-3-small`, 384 for `bge-small-en`).
- Study: Qdrant's Python quickstart — `client.create_collection`, `client.upsert`, `client.search` (or `query_points` in newer client versions).

---

## Architecture Overview

```
                     ┌─────────────────────────┐
                     │   Offline: Ingestion      │
                     │  docs → chunks → embed    │
                     │  → upsert into Qdrant      │
                     └─────────────────────────┘
                                  │
                                  ▼
┌────────────┐   MCP    ┌─────────────────┐   search    ┌─────────┐
│ Claude      │◄────────►│  Your MCP Server │◄───────────►│ Qdrant  │
│ Desktop/Code│  stdio/  │  (Python)         │   (vectors) │ (Docker)│
│ or your own │  HTTP    │  tool: search_docs│             └─────────┘
│ chat app    │          │  tool: get_topic  │
└────────────┘          └─────────────────┘
```

Two ways to "chat":
- **Path A (fastest)**: register your MCP server in Claude Desktop's config. Claude itself becomes the chat UI, and it calls your `search_bureaucracy_docs` tool automatically when relevant.
- **Path B (own app)**: write a small Python script that acts as an MCP *client*, connects to your server, and drives its own loop: user message → call LLM with tool definitions → if LLM requests the tool, call your MCP server → feed results back to LLM → print answer. This teaches you the full loop that Path A hides from you.

You'll do Path A first to validate retrieval quality quickly, then Path B to understand what's happening under the hood.

---

## Phased Build Plan

### Phase 0 — Environment setup
- Install Python 3.11+, `uv` or `pip` for deps.
- Run Qdrant locally via Docker: `docker run -p 6333:6333 qdrant/qdrant`.
- Install: `mcp`, `qdrant-client`, an embeddings client (e.g. `openai` or a local `sentence-transformers` model), `python-dotenv`.

### Phase 1 — Hand-picked corpus
- Collect 5–10 documents/pages, saved as plain text or markdown, covering:
  - Anmeldung (city registration) at Bürgeramt Stuttgart
  - Aufenthaltstitel / visa extension at Ausländerbehörde
  - Health insurance requirements for students
  - Blocked account (Sperrkonto) for visa purposes
  - University enrollment/immatriculation steps (pick one university, e.g. Uni Stuttgart)
- Keep each doc's source URL/title as metadata — citations matter a lot for bureaucratic accuracy.

### Phase 2 — Ingestion script
- Write `ingest.py`: load docs → chunk (start simple: fixed-size with overlap, e.g. 500 tokens / 50 overlap) → embed → upsert into Qdrant collection with payload `{text, source, title, section}`.
- Verify manually: run a few `client.query_points` calls with a test query and eyeball whether the right chunks come back.

### Phase 3 — MCP server with one tool
- Write `server.py` using the MCP Python SDK.
- Implement `search_bureaucracy_docs(query: str, top_k: int = 5)`:
  - Embed query → search Qdrant → return formatted chunks with source citations.
- Run it standalone first (the SDK provides a way to test tools without a client) to confirm it works before wiring into Claude Desktop.

### Phase 4 — Wire into Claude Desktop (Path A)
- Add your server to Claude Desktop's `claude_desktop_config.json` (stdio transport, points at your Python script).
- Chat with Claude Desktop, ask real questions ("How do I register my address in Stuttgart as a new student?"), confirm it calls your tool and grounds its answer in retrieved chunks with citations.
- This is your first end-to-end milestone.

### Phase 5 — Build your own chat client (Path B)
- Write `chat.py`: a minimal loop using the Anthropic API directly (`anthropic` Python SDK) as an MCP *client*.
- Use the MCP Python SDK's client utilities to connect to your server over stdio, list its tools, convert them to Claude tool-use format, and implement the tool-call ↔ tool-result loop yourself.
- This is where the "how MCP actually works under the hood" understanding solidifies.

### Phase 6 — Quality pass
- Add a second tool if useful, e.g. `get_procedure_checklist(topic: str)` that returns a structured step list for a known topic (separate from free-text search).
- Tune chunking/top-k based on real questions that go wrong.
- Add source citations clearly in responses (this matters a lot for bureaucratic trust — wrong info about visas has real consequences, so always cite and encourage the user to verify with the official office).

### Phase 7 — Scraping & refresh pipeline

Goal: replace the hand-picked `data/docs/*.md` corpus with an automated,
periodically-refreshed pipeline over official sources, without regressing
the retrieval quality Phase 6 achieved. Bureaucratic info being wrong has
real consequences, so publishing is risk-based: changes that pass automated
sanity checks go live automatically, anomalies get held for review.

**7.1 — Source inventory & legal check**
- Scope is allowed to grow organically, not gated to the current 6 topics — as new relevant pages on `stuttgart.de` / `uni-stuttgart.de` are found (more offices, more procedures), add them to the source list rather than waiting for a separate expansion phase.
- Check `robots.txt` and ToS for each domain before writing a fetcher against it. Note any crawl-rate or caching requirements.

**7.2 — Fetch layer**
- Plain `requests`/`httpx` GET, polite `User-Agent`, rate-limited (e.g. 1 req/sec) with exponential backoff on errors. These are static government pages — verify none need JS rendering before reaching for Playwright.
- Persist raw HTML snapshots (e.g. `data/raw/<page>/<date>.html`) before any extraction. Never scrape straight into chunks — keep the source for auditing and re-processing if extraction logic changes later.

**7.3 — Extraction & normalization**
- HTML → clean text via `trafilatura` or `readability-lxml`, plus manual boilerplate rules (nav/footer/cookie banners).
- Reuse `chunking.py`'s existing contract rather than rewriting it: emit the same frontmatter fields (`title`, `topic`, `source`, `last_checked`) and `## heading`-delimited sections `HEADING_RE`/`parse_doc()` already expect, so `chunk_corpus()` keeps working unmodified on scraped output.

**7.4 — Change detection & review gate**
- Store a content hash per page/section alongside `last_checked`.
- Each scrape run: unchanged hash → skip re-embedding (saves compute, and keeps `vectorstore.py`'s stable `uuid5(title|section)` chunk IDs from churning).
- Changed hash → run automated sanity checks on the new extraction: expected headings still present, extracted text length within normal bounds for that page, source URL still resolves, and the Phase 7.7 fixed-question regression check still retrieves it correctly. Checks pass → auto-publish (upsert straight to the live collection). Any check fails → hold in a review queue (diff shown, not applied) instead of auto-publishing.
- This keeps freshness automatic for the common case (routine content edits) while bounding risk to actual anomalies (site redesign, page removed, extraction broke) — a strict "always hold for manual review" gate tends to rot unreviewed on a solo project and defeats the point of scraping.

**7.5 — Re-ingestion pipeline**
- Extend `ingest.py` (or a new `scrape_ingest.py`) with: fetch → extract → diff-check → chunk → embed → upsert only new/changed chunks.
- `vectorstore.ensure_collection()` currently deletes and rebuilds the whole collection on every run — fine for a manual full-corpus reload, but wrong for incremental scraped updates (it would wipe everything each run). Switch scraped ingestion to targeted `upsert` + explicit delete of removed sections instead of full rebuild.
- If rebuild-triggered downtime ever matters in practice, revisit with a collection-alias blue-green swap (build new collection, swap alias, drop old).

**7.6 — Scheduling**
- Local scheduler for now (e.g. cron on your machine) — weekly cadence is reasonable for government pages. Revisit a hosted/CI scheduler only if this needs to run somewhere other than your machine.
- Fail loudly on scrape errors (404, blocked, changed page structure) rather than silently continuing to serve stale data.

**7.7 — Validation**
- Keep a small fixed set of test questions and expected source pages; after each ingest run, use `query.py` to confirm retrieval still surfaces the right sources. Catches silent extraction regressions (e.g. a site redesign breaking the boilerplate-stripping rules) before they reach the live tool.

**7.8 — Rollout**
- Run the scraped pipeline into a separate Qdrant collection first and compare retrieval quality against the hand-picked corpus side by side.
- Cut `server.py` over to the scraped collection only once parity is confirmed; keep the hand-picked docs as a fallback/reference, not deleted.

**Decisions locked in:**
- Scope: open to grow beyond the current 6 topics as relevant pages are found — no artificial gate to prove out on 6 first.
- Publishing: risk-based auto-publish with a review gate for anomalies only (see 7.4), not a blanket manual-review-everything policy.
- Scheduling: local cron for now (see 7.6).

---

## Things Worth Understanding Deeply (not just copy-pasting)

- **Why RAG instead of just stuffing all docs in the prompt**: cost, relevance, and staying within context limits as your corpus grows — but also understand when RAG is overkill (small fixed corpus might just fit in context).
- **Embedding model choice tradeoffs**: hosted (OpenAI, quality + cost) vs local (`sentence-transformers`, free + private but need to manage compute).
- **Why grounding + citation prompting matters here specifically**: bureaucratic/legal-adjacent info that's wrong or outdated can genuinely harm someone's visa status — this is a good case study in why RAG systems need explicit "answer only from context, cite sources, say when unsure" instructions rather than letting the model free-associate.
- **MCP tool descriptions matter**: the model decides *whether* to call your tool based on its description — vague descriptions mean the model won't use it when it should.

---

## Suggested Reading Order

1. MCP quickstart (server) — modelcontextprotocol.io docs
2. MCP Python SDK README/examples on GitHub
3. Qdrant Python client quickstart
4. A short RAG conceptual overview (any recent blog/guide covering chunking + retrieval + grounding prompts)
5. Anthropic tool-use docs (for Phase 5, building your own client loop)

---

## Next Step

When ready to start coding, begin with Phase 0 + Phase 1 (environment + corpus), and we'll build `ingest.py` together, testing retrieval quality before touching the MCP server itself.
