# Merge plan: `stuttgart-mcp-rag` → `student-flow`

Goal: give StudentFlow's assistant a grounded, cited, offline corpus of Stuttgart
bureaucracy documents by folding this repo in as a second MCP server.

Status: **plan only** — nothing here has been implemented.

---

## 1. What each side actually is today

### StudentFlow (`D-G-X/student-flow`)

A full Docker Compose product, not a script collection:

| Service | Tech | Role |
|---|---|---|
| `nginx` | nginx:alpine | Single public port `8080`; routes `/app` → web-app, `/server/` → API, `/` → LibreChat |
| `web-app` | Next.js 15 / Node 20 | Dashboard, task tracking, embedded chat panel |
| `server` | Spring Boot 4 / Java 21 | REST API (JWT auth, Mongo) **and** an MCP server at `POST /mcp` |
| `librechat` | LibreChat 1.3.9 | The chat UI + LLM orchestration + MCP *client* |
| `ollama` | ollama/ollama | Local LLM, `qwen3:30b` aliased to `assistant` |
| `mongodb` | Mongo w/ replica set | App data + LibreChat's own data |
| `database_seeder` | Python one-shot | Seeds 35 tasks, 4 pathways, 3 priorities, roles, users |

The MCP layer already exists and is Java, via `spring-ai-starter-mcp-server-webmvc`
2.0.0. Two tool groups are registered in
`server/src/main/java/com/dbproj/server/config/McpConfig.java`:

- **`ApplicationMCPService`** — 7 tools over Mongo: `getMyProfile`, `getMyTasks`,
  `getMyRole`, `getAllTasks`, `getTaskById`, `getAllPathways`, `getAllPriorities`,
  `getAllRoles`. Identity comes from the `X-User-Email` header, *not* from an LLM
  argument — LibreChat injects it via `{{LIBRECHAT_USER_EMAIL}}`.
- **`WebSearchMCPService`** — `webSearch` + `webFetch`, proxied to
  `https://ollama.com/api`, gated on `OLLAMA_API_KEY`.

LibreChat registers the server in `librechat/librechat.yaml`:

```yaml
mcpServers:
  student-data:
    type: streamable-http
    url: "http://server:8080/mcp"
    requiresOAuth: false
    headers:
      X-User-Email: "{{LIBRECHAT_USER_EMAIL}}"

mcpSettings:
  allowedAddresses: [ "server:8080" ]
```

### stuttgart-mcp-rag (this repo)

A Python RAG pipeline + MCP server, currently run by hand:

| Piece | Role |
|---|---|
| `server.py` | MCP server, **stdio** transport, 2 tools |
| `chunking.py` / `embeddings.py` / `vectorstore.py` | chunk → embed (`all-MiniLM-L6-v2`, 384-d) → Qdrant |
| `ingest.py` | Hand-picked corpus (`data/docs/`, 8 files) |
| `scrape_*.py` | fetch → extract → review gate → incremental sync (7 URLs) |
| `chat.py` / `query.py` | Standalone Ollama chat client + retrieval REPL (dev tools) |
| `checklists.py` | 5 hardcoded ordered procedures |

Live collection: `stuttgart_bureaucracy_scraped`, ~60 points, both origins
(`hand_picked` / `scraped`) sharing one collection, kept apart by the `origin`
payload field.

---

## 2. The integration decision

The two MCP surfaces are cleanly complementary, and that shape should drive the design:

| | `student-data` (existing) | RAG (incoming) |
|---|---|---|
| Data | Per-user, mutable, Mongo | Shared, versioned, Qdrant |
| Identity | Required (`X-User-Email`) | **None needed** |
| Answers | "What are *my* deadlines?" | "What does the city *require*?" |
| Freshness | Live DB | Weekly scrape + review gate |

### Options considered

**A. RAG as its own container + second MCP server in LibreChat.** ← recommended
LibreChat supports N MCP servers natively. Python stays Python, Java stays Java.
The RAG service needs no user identity, so it needs no auth plumbing.

**B. Port RAG into the Spring server as Java `@Tool`s.**
Spring AI does have an ONNX `all-MiniLM-L6-v2` embedder and a Qdrant client, so
this is technically possible. But ingestion (chunking, scraping, the review gate)
would stay Python regardless — so you'd end up maintaining the *same embedding
config in two languages*, and any drift silently produces incompatible vectors.
Rejected.

**C. Spring server proxies the Python RAG over REST, re-exposing it as a `@Tool`.**
One MCP endpoint, and the tool could read the student's pathway from Mongo before
searching. Real value — but it's a *later* enhancement (§5, M9), not the first move.

### Recommendation: **A**, with C kept open as a follow-up.

---

## 3. Target architecture

```
                          ┌──────────── nginx :8080 ────────────┐
                          │  /app → web-app   /server/ → server │
                          │  /     → librechat                  │
                          └──────────────────┬──────────────────┘
                                             │
                                       ┌─────▼──────┐
                                       │ librechat  │  MCP client
                                       └──┬──────┬──┘
                    ┌─────────────────────┘      └───────────────┐
                    │ student-data                  stuttgart-docs│
                    │ http://server:8080/mcp        http://rag:8000/mcp
              ┌─────▼──────┐                            ┌─────────▼────────┐
              │  server    │                            │   rag (Python)   │
              │ Spring MCP │                            │   MCP + Qdrant   │
              └─────┬──────┘                            └─────────┬────────┘
                    │                                             │
              ┌─────▼──────┐   ┌──────────────┐            ┌──────▼──────┐
              │  mongodb   │◄──│    seeder    │            │   qdrant    │◄── rag_ingest
              └────────────┘   │  (one-shot)  │            └─────────────┘    (one-shot)
                               └──────────────┘
                    ┌────────────┐
                    │   ollama   │ qwen3:30b
                    └────────────┘
```

New services: `qdrant`, `rag`, `rag_ingest`. Everything else unchanged.

Merged repo layout — `rag/` sits alongside the existing top-level services:

```
student-flow/
├── server/          web-app/       librechat/     seeder/      nginx/     mongo/
└── rag/             ← this repo, moved wholesale
    ├── Dockerfile          (new)
    ├── ingest_all.py       (new — one-shot entrypoint)
    ├── server.py           (modified — transport)
    ├── data/docs/          (8 files, tracked)
    ├── data/published/     (11 files, tracked → stack boots offline)
    └── …
```

---

## 4. Phased plan

### M0 — Repo merge mechanics

Both repos have real history worth keeping. Use `git subtree` rather than a copy:

```bash
git remote add rag-origin https://github.com/D-G-X/stuttgart-mcp-rag.git
git fetch rag-origin
git subtree add --prefix=rag rag-origin main
```

Then in the merged repo:

- Delete `rag/.gitignore`'s duplicate entries and fold the meaningful ones
  (`qdrant_storage/`, `data/raw/`, `data/scraped/`, `data/scraped_review/`,
  `.venv/`) into the root `.gitignore` with the `rag/` prefix.
- **Do not carry `rag/.env`** — it is gitignored here and its variables move into
  the single root `.env` (§M3).
- `rag/qdrant_storage/` is a local bind-mount artifact; drop it, Docker uses a
  named volume instead.
- Keep `rag/PLAN.md` and `rag/README.md` as the RAG subsystem's own docs; the root
  README gets a pointer, not a copy.

Decide up front whether `stuttgart-mcp-rag` stays alive as an upstream you'll
`git subtree pull` from, or becomes archived. Recommendation: **archive it** after
the merge — two divergent copies of the ingestion pipeline is exactly the failure
mode §2/B was rejected for.

### M1 — Make the RAG server speak streamable-http

One-line transport change in `rag/server.py`. Verified against the installed
`mcp` 2.0.0 SDK — `run()` forwards `**kwargs` to `run_streamable_http_async`,
which accepts `host`, `port`, `streamable_http_path`, `stateless_http`:

```python
if __name__ == "__main__":
    import os
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run()  # keeps chat.py / MCP Inspector working locally
    else:
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=int(os.environ.get("MCP_PORT", "8000")),
            stateless_http=True,
        )
```

Notes:

- `stateless_http=True` is deliberate — no per-session state to lose across
  restarts, and the RAG tools are pure functions of their arguments anyway.
- The path defaults to `/mcp`, matching how `student-data` is addressed.
- **DNS-rebinding gotcha:** the SDK's `TransportSecuritySettings` defaults to
  `enable_dns_rebinding_protection=True` with an *empty* `allowed_hosts`, which
  would 421 every request. It is only applied if you pass `transport_security=`
  explicitly — omitting it (as above) disables the middleware, which is correct
  for an internal-network-only service. If you later want it on, `allowed_hosts`
  must contain `rag:8000`.

### M2 — Containerize

`rag/Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf \
    HF_HUB_OFFLINE=1

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Bake the embedding model into the image: the container then never reaches
# huggingface.co at runtime, startup isn't a 90 MB download, and the
# "unauthenticated requests to the HF Hub" warning disappears.
RUN HF_HUB_OFFLINE=0 uv run python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .
EXPOSE 8000
CMD ["uv", "run", "python", "server.py"]
```

Image-size warning: `sentence-transformers` pulls full PyTorch (~800 MB–2 GB
depending on wheel). Add a CPU-only torch index to `pyproject.toml` before
building, or the image is unpleasant:

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cpu" }
```

Optional cleanup while you're here: `anthropic`, `openai`, and `ollama` are only
used by the standalone `chat.py` / `chat-anthropic.py` / `embedding-openai-api.py`
dev scripts. Move them to a `dev` dependency group so the production image
doesn't ship three unused API SDKs.

### M3 — Ingestion as a one-shot service

Mirror the `database_seeder` pattern exactly. New `rag/ingest_all.py`:

```python
"""One-shot container entrypoint: wait for Qdrant, then run both pipelines."""
import os, time
import httpx
import ingest
import scrape_ingest

def wait_for_qdrant(url: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(f"{url}/readyz", timeout=2).raise_for_status()
            return
        except Exception:
            time.sleep(2)
    raise SystemExit(f"Qdrant not ready at {url} after {timeout}s")

if __name__ == "__main__":
    wait_for_qdrant(os.environ.get("QDRANT_URL", "http://qdrant:6333"))
    ingest.run()                          # hand-picked corpus -> both collections
    scrape_ingest.run(do_fetch=False)     # replay committed data/published/
```

`do_fetch=False` is the important bit: `data/published/` (11 files) is already
tracked in git, so **the stack boots with zero outbound network calls**. Fetching
is a separate, scheduled concern (M8).

Both pipelines are already idempotent — content-keyed chunk IDs plus origin-scoped
sync mean re-running is a no-op — so this can safely run on every `compose up`.

Doing the readiness wait *in Python* rather than as a compose `healthcheck` avoids
a known annoyance: the `qdrant/qdrant` image is minimal and has neither `curl` nor
a reliable `bash` for the `/dev/tcp` trick, so a naive healthcheck silently never
goes healthy.

### M4 — Compose wiring

```yaml
  qdrant:
    image: qdrant/qdrant:latest
    container_name: studentflow_qdrant
    restart: unless-stopped
    expose: ["6333"]
    volumes:
      - qdrant_data:/qdrant/storage
    networks: [studentflow_network]

  rag_ingest:
    image: studentflow/rag:latest
    container_name: studentflow_rag_ingest
    pull_policy: build
    build:
      context: ./rag
      dockerfile: Dockerfile
    restart: "no"
    depends_on: [qdrant]
    environment:
      - QDRANT_URL=http://qdrant:6333
    command: ["uv", "run", "python", "ingest_all.py"]
    networks: [studentflow_network]

  rag:
    image: studentflow/rag:latest
    container_name: studentflow_rag
    pull_policy: build
    build:
      context: ./rag
      dockerfile: Dockerfile
    restart: unless-stopped
    expose: ["8000"]              # NOT ports: — 8080 belongs to nginx
    environment:
      - QDRANT_URL=http://qdrant:6333
      - MCP_PORT=8000
    depends_on:
      rag_ingest:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import socket,sys; s=socket.create_connection(('127.0.0.1',8000),2); s.close()\""]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 30s
    networks: [studentflow_network]

volumes:
  qdrant_data:
    driver: local
```

Then add to `librechat`'s `depends_on`:

```yaml
      rag:
        condition: service_healthy
```

Root `.env` / `.env.example` additions: none strictly required (all values are
compose-internal), but add `QDRANT_URL` for parity with how the other services
are configured.

### M5 — Register with LibreChat

`librechat/librechat.yaml`:

```yaml
mcpServers:
  student-data:
    type: streamable-http
    url: "http://server:8080/mcp"
    requiresOAuth: false
    headers:
      X-User-Email: "{{LIBRECHAT_USER_EMAIL}}"

  stuttgart-docs:                       # new — no headers, no identity needed
    type: streamable-http
    url: "http://rag:8000/mcp"
    requiresOAuth: false

mcpSettings:
  allowedAddresses: [ "server:8080", "rag:8000" ]
```

`allowedAddresses` is easy to forget and fails closed — LibreChat will refuse the
connection without it.

### M6 — Prompt: teach the model to route between *three* tool groups

This is the highest-risk step, and the one that's least about code. The assistant
now has three overlapping ways to answer "what documents do I need for my visa?":
`getAllTasks` (Mongo), `search_bureaucracy_docs` (RAG), and `webSearch` (live web).
Without explicit precedence, a 30B model will pick inconsistently.

Add to the shared `promptPrefix` anchor in `librechat.yaml`, after the existing
`student-data` bullets:

```
- Use the `stuttgart-docs` tools to look up official requirements, fees,
  deadlines, and office addresses from a curated set of official Stuttgart,
  University of Stuttgart and HFT Stuttgart pages. Prefer these over
  `webSearch`: they are pre-verified, and every result carries the source URL
  and the date it was last checked. Always pass those on to the student.
- Tool precedence: `student-data` for anything about *this student*
  (their tasks, pathway, deadlines); `stuttgart-docs` for what the authorities
  *require*; `webSearch`/`webFetch` only when `stuttgart-docs` returns nothing
  relevant, or when the student asks about something outside its coverage.
- When `stuttgart-docs` returns a "Last checked" date, mention it — the corpus is
  a periodic snapshot, not a live feed.
```

Also extend the existing "ask the user to enable the `student-data` MCP server"
bullet to name `stuttgart-docs` too — LibreChat surfaces MCP servers as toggles in
the chat toolbar, and a disabled server just looks like a dumb assistant.

### M7 — Reconcile the overlapping tool surfaces

Two genuine conflicts the merge creates. Neither is a blocker, but both should be
a deliberate decision rather than an accident:

**`get_procedure_checklist` vs. Mongo `tasks`.** StudentFlow already has 35 task
definitions with descriptions, required/optional documents, tips, pathway codes
and priorities — admin-editable through the web app. This repo's `checklists.py`
has 5 hardcoded procedures. The Mongo side is strictly richer and pathway-aware.

Recommendation: **retire `get_procedure_checklist`** once you've diffed its 5
topics against the 35 Mongo tasks and moved anything the tasks are missing into
the seed data. Until then it stays but is explicitly deprioritized in the prompt.

⚠️ **A regression to know about:** `PASSTHROUGH_TOOLS` in `chat.py` — the mechanism
that fixed the checklist tool by returning its output verbatim without an LLM
relay — **has no equivalent in LibreChat.** LibreChat always feeds tool results
back through the model. The mitigation is that qwen3:30b is far stronger than the
llama3.1:8b that originally mangled this; but if you keep the checklist tool,
re-test that its steps survive the round trip.

**`search_bureaucracy_docs` vs. `webSearch`.** Handled by precedence in M6, but
worth noting: `webSearch` requires `OLLAMA_API_KEY` and fails with a 503 when
unset. The RAG corpus works with no key at all, which makes the merged stack
meaningfully more useful in the default configuration.

Also worth doing while you're here: `search_bureaucracy_docs`'s docstring in
`rag/server.py` still lists only the original six topics and doesn't mention HFT,
even though HFT content is indexed. Since the docstring is the *only* thing
routing the model to the tool, this understates coverage — and HFT is exactly what
StudentFlow's prompt says the student is enrolled in.

### M8 — Scheduled re-scraping in a container world

`crontab.txt` (host cron calling `uv run python scrape_ingest.py`) doesn't apply
once this is Dockerized. Replace it with a host cron that drives compose:

```
0 3 * * 1 cd /path/to/student-flow && docker compose run --rm -e SCRAPE_FETCH=1 rag_ingest >> ./rag/data/scrape_cron.log 2>&1
```

That needs `ingest_all.py` to honour `SCRAPE_FETCH` (`do_fetch=os.environ.get("SCRAPE_FETCH") == "1"`).
Keep it reference-only in the repo as `crontab.txt` is today — don't install it as
part of setup.

The review gate (`scrape_review.py`) still holds anomalous changes for manual
review, so a scheduled fetch can't silently corrupt the corpus.

### M9 — Verification

Run through these against the running stack before calling it done:

| # | Check | Expected |
|---|---|---|
| 1 | `docker compose up --build -d`, all healthy | `rag_ingest` exits 0, `rag` healthy |
| 2 | Qdrant point count | ~60 in `stuttgart_bureaucracy_scraped` |
| 3 | LibreChat toolbar | both `student-data` and `stuttgart-docs` listed |
| 4 | "How much do I need in my blocked account?" | **€11,904**, with source URL — the regression that took several fixes to land here |
| 5 | "How long do I have to register my address?" | "two weeks", not an office address (the ranking fix) |
| 6 | "Where is the nearest Bürgerbüro?" | a real address from the 22-office directory |
| 7 | "What are my open tasks?" | routes to `student-data`, not RAG |
| 8 | "What do I need for the HFT software technology master?" | HFT doc, not Uni Stuttgart |
| 9 | Restart the stack | ingest re-runs as a no-op, counts unchanged |
| 10 | Unset `OLLAMA_API_KEY` | RAG answers still work; only `webSearch` degrades |

Checks 4, 5 and 8 are specifically the failures this repo already debugged — they
are the regression suite for the merge.

### M10 — CI and docs

- `.github/workflows/ci.yml` gains a third job: `uv sync --frozen` + a smoke
  import of `server.py`/`ingest.py` (there is no test suite to run yet).
- Root `README.md` stack table gains `Vector DB — Qdrant` and
  `RAG MCP — Python`, and the directories list gains `rag/`.
- `rag/README.md` gets a short "running inside StudentFlow vs. standalone" note —
  `chat.py`, `query.py` and the stdio transport remain useful for debugging
  retrieval without booting seven containers.

---

## 5. Risks and things that get worse

Being explicit, because most of these are only visible if you've worked on both sides:

1. **`PASSTHROUGH_TOOLS` is lost** (M7). The single most load-bearing hack in
   `chat.py` has no LibreChat equivalent.
2. **Three tool namespaces, one 30B model.** Routing quality is now a prompt
   engineering problem, and it degrades silently — wrong tool, plausible answer.
   Check 7 in M9 exists for this.
3. **Image size.** Torch + sentence-transformers is the largest image in the
   stack by a wide margin. The CPU-only index in M2 is not optional if you care.
4. **`ollama` runs `qwen3:30b`.** Adding a torch-based embedder to the same host
   means two model workloads on one machine. Embedding is cheap here (~60 chunks,
   384-d, only on ingest and per-query), so this should be fine — but it's worth
   watching on a laptop.
5. **Two ingestion pipelines writing one Qdrant collection** is already subtle
   (the origin-scoped delete bug that silently wiped half the collection was found
   late). Containerizing doesn't change the logic, but it does mean re-runs happen
   automatically on every `compose up` rather than when you type them — so the
   idempotency guarantee is now load-bearing. M9 check 9 covers it.
6. **Two mega-chunk sources remain** (study.eu Sperrkonto, both HFT scraped pages
   lack `<h2>` structure). Currently masked because hand-picked docs outrank them.
   Unchanged by the merge, but now shipping in a product rather than a prototype.
7. **`data/published/` is tracked in git**, which is what makes offline boot work
   — but it also means scraped third-party content lives in the repo. Fine for a
   university project; worth a conscious nod if this ever goes public.

---

## 6. Decisions for you before M0

1. **Subtree or plain copy?** Subtree keeps both histories; plain copy is simpler
   and loses the RAG development history. (Recommend subtree.)
2. **Archive `stuttgart-mcp-rag` after the merge, or keep syncing?**
   (Recommend archive.)
3. **Keep or retire `get_procedure_checklist`?** (Recommend retire after diffing
   against the 35 Mongo tasks — but that's a data-migration task, not a deletion.)
4. **Does the merged assistant need pathway-aware retrieval** (option C in §2 —
   Spring proxies RAG and pre-filters by the student's pathway)? Real value, but
   a separate project after this lands.
5. **`main` or a `feat/rag` branch on student-flow?** This touches
   `docker-compose.yml`, `librechat.yaml` and the root README — all files
   teammates likely also touch. (Recommend a branch and a PR.)
