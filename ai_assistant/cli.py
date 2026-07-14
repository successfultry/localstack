from __future__ import annotations

import asyncio
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import REPO_ROOT, Settings
from .llm_client import LLMClient
from .rag import Rag

console = Console()

MCP_TIMEOUT = 15

HELP = r"""[bold]Commands[/bold]
  /help <question>   ask about the project (RAG over README + docs/)
  <question>         same as /help
  /branch            current git branch (via MCP)
  /files \[subdir]    tracked files (via MCP)
  /reindex           rebuild the RAG index
  /quit              exit
"""


class GitMCP:
    """Persistent MCP client: one stdio session for the whole CLI session.

    Spawning the server subprocess per call breaks stdio teardown on Windows
    (ProactorEventLoop -> ExceptionGroup). Keeping one session avoids that and
    matches how an MCP client is meant to hold a connection.
    """

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def open(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ai_assistant.git_tools"],
            cwd=str(REPO_ROOT),
        )
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            async with asyncio.timeout(MCP_TIMEOUT):
                await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session

    async def call(self, tool: str, args: dict | None = None) -> str:
        if self._session is None:
            return "[git error] MCP session not open"
        try:
            async with asyncio.timeout(MCP_TIMEOUT):
                result = await self._session.call_tool(tool, args or {})
        except Exception as e:  # noqa: BLE001
            return f"[git error] {type(e).__name__}: {e}"
        parts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
        return "\n".join(parts).strip()

    async def close(self) -> None:
        if self._stack is None:
            return
        try:
            await self._stack.aclose()
        except BaseException:
            # stdio teardown on Windows can raise noisily; the session already
            # served every call, so shutdown noise is not worth crashing on.
            pass
        finally:
            self._stack = None
            self._session = None


def _ask(rag: Rag, question: str) -> None:
    reply, hits = rag.answer(question)
    console.print(Markdown(reply))
    if hits:
        srcs = ", ".join(dict.fromkeys(h.path for h in hits))
        console.print(f"[dim]sources: {srcs}[/dim]")


async def _run_async(reindex: bool) -> None:
    settings = Settings.load()
    if not settings.openai_api_key:
        console.print("[yellow]No OPENAI_API_KEY in .env — chat/embeddings will fail.[/yellow]")
    llm = LLMClient(settings)
    rag = Rag(settings, llm)

    if reindex or rag.store.count() == 0:
        console.print("[dim]indexing docs...[/dim]")
        stats = rag.reindex(force=reindex)
        console.print(f"[green]index:[/green] {stats}")

    git: GitMCP | None = GitMCP()
    try:
        await git.open()
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]MCP git unavailable: {type(e).__name__}: {e}[/yellow]")
        git = None

    console.print(Panel.fit("LocalStack AI Assistant — Week 7", style="bold cyan"))
    console.print(HELP)

    while True:
        try:
            line = (await asyncio.to_thread(console.input, "[bold green]›[/bold green] ")).strip()
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
            out = await git.call("current_branch") if git else "[git error] MCP unavailable"
            console.print(f"branch: [bold]{out}[/bold]")
        elif line.startswith("/files"):
            subdir = line[len("/files") :].strip()
            if git:
                out = await git.call("list_files", {"subdir": subdir} if subdir else {})
            else:
                out = "[git error] MCP unavailable"
            console.print(out or "[dim](none)[/dim]")
        elif line == "/reindex":
            stats = rag.reindex(force=True)
            console.print(f"[green]index:[/green] {stats}")
        elif line.startswith("/"):
            console.print("[red]unknown command[/red]")
            console.print(HELP)
        else:
            _ask(rag, line)

    if git:
        await git.close()
    rag.store.close()
    console.print("bye")


def run(reindex: bool = False) -> None:
    asyncio.run(_run_async(reindex))
