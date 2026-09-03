# ALTER EGO — Product Requirements & Build Spec

> A "Digital Twin" that remembers who you are and writes in your voice, powered by a hybrid memory system (knowledge graph + vector + keyword). Built entirely on free-tier services.

This document is the single source of truth for building the project. It is written to be handed directly to **Claude Code**. Build it in the phased order given in Section 11. Do not skip the acceptance criteria in Section 15.

---

## 1. Vision

A visitor lands on the page, gives the app a few writing samples and a handful of facts about themselves, and then chats with their "twin." Every message is parsed into structured memory across three stores. When the visitor sends a new message, the app retrieves the most relevant memories from all three stores, then generates a reply that is grounded in those memories **and** written in the visitor's own tone.

The portfolio impact comes from **transparency**: the frontend shows the knowledge graph growing live and shows exactly which memories were retrieved for each reply, so a stranger immediately understands what the system is doing.

## 2. Goals & non-goals

**Goals**
- Demonstrate a hybrid retrieval memory system (graph + vector + keyword) end to end.
- Demonstrate GraphRAG, recursive summarization, few-shot style transfer, and encryption-at-rest.
- Be deployed, live, publicly usable by anyone, and interactive in real time.
- Run on 100% free-tier services with no credit card required.
- Be legible to a non-technical reviewer within 30 seconds via a "load example persona" path.

**Non-goals**
- Production scale, multi-region, or high availability.
- User accounts / authentication (sessions are anonymous and ephemeral).
- Perfect style cloning — "recognizably in the user's voice" is enough.
- Mobile-native apps (responsive web only).

## 3. Users & the demo persona

- **Primary user:** a portfolio reviewer or curious visitor with no context.
- **Onboarding must be frictionless.** A prominent "Load example persona" button seeds a prebuilt twin (writing samples + facts already ingested) so a visitor can chat and see it working before building their own.
- Each visitor gets an isolated, anonymous `session_id`. No login.

## 4. Tech stack (all free tier)

**Backend**
- Python 3.11+, FastAPI, Uvicorn.
- LangChain as the orchestration layer (`langchain`, `langchain-google-genai`, `langchain-neo4j`, `langchain-qdrant`).
- `google-generativeai` (Gemini SDK), `neo4j` (driver), `qdrant-client`, `networkx`, `rank_bm25`, `cryptography`, `pydantic`, `python-dotenv`, `sse-starlette` (streaming).

**External services (each free tier, no credit card)**
| Purpose | Service | Notes / limits |
|---|---|---|
| LLM (extraction, summarization, generation) | **Google Gemini Flash** via AI Studio API | Permanent free tier. ~10–15 requests/min, ~250k tokens/min, ~500–1,500 requests/day. Use the current free Flash model ID (check AI Studio; e.g. `gemini-2.5-flash` / `gemini-flash-lite`). |
| Embeddings | **`gemini-embedding-001`** | Free ~1,500 req/day. Truncate output to **768 dimensions** via MRL to save storage. (`text-embedding-004` is deprecated as of Jan 2026 — do not use it.) |
| Knowledge graph | **Neo4j Aura Free** | Always free, no card. ~250MB ceiling. Pauses after ~7 days idle — reactivate from the console. |
| Vector store | **Qdrant Cloud Free** | 1GB free cluster. Single collection, filter by `session_id`. |
| Keyword search | **`rank_bm25`** (in-process) | No external service; the "keyword" leg of hybrid search. |
| Backend hosting | **Render Free** web service | 750 hrs/mo. Sleeps after 15 min idle → 10–30s cold start. Design a warm-up ping + loading state. |
| Frontend hosting | **Vercel** or **Netlify** free | Static React build. |
| Source / CI | **GitHub** | Free. |

**Alternatives (documented fallbacks, still free):**
- Embeddings can instead run locally with `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dims) to avoid Gemini quota — but this adds ~100MB+ RAM, tight on Render Free. Prefer the Gemini embedding API.
- Vector store can instead be Neo4j's native vector index (removes Qdrant entirely) or `pgvector` on Render Postgres. Keep Qdrant as the default for a cleaner "hybrid" story.

**Frontend**
- React + Vite + TypeScript, Tailwind CSS.
- `react-force-graph-2d` (or `vis-network`) for the live knowledge graph.
- Native `EventSource` for streaming chat.

## 5. System architecture

```
User input (chat message OR writing sample / fact)
        │
        ▼
  Ingestion (Gemini Flash)
   ├─ entity + relationship extraction ──► Neo4j knowledge graph
   ├─ embedding (gemini-embedding-001) ──► Qdrant vector store
   └─ recursive summarization (on threshold) ──► summary memories
        │
        ▼  (on a new chat message)
  Hybrid retriever
   ├─ graph traversal (entities related to the query)
   ├─ vector search (semantic top-k, session-filtered)
   └─ BM25 keyword search (over session texts)
   └─► merge + rerank → top context
        │
        ▼
  Style-transfer generation (Gemini Flash + few-shot on user's samples)
        │
        ▼
  Twin reply (streamed)  +  retrieved-memories payload  +  graph delta
```

## 6. Data model

### 6.1 Neo4j (knowledge graph)
- All nodes and relationships carry a `session_id` property for isolation.
- Node labels (from extraction): `Person`, `Place`, `Organization`, `Project`, `Preference`, `Event`, `Object`, `Concept`. Each has `{ name, session_id, created_at }`.
- Relationships are typed by the extractor, e.g. `WORKS_AT`, `LIVES_IN`, `LIKES`, `KNOWS`, `WORKED_ON`, `HAPPENED_ON`. Each carries `{ session_id }`.
- Use LangChain `LLMGraphTransformer` to convert text → `GraphDocument`, then `Neo4jGraph.add_graph_documents(...)`. Inject `session_id` on every node/rel before writing.
- **Every Cypher query MUST filter by `session_id`.** Never return cross-session data.

### 6.2 Qdrant (vector + payload)
- One collection `memories`, vector size **768**, distance **Cosine**.
- Point payload: `{ session_id, text_encrypted, source_type, created_at }` where `source_type ∈ {"sample","fact","message","summary"}`.
- All searches use a `Filter` on `session_id`.
- `text` is stored **encrypted** (see 6.4); decrypt server-side after retrieval.

### 6.3 Summaries (recursive summarization)
- Maintain a per-session running count of `"message"` memories.
- When raw messages for a session exceed `SUMMARY_THRESHOLD` (default 12), summarize the oldest `SUMMARY_BATCH` (default 8) messages into one `"summary"` memory (embedded + stored), and mark those raw messages so they are excluded from future BM25/vector recall (e.g. add `summarized: true` to payload and filter it out). Summaries themselves can be re-summarized when they accumulate → recursive.

### 6.4 Encryption at rest (`cryptography` / Fernet)
- App holds a master key in `FERNET_KEY` (env). Encrypt the raw `text` of every stored memory (Qdrant payload and any Memory node content) with Fernet before writing; decrypt server-side only when assembling LLM context or the retrieved-memories panel.
- Graph **entity labels** stay plaintext (they drive the visualization and are low-sensitivity). Document this tradeoff in the README.
- Stretch: derive a per-session key from the master key + a session salt.

## 7. Functional requirements

- **FR1 — Session creation.** Create an anonymous session, return `session_id`.
- **FR2 — Ingestion.** Accept writing samples and facts; extract entities/relationships → graph; embed → vector; return counts.
- **FR3 — Chat.** Given a message: run hybrid retrieval, generate a styled reply, stream it, and also return the retrieved memories (with their source leg) and the graph delta.
- **FR4 — Hybrid retrieval.** Combine graph traversal, vector search, and BM25; merge and rerank; cap total context tokens.
- **FR5 — Style transfer.** Few-shot the generation with 2–4 of the user's writing samples so the reply matches their tone.
- **FR6 — Recursive summarization.** Compress old messages per Section 6.3.
- **FR7 — Encryption.** Encrypt stored memory text at rest per Section 6.4.
- **FR8 — Session isolation.** Every store access filters by `session_id`.
- **FR9 — Example persona.** One-click load of a prebuilt, pre-ingested twin.
- **FR10 — Live graph.** Frontend renders and live-updates the session's knowledge graph.
- **FR11 — Guardrails.** Per-session rate limit, max message length, capped requests (Section 13).

## 8. API specification

Base path `/api`. JSON unless noted. All endpoints except `/health` and `/session` require a valid `session_id`.

- `POST /session` → `{ session_id }`. Creates session state.
- `POST /ingest` → body `{ session_id, text, source: "sample"|"fact" }` → `{ entities_added, relationships_added, memory_id }`.
- `POST /chat` → body `{ session_id, message }` → **SSE stream**. Events: `token` (streamed reply chunks), then a final `meta` event `{ retrieved_memories: [{text, source, score}], graph_delta: {nodes, edges} }`.
- `GET /graph?session_id=` → `{ nodes: [{id, label, type}], edges: [{source, target, type}] }` for visualization.
- `POST /load-example` → body `{ session_id }` → ingests the bundled persona; returns ingestion summary.
- `GET /health` → `{ status: "ok" }` (also used as warm-up ping).

**Retrieved-memory source values:** `"graph"`, `"vector"`, `"keyword"` (a memory found by multiple legs lists all).

## 9. Frontend specification

**Layout:** three-pane responsive app.
1. **Left — Onboarding & controls:** writing-samples textarea, facts textarea, "Add to memory" button, "Load example persona" button, a short "How it works" accordion.
2. **Center — Chat:** message list with streaming twin replies; input box; token-by-token rendering.
3. **Right — Memory inspector:** (a) live **knowledge graph** (`react-force-graph-2d`) that updates after each turn; (b) **retrieved memories** list for the latest reply, each tagged with its source leg (graph / vector / keyword) and score.

**Behaviors**
- On load, create a session (`POST /session`) and show an empty-state prompt suggesting "Load example persona."
- Show a warm-up/loading state on first request (Render cold start).
- After each `chat` turn, refresh the graph from the `graph_delta` (or re-fetch `/graph`) and populate the retrieved-memories panel.
- Clearly label everything so a first-time viewer understands the graph + retrieval without reading docs.

**Design:** clean, modern, single accent color; the graph and memory panel are the visual centerpiece. Follow good contrast and spacing; no clutter.

## 10. Prompt templates

Store these in `backend/prompts/`. Tune wording during implementation.

**10.1 Entity/relationship extraction** (or use `LLMGraphTransformer` with `allowed_nodes`/`allowed_relationships` set to the labels in 6.1):
```
You extract a knowledge graph from text about a person.
Return STRICT JSON: {"nodes":[{"name","type"}],"relationships":[{"source","type","target"}]}.
Allowed node types: Person, Place, Organization, Project, Preference, Event, Object, Concept.
Use the person as "User" when the text is first-person. Only extract facts explicitly stated.
Text: """{input}"""
```

**10.2 Recursive summarization:**
```
Summarize the following memories about the user into a compact third-person profile note.
Preserve concrete facts, names, preferences, and relationships. Omit filler. 4 sentences max.
Memories: """{batch}"""
```

**10.3 Style-transfer generation:**
```
You are the user's digital twin. Reply to the new message AS the user, in their voice.

MATCH THE USER'S STYLE from these samples (tone, sentence length, punctuation, vocabulary):
{writing_samples}

GROUND YOUR REPLY in these retrieved memories (do not invent facts):
{retrieved_context}

New message: {message}

Reply in first person, in the user's style. Do not mention that you are an AI or a twin.
```

## 11. Build plan for Claude Code (phased)

Build in this order. Each phase must run and be testable before the next.

- **Phase 0 — Scaffold.** Repo structure (Section 12), `.env.example`, FastAPI app with `/health`, Vite React app that calls `/health`. Deploy nothing yet; run locally.
- **Phase 1 — LLM round-trip.** `/session` + a minimal `/chat` that just calls Gemini Flash and streams the reply (no memory yet). Confirm streaming works end to end in the UI.
- **Phase 2 — Vector memory.** Wire Gemini embeddings + Qdrant. `/ingest` embeds & stores; `/chat` does vector top-k (session-filtered) and injects it as context. Add the retrieved-memories panel (vector only).
- **Phase 3 — Graph memory (GraphRAG).** Wire Neo4j Aura + `LLMGraphTransformer`. `/ingest` writes entities/relationships; `/graph` returns the graph; frontend renders it live. Add graph-traversal retrieval to `/chat`.
- **Phase 4 — Hybrid retrieval.** Add BM25; build the merge+rerank that combines graph + vector + keyword, dedupes, tags each memory's source, and caps context tokens.
- **Phase 5 — Style transfer.** Few-shot the generation with stored writing samples so replies match tone.
- **Phase 6 — Recursive summarization.** Implement Section 6.3.
- **Phase 7 — Encryption + isolation hardening.** Fernet-encrypt stored text; audit every store access for `session_id` filtering.
- **Phase 8 — Example persona + guardrails.** Bundle a persona and `/load-example`; add rate limiting, max length, request caps.
- **Phase 9 — Polish + deploy.** Warm-up handling, error states, README, then deploy (Section 14).

## 12. Repository structure

```
alter-ego/
├── PRD.md
├── README.md
├── render.yaml                 # backend blueprint
├── .env.example
├── backend/
│   ├── main.py                 # FastAPI app + routes
│   ├── config.py               # env/settings via pydantic
│   ├── deps.py                 # clients: gemini, neo4j, qdrant
│   ├── ingestion/
│   │   ├── extract.py          # entities/relationships → graph
│   │   ├── embed.py            # gemini embeddings
│   │   └── summarize.py        # recursive summarization
│   ├── memory/
│   │   ├── graph_store.py      # Neo4j read/write, session-scoped
│   │   ├── vector_store.py     # Qdrant read/write, session-scoped
│   │   └── keyword_store.py    # BM25 over session texts
│   ├── retrieval/
│   │   └── hybrid.py           # merge + rerank
│   ├── generation/
│   │   └── style_transfer.py   # few-shot styled reply
│   ├── crypto/
│   │   └── vault.py            # Fernet encrypt/decrypt
│   ├── prompts/                # the templates in Section 10
│   ├── data/example_persona.json
│   ├── guardrails.py           # rate limit, caps
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── package.json
    ├── src/
    │   ├── App.tsx
    │   ├── api.ts              # session, ingest, chat(SSE), graph
    │   ├── components/
    │   │   ├── Onboarding.tsx
    │   │   ├── ChatPanel.tsx
    │   │   ├── GraphView.tsx
    │   │   └── RetrievedMemories.tsx
    │   └── styles/
    └── vite.config.ts
```

## 13. Environment variables & guardrails

`.env.example`:
```
GEMINI_API_KEY=
GEMINI_CHAT_MODEL=gemini-2.5-flash      # use current free Flash id
GEMINI_EMBED_MODEL=gemini-embedding-001
EMBED_DIM=768
NEO4J_URI=
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=
QDRANT_URL=
QDRANT_API_KEY=
FERNET_KEY=                              # generate with Fernet.generate_key()
FRONTEND_ORIGIN=                         # for CORS
RATE_LIMIT_PER_MIN=8
MAX_MESSAGE_CHARS=2000
MAX_REQUESTS_PER_SESSION=60
```

**Guardrails (required, because the demo is public and the LLM key is shared):**
- Per-`session_id` rate limit (default 8 req/min) and a hard `MAX_REQUESTS_PER_SESSION`.
- Reject messages over `MAX_MESSAGE_CHARS`.
- Stay under Gemini free RPM: serialize/queue LLM calls and add exponential backoff on HTTP 429.
- Never expose keys to the frontend; all model calls are server-side.

## 14. Deployment

1. Push repo to GitHub.
2. Provision free services: create Neo4j Aura Free instance (save URI + password), create Qdrant Cloud free cluster (save URL + API key), get a Gemini API key from AI Studio.
3. **Backend on Render:** New → Blueprint → point at repo. `render.yaml` defines a Python web service, start command `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`. Set all env vars in the dashboard. Set CORS to allow the frontend origin.
4. **Frontend on Vercel/Netlify:** import repo, build `frontend/`, set `VITE_API_BASE` to the Render URL.
5. Add a client-side warm-up: ping `/health` on page load to spin the backend up before the first real request.
6. Smoke-test the live URL against every acceptance criterion in Section 15.

## 15. Acceptance criteria (definition of done)

- A brand-new visitor can load the site, click **Load example persona**, and get a styled, memory-grounded reply within one interaction.
- Ingesting a fact (e.g. "I work at Acme as a designer") creates the expected nodes/edges, visible in the live graph within one refresh.
- A chat reply visibly reflects an earlier-stated fact **and** is written in a tone matching the provided samples.
- The retrieved-memories panel shows real memories tagged by source leg (graph / vector / keyword) for the latest reply.
- Two different sessions never see each other's memories or graph.
- Stored memory text is encrypted at rest (verify raw Qdrant payload is ciphertext).
- After enough turns, older messages are compressed into a summary memory and still recalled.
- The whole thing runs on the free tiers above with no billing enabled.

## 16. Stretch goals

- Per-session encryption keys.
- Neo4j native vector index to drop Qdrant (single-DB hybrid).
- "Explain this reply" view that traces each sentence to its source memory.
- Adjustable retrieval weights (graph vs vector vs keyword) as a live slider.
- Export/import a twin as an encrypted JSON blob.

---

*Build phase by phase. Keep every store access session-scoped. Keep secrets server-side. Ship the example persona early — it is what makes the project legible.*
