from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT

PROJECT_ROOT = REPO_ROOT / "ai_assistant"
_BINARY_SUFFIXES = {
    ".db",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".bin",
    ".pyc",
}


def _resolve_project_path(path: str) -> Path:
    target = (REPO_ROOT / path).resolve()
    if not str(target).startswith(str(PROJECT_ROOT.resolve())):
        raise ValueError("path is outside ai_assistant/")
    if target.name == ".env":
        raise ValueError("reading/writing .env is forbidden")
    return target


def _read_text(path: Path) -> str:
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _run_git(args: list[str], timeout: int = 30) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git command failed")
    return proc.stdout


def read_project_file(path: str) -> str:
    target = _resolve_project_path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(path)
    return target.read_text(encoding="utf-8")


def search_project_files(query: str, roots: list[str] | None = None) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        raise ValueError("query is required")
    roots = roots or ["ai_assistant"]

    root_paths: list[Path] = []
    seen_roots: set[str] = set()
    for root in roots:
        root_path = _resolve_project_path(root)
        if not root_path.exists() or not root_path.is_dir():
            raise FileNotFoundError(root)
        key = str(root_path)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        root_paths.append(root_path)

    hits: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for root_path in root_paths:
        for file_path in sorted(root_path.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name == ".env" or file_path.suffix.lower() in _BINARY_SUFFIXES:
                continue
            rel = str(file_path.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel in seen_files:
                continue
            seen_files.add(rel)
            text = _read_text(file_path)
            if not text:
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    hits.append(
                        {
                            "path": rel,
                            "line": idx,
                            "snippet": line.strip()[:240],
                        }
                    )
    return hits


def write_project_file(path: str, content: str) -> None:
    target = _resolve_project_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def changed_files() -> list[str]:
    modified = _run_git(["diff", "--name-only", "--", "ai_assistant"]).splitlines()
    staged = _run_git(["diff", "--cached", "--name-only", "--", "ai_assistant"]).splitlines()
    untracked = _run_git(["ls-files", "--others", "--exclude-standard", "--", "ai_assistant"]).splitlines()

    merged = []
    seen: set[str] = set()
    for path in [*modified, *staged, *untracked]:
        normalized = path.strip().replace("\\", "/")
        if not normalized or normalized in seen:
            continue
        if normalized.endswith("/.env") or normalized == ".env":
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged


def git_diff(paths: list[str] | None = None) -> str:
    args = ["diff", "--", "ai_assistant"]
    if paths:
        args = ["diff", "--", *paths]
    return _run_git(args, timeout=60)

