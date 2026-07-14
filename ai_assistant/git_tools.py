from __future__ import annotations

import subprocess

from mcp.server.fastmcp import FastMCP

from .config import REPO_ROOT

mcp = FastMCP("localstack-git")

# Read-only allowlist. Never expose write/destructive git ops.
_ALLOWED = {"rev-parse", "branch", "ls-files", "diff", "status", "log"}


def _git(*args: str) -> str:
    if not args or args[0] not in _ALLOWED:
        raise ValueError(f"git subcommand not allowed: {args[:1]}")
    # stdin=DEVNULL is required: under the MCP stdio server the child would
    # otherwise inherit the server's stdin (the JSON-RPC pipe) and corrupt the
    # transport on Windows (anyio BrokenResourceError).
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git failed")
    return proc.stdout.strip()


@mcp.tool()
def current_branch() -> str:
    """Return the current git branch name."""
    return _git("rev-parse", "--abbrev-ref", "HEAD")


@mcp.tool()
def list_files(subdir: str = "") -> list[str]:
    """List tracked files, optionally under a subdirectory."""
    args = ["ls-files"]
    if subdir:
        args.append(subdir)
    out = _git(*args)
    return out.splitlines() if out else []


@mcp.tool()
def diff(base: str = "HEAD") -> str:
    """Return the git diff against a base ref (read-only)."""
    return _git("diff", base)


if __name__ == "__main__":
    mcp.run()
