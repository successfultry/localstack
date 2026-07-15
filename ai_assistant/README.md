# Week 07 — Developer Assistant (AI Advent #8)

Dev assistant that understands the **LocalStack** codebase via RAG over its docs, plus live
git context through **MCP**. This repo is a fork of `localstack/localstack`; all assistant code
lives in `ai_assistant/` and never touches LocalStack core.

## Structure

```text
ai_assistant/
├── main.py          # entrypoint: python -m ai_assistant.main
├── cli.py           # terminal UI + command loop; persistent MCP client session
├── config.py        # settings + repo-root .env loading, paths
├── llm_client.py    # OpenAI Responses API chat + embeddings
├── rag.py           # discover -> chunk -> embed -> retrieve, with citations
├── store.py         # SQLite vector store + sha-based incremental reindex
├── git_tools.py     # MCP server (FastMCP): read-only git tools
├── reviewer.py      # Day 32 PR review pipeline
├── support/         # Day 33 support assistant mini-service
│   ├── assistant.py # support orchestration + one-shot CLI
│   ├── crm_tools.py # JSON CRM MCP tools (also callable as plain funcs)
│   ├── service.py   # stdlib HTTP service (/health, /support/answer)
│   └── data/
│       ├── users.json
│       ├── tickets.json
│       └── faq.md
├── requirements.txt
├── .env.example
└── README.md
```

No extra packages/subfolders — one file per responsibility. `reviewer.py` is added only when
Day 32 (PR code review) starts.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r ai_assistant/requirements.txt

cp ai_assistant/.env.example .env   # then fill OPENAI_API_KEY (repo-root .env)
```

`.env` lives at the **repo root** and is gitignored.

## Environment

The assistant is OpenAI-only: one key for both Responses API chat and embeddings.

```env
OPENAI_API_KEY=sk-your-openai-key
LLM_MODEL=gpt-5.5
EMBED_MODEL=text-embedding-3-large
RAG_INCLUDE=README.md,DOCKER.md,AGENTS.md,docs/**/*.md,docs/**/*.rst,localstack-core/localstack/openapi.yaml,ai_assistant/support/data/faq.md
INDEX_PATH=ai_assistant/.index.db
```

| Var | Purpose |
|-----|---------|
| `OPENAI_API_KEY` | chat + embeddings (single key, no base URLs) |
| `LLM_MODEL` | chat model (Responses API). Fallback to `gpt-4o` if `gpt-5.5` is not on your account |
| `EMBED_MODEL` | embedding model for RAG |
| `RAG_INCLUDE` | comma-separated globs (relative to repo root) RAG may index — **docs only** |
| `INDEX_PATH` | SQLite index location (auto-created, gitignored) |

## Run

```bash
python -m ai_assistant.main            # start CLI; indexes on first run
python -m ai_assistant.main --reindex  # force rebuild the RAG index
```

## Commands

| Command | What it does |
|---------|--------------|
| `/help <question>` | ask about the project (RAG over docs + citations) |
| `<question>` | same as `/help` |
| `/branch` | current git branch (via MCP) |
| `/files [subdir]` | tracked files, optionally under a subdir (via MCP) |
| `/reindex` | rebuild the RAG index |
| `/quit` | exit |

---

## Day 31 — Developer Assistant

### Goal

An assistant that understands the project:

- **RAG** over `README`, `docs/`, and the LocalStack `openapi.yaml` API spec.
- **MCP** for live project context — at minimum the current git branch (files/diff as bonus).
- **`/help`** answers questions about the project using the retrieved docs + context.

### How it works

- `rag.py` discovers files by `RAG_INCLUDE`, chunks them (1200 chars / 200 overlap), embeds
  batches via OpenAI, and stores vectors in SQLite. Reindex is incremental by file `sha256`.
- Retrieval is cosine similarity over stored vectors; answers cite sources as `[path]` and fall
  back to "I don't know" when the best score is below `MIN_SCORE` (anti-hallucination).
- `git_tools.py` is a real **FastMCP** server exposing read-only git tools behind an allowlist.
  `cli.py` connects as an MCP client and holds **one persistent stdio session** for the whole run.

### RAG corpus (docs only)

Indexed: root `README.md`, `DOCKER.md`, `AGENTS.md`, everything under `docs/`, and
`localstack-core/localstack/openapi.yaml`. The thousands of auto-generated AWS API type files
(`localstack-core/.../aws/api/**`) and `.cursor/docs/` learning notes are **never** indexed —
they are noise for a project Q&A assistant and expensive to embed.

> RAG indexing (~14 files) is separate from the MCP `/files` tool, which lists *all* git-tracked
> files in the repo. Different mechanisms.

### MCP git tools (read-only)

Allowlist in `git_tools.py`: `rev-parse`, `branch`, `ls-files`, `diff`, `status`, `log`. Any
write/destructive git op is rejected. The git child runs with `stdin=DEVNULL` so it never
inherits the MCP server's JSON-RPC stdio (required on Windows to avoid transport corruption).

### What to verify

- `--reindex` prints a non-zero index, e.g. `index: {'files': 14, ..., 'chunks': 146}`.
- `/help` about project structure returns an answer **with `sources:`** citations.
- An out-of-corpus question (e.g. kubernetes ingress) returns the "I don't know" fallback.
- `/branch` returns the real branch via MCP (matches `git rev-parse --abbrev-ref HEAD`).
- `/files ai_assistant` lists this package's files via MCP.

### Troubleshooting

- `model_not_found` / access denied → set `LLM_MODEL=gpt-4o` (or a model on your account).
- `No OPENAI_API_KEY in .env` → fill the repo-root `.env`.
- Empty answers / `chunks: 0` → run `--reindex`; check `RAG_INCLUDE` paths exist.
- `MCP git unavailable` on startup → git not on PATH, or the server module failed to import.

### Example output

```text
> python -m ai_assistant.main --reindex
indexing docs...
index: {'files': 14, 'indexed': 14, 'skipped': 0, 'chunks': 146}
╭──────────────────────────────────╮
│ LocalStack AI Assistant — Week 7 │
╰──────────────────────────────────╯

› /help how is the LocalStack project structured and what is it?
LocalStack is a cloud service emulator that runs in a single container ... [README.md]
sources: README.md, DOCKER.md, docs/localstack-concepts/README.md

› /branch
branch: week7/day31-assistant

› /files ai_assistant
ai_assistant/.env.example
ai_assistant/README.md
ai_assistant/cli.py
ai_assistant/config.py
ai_assistant/git_tools.py
ai_assistant/llm_client.py
ai_assistant/main.py
ai_assistant/rag.py
ai_assistant/store.py

› /quit
bye
```

## Day 32 — AI PR Review Pipeline

### Goal

Reactive PR review that runs on GitHub Actions and posts one summary comment with:

- potential bugs
- architectural concerns
- recommendations

### Implementation

- `ai_assistant/reviewer.py`:
  - reads PR context (number/repo) from CLI args or `GITHUB_EVENT_PATH`
  - loads changed files + diff via `gh pr view` / `gh pr diff`
  - uses docs RAG (README/docs/openapi) for policy/context
  - passes changed code directly from diff into the review prompt
  - generates review with OpenAI and model fallback `gpt-5.5 -> gpt-4o` on unavailable model
  - posts/updates a single PR comment marked with `<!-- localstack-ai-review -->`
- `.github/workflows/ai-review.yml`:
  - trigger: `pull_request` (`opened`, `synchronize`, `reopened`, `ready_for_review`)
  - concurrency per PR with cancel-in-progress
  - minimal permissions: `contents: read`, `pull-requests: write`
  - caches `ai_assistant/.index.db` with `actions/cache`
  - builds index on cache miss via `python -m ai_assistant.reviewer --reindex-only`
  - runs reviewer via `python -m ai_assistant.reviewer`

### Day 32 local checks

```bash
python -m py_compile ai_assistant/reviewer.py
python -m ai_assistant.reviewer --reindex-only
# Optional local test when you have repo/pr context:
# python -m ai_assistant.reviewer --repo successfultry/localstack --pr 123 --dry-run
```

### Day 32 demo flow

1. Push branch with `.github/workflows/ai-review.yml` and `ai_assistant/reviewer.py`.
2. Open or update a PR in `successfultry/localstack`.
3. Wait for `AI Review` workflow to finish.
4. Show the bot summary comment in the PR discussion.

### Day 32 FAQ (from chat)

- Do I need to host my own external service?  
  No. For this task, GitHub Actions runs everything on the GitHub runner. You only add
  `OPENAI_API_KEY` as a GitHub secret.
- Must it be reactive (automatic), not manual?  
  Yes. The required mode is trigger-based (`pull_request`), not a manually started local script.
- Must this be part of the same project, or can it be separate?  
  Both are acceptable in general, but here it is integrated into this repo as a coherent Week 7
  continuation.

### Done / next

- Done: Day 31 local assistant + Day 32 reactive PR review pipeline.
- Next (optional): inline comments by diff position, code-search tools for broader context.

## Day 33 — User Support Assistant

### Goal

Mini support assistant for LocalStack that answers user questions with:

- CRM context (user profile + ticket details)
- RAG over project docs/openapi + support FAQ
- clear anti-hallucination behavior when docs are insufficient

### Architecture

- `support/crm_tools.py`:
  - local JSON CRM (`support/data/users.json`, `support/data/tickets.json`)
  - functions: `get_ticket`, `get_user`, `list_user_tickets`
  - same functions exposed as FastMCP tools (`python -m ai_assistant.support.crm_tools`)
- `support/assistant.py`:
  - orchestrates ticket/user fetch + RAG retrieval + LLM answer generation
  - one-shot CLI entry:
    - `python -m ai_assistant.support.assistant --ticket TCK-1001 --question "..."`
  - response JSON fields:
    - `ticket_id`, `answer`, `sources`, `user_context_used`, `ticket`, `user`
- `support/service.py`:
  - stdlib `http.server` mini-service (no FastAPI)
  - endpoints:
    - `GET /health`
    - `POST /support/answer` with body `{"ticket_id":"...","question":"..."}`

### Anti-hallucination behavior

- Uses existing `rag.MIN_SCORE`.
- If no retrieved chunk is above threshold, assistant explicitly says docs context is insufficient,
  does not invent LocalStack facts, and answers only from ticket/user context.

### Day 33 run commands

```bash
python -m py_compile ai_assistant/support/*.py

# optional upfront reindex
python -m ai_assistant.support.service --reindex

# primary demo path (Windows-friendly for Cyrillic)
python -m ai_assistant.support.assistant --ticket TCK-1001 --question "Почему не работает авторизация?"

# English example
python -m ai_assistant.support.assistant --ticket TCK-2002 --question "Why is authorization failing?"
```

HTTP mode:

```bash
python -m ai_assistant.support.service --host 127.0.0.1 --port 8787

curl -s -X POST "http://127.0.0.1:8787/support/answer" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TCK-1001","question":"Почему не работает авторизация?"}'

curl -s -X POST "http://127.0.0.1:8787/support/answer" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TCK-2002","question":"Why is authorization failing?"}'
```

### Example output shape

```json
{
  "ticket_id": "TCK-1001",
  "answer": "Диагноз ...",
  "sources": [
    "ai_assistant/support/data/faq.md",
    "localstack-core/localstack/openapi.yaml"
  ],
  "user_context_used": {
    "user_id": "u_100",
    "plan": "community",
    "os_docker": "Windows 11 + Docker Desktop 4.32 (WSL2)",
    "localstack_version": "3.7.2",
    "preferred_language": "ru"
  },
  "ticket": {},
  "user": {}
}
```

### What to verify

- `python -m ai_assistant.support.assistant ...` returns JSON with non-empty `answer`.
- `sources` includes FAQ/docs when relevant.
- unknown ticket returns clear error.
- `/health` returns `{"status":"ok"}`.
- Russian question/user gives Russian answer.

### Day 33 video flow

1. Show `support/data/users.json` + `support/data/tickets.json` + `support/data/faq.md`.
2. Run one-shot CLI command with Russian question.
3. Show answer structure: diagnosis, cause, steps, follow-up data request, sources.
4. Start HTTP service, hit `/health`.
5. Call `/support/answer` via `curl` and show JSON response.

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 31 | Developer assistant: RAG over README/docs/openapi + MCP git context + `/help` | `-m ai_assistant.main --reindex`, then `/help ...`, `/branch`, `/files ai_assistant` | `config.py`, `llm_client.py`, `rag.py`, `store.py`, `git_tools.py`, `cli.py`, `main.py` | done | _link_ |
| 32 | Reactive AI code review on PR (`pull_request` trigger, summary comment) | `-m ai_assistant.reviewer --reindex-only`, workflow run on PR | `reviewer.py`, `.github/workflows/ai-review.yml` | done | _link_ |
| 33 | User support assistant (CRM JSON + MCP tools + RAG FAQ/docs + HTTP mini-service) | `-m ai_assistant.support.assistant --ticket ... --question ...`, optional `-m ai_assistant.support.service` | `support/crm_tools.py`, `support/assistant.py`, `support/service.py`, `support/data/*`, `config.py`, `.env.example`, `README.md` | done | _link_ |
