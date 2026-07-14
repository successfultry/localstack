# LocalStack AI Assistant (AI Advent #8, Week 7)

Dev assistant that understands the **LocalStack** codebase via RAG over its docs, plus
git context through MCP. This repo is a fork of `localstack/localstack`; all assistant
code lives in `ai_assistant/` and never touches LocalStack core.

## Day targets

- **Day 31**: RAG over `README` + `docs/`; MCP exposes git branch (min); `/help` answers
  questions about the project using docs + context.
- **Day 32**: AI code review on a PR.

## Setup

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
pip install -r ai_assistant/requirements.txt

cp ai_assistant/.env.example .env   # then fill keys (repo root .env)
```

`.env` lives at the **repo root** and is gitignored. The assistant uses OpenAI for both
Responses API chat and embeddings:

```env
OPENAI_API_KEY=sk-your-openai-key
LLM_MODEL=gpt-5.5
EMBED_MODEL=text-embedding-3-large
RAG_INCLUDE=README.md,DOCKER.md,AGENTS.md,docs/*.md,docs/**/*.md,docs/*.rst,docs/**/*.rst
INDEX_PATH=ai_assistant/.index.db
```

## Run

```bash
python -m ai_assistant.main            # starts the CLI, /help loop
python -m ai_assistant.main --reindex  # rebuild the RAG index
```

## Layout

| file | responsibility |
|------|----------------|
| `config.py` | settings + `.env` loading, paths |
| `llm_client.py` | OpenAI Responses API chat + embeddings |
| `rag.py` | index/retrieve docs (README + `docs/`), citations |
| `store.py` | SQLite vector index / embeddings cache |
| `git_tools.py` | MCP git tools (branch; optional files/diff) — read-only |
| `cli.py` | terminal UI, `/help` command loop |
| `main.py` | thin entrypoint |
| `reviewer.py` | Day 32 PR code review (added when Day 32 starts) |

RAG indexes **docs only** (`RAG_INCLUDE` in `.env`). The `.cursor/docs/` learning notes
are never indexed.
