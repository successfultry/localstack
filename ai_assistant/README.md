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
RAG_INCLUDE=README.md,DOCKER.md,AGENTS.md,docs/**/*.md,docs/**/*.rst,localstack-core/localstack/openapi.yaml
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

### Done / not done

- Done: docs+openapi RAG with citations, incremental SQLite index, anti-hallucination fallback,
  persistent MCP client, read-only git tools (branch/files/diff), `/help` loop.
- Not done (later): Day 32 PR code-review pipeline (`reviewer.py` + `.github/workflows/`),
  code search tools over source.

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 31 | Developer assistant: RAG over README/docs/openapi + MCP git context + `/help` | `-m ai_assistant.main --reindex`, then `/help ...`, `/branch`, `/files ai_assistant` | `config.py`, `llm_client.py`, `rag.py`, `store.py`, `git_tools.py`, `cli.py`, `main.py` | done | _link_ |
| 32 | AI code review on a PR | — | `reviewer.py`, `.github/workflows/ai-review.yml` | todo | _link_ |
