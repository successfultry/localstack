from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import REPO_ROOT, Settings
from .llm_client import LLMClient
from .rag import Rag

console = Console()

HELP = """[bold]Commands[/bold]
  /help <question>   ask about the project (RAG over README + docs/)
  <question>         same as /help
  /branch            current git branch (via MCP)
  /files [subdir]    tracked files (via MCP)
  /reindex           rebuild the RAG index
  /quit              exit
"""


async def _git_tool(tool: str, args: dict | None = None) -> str:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ai_assistant.git_tools"],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args or {})
            parts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
            return "\n".join(parts).strip()


def _git(tool: str, args: dict | None = None) -> str:
    try:
        return asyncio.run(_git_tool(tool, args))
    except Exception as e:  # noqa: BLE001
        return f"[git error] {e}"


def _ask(rag: Rag, question: str) -> None:
    reply, hits = rag.answer(question)
    console.print(Markdown(reply))
    if hits:
        srcs = ", ".join(dict.fromkeys(h.path for h in hits))
        console.print(f"[dim]sources: {srcs}[/dim]")


def run(reindex: bool = False) -> None:
    settings = Settings.load()
    if not settings.openai_api_key:
        console.print("[yellow]No OPENAI_API_KEY in .env — chat/embeddings will fail.[/yellow]")
    llm = LLMClient(settings)
    rag = Rag(settings, llm)

    if reindex or rag.store.count() == 0:
        console.print("[dim]indexing docs...[/dim]")
        stats = rag.reindex(force=reindex)
        console.print(f"[green]index:[/green] {stats}")

    console.print(Panel.fit("LocalStack AI Assistant — Week 7", style="bold cyan"))
    console.print(HELP)

    while True:
        try:
            line = console.input("[bold green]›[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in {"/quit", "/exit", "/q"}:
            break
        if line == "/help":
            console.print(HELP)
        elif line.startswith("/help "):
            _ask(rag, line[len("/help ") :].strip())
        elif line == "/branch":
            console.print(f"branch: [bold]{_git('current_branch')}[/bold]")
        elif line.startswith("/files"):
            subdir = line[len("/files") :].strip()
            out = _git("list_files", {"subdir": subdir} if subdir else {})
            console.print(out or "[dim](none)[/dim]")
        elif line == "/reindex":
            stats = rag.reindex(force=True)
            console.print(f"[green]index:[/green] {stats}")
        elif line.startswith("/"):
            console.print("[red]unknown command[/red]")
            console.print(HELP)
        else:
            _ask(rag, line)

    rag.store.close()
    console.print("bye")
