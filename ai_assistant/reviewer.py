from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Settings
from .llm_client import LLMClient
from .rag import MIN_SCORE, Hit, Rag

MARKER = "<!-- localstack-ai-review -->"
MAX_DIFF_CHARS = 40000
RAG_TOP_K = 8
REVIEWABLE_SUFFIXES = {
    ".c",
    ".cfg",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

SYSTEM_REVIEW = (
    "You are a strict senior code reviewer for the LocalStack repository. "
    "Review only what changed in the PR diff and changed files list. "
    "Use documentation context when relevant. "
    "Prioritize concrete bugs, regressions, security and reliability risks, and architectural "
    "issues. Do not nitpick formatting. If no major issues exist, say so clearly and include "
    "residual risks. "
    "Return markdown with sections in this exact order:\n"
    "## AI Review\n"
    "### Potential Bugs\n"
    "### Architectural Concerns\n"
    "### Recommendations\n"
    "### Sources\n"
)


@dataclass(frozen=True)
class PRContext:
    number: int
    repo: str
    title: str
    body: str
    base_ref: str
    head_ref: str
    changed_files: list[str]
    diff: str


def _run(cmd: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {cmd}")
    return proc.stdout


def _gh_json(args: list[str]) -> dict | list:
    out = _run(["gh", *args])
    return json.loads(out)


def _read_pr_number(event_path: Path) -> int:
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    pr = payload.get("pull_request", {})
    number = pr.get("number")
    if number is None:
        raise ValueError("pull_request.number not found in event payload")
    return int(number)


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _is_reviewable(path: str) -> bool:
    return Path(path).suffix.lower() in REVIEWABLE_SUFFIXES


def _load_pr_context(repo: str, pr_number: int, max_diff_chars: int) -> PRContext:
    view = _gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "title,body,baseRefName,headRefName,files",
        ]
    )
    if not isinstance(view, dict):
        raise RuntimeError("unexpected PR view payload")

    files_raw = view.get("files", [])
    changed_files = [f.get("path", "") for f in files_raw if isinstance(f, dict) and f.get("path")]
    diff_full = _run(["gh", "pr", "diff", str(pr_number), "--repo", repo], timeout=120)
    diff, truncated = _truncate(diff_full, max_diff_chars)
    if truncated:
        diff += f"\n\n[diff truncated to {max_diff_chars} characters]"

    return PRContext(
        number=pr_number,
        repo=repo,
        title=str(view.get("title", "")),
        body=str(view.get("body", "")),
        base_ref=str(view.get("baseRefName", "")),
        head_ref=str(view.get("headRefName", "")),
        changed_files=changed_files,
        diff=diff,
    )


def _build_retrieval_query(ctx: PRContext) -> str:
    file_block = "\n".join(ctx.changed_files[:80])
    diff_slice, _ = _truncate(ctx.diff, 6000)
    return (
        f"PR title: {ctx.title}\n"
        f"Base: {ctx.base_ref}\nHead: {ctx.head_ref}\n"
        f"Changed files:\n{file_block}\n\n"
        f"Diff excerpt:\n{diff_slice}"
    )


def _render_doc_context(hits: list[Hit]) -> str:
    useful = [h for h in hits if h.score >= MIN_SCORE]
    if not useful:
        return "No relevant documentation retrieved."
    blocks = []
    for hit in useful:
        blocks.append(f"[{hit.path}] (score={hit.score:.3f})\n{hit.text}")
    return "\n\n".join(blocks)


def _review_prompt(ctx: PRContext, rag_hits: list[Hit]) -> str:
    changed_summary = "\n".join(f"- {p}" for p in ctx.changed_files[:300]) or "- (none)"
    reviewable_files = [p for p in ctx.changed_files if _is_reviewable(p)]
    reviewable_summary = "\n".join(f"- {p}" for p in reviewable_files[:300]) or "- (none)"
    return (
        f"Repository: {ctx.repo}\n"
        f"PR #{ctx.number}: {ctx.title}\n"
        f"Base: {ctx.base_ref}\nHead: {ctx.head_ref}\n\n"
        f"PR body:\n{ctx.body or '(empty)'}\n\n"
        f"Changed files (all):\n{changed_summary}\n\n"
        f"Reviewable files (by extension):\n{reviewable_summary}\n\n"
        f"Documentation context from RAG:\n{_render_doc_context(rag_hits)}\n\n"
        f"PR diff:\n{ctx.diff}\n\n"
        "Requirements:\n"
        "- Focus on real issues and impact.\n"
        "- Mention specific files/lines/snippets from the diff when possible.\n"
        "- Keep it concise but concrete.\n"
        "- For Sources section, cite docs paths used from context as [path].\n"
    )


def _is_model_unavailable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    tokens = ("model_not_found", "does not exist", "unavailable", "access", "not have access")
    return any(t in text for t in tokens)


def _generate_review(settings: Settings, prompt: str) -> str:
    llm = LLMClient(settings)
    try:
        return llm.chat(SYSTEM_REVIEW, prompt)
    except Exception as exc:  # noqa: BLE001
        if settings.llm_model == "gpt-4o" or not _is_model_unavailable_error(exc):
            raise
        fallback_settings = replace(settings, llm_model="gpt-4o")
        print(
            f"[reviewer] llm model '{settings.llm_model}' unavailable; "
            "falling back to 'gpt-4o'",
            file=sys.stderr,
        )
        return LLMClient(fallback_settings).chat(SYSTEM_REVIEW, prompt)


def _find_existing_comment(repo: str, pr_number: int) -> int | None:
    comments = _gh_json(
        [
            "api",
            f"repos/{repo}/issues/{pr_number}/comments?per_page=100",
        ]
    )
    if not isinstance(comments, list):
        return None
    for comment in reversed(comments):
        if not isinstance(comment, dict):
            continue
        body = str(comment.get("body", ""))
        if MARKER in body:
            cid = comment.get("id")
            return int(cid) if isinstance(cid, int) else None
    return None


def _write_or_update_comment(repo: str, pr_number: int, body: str) -> None:
    comment_id = _find_existing_comment(repo, pr_number)
    if comment_id is None:
        tmp = Path("ai_assistant/.review_comment.md")
        tmp.write_text(body, encoding="utf-8")
        try:
            _run(["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body-file", str(tmp)])
        finally:
            if tmp.exists():
                tmp.unlink()
        return
    _run(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{repo}/issues/comments/{comment_id}",
            "-f",
            f"body={body}",
        ]
    )


def _no_review_message(ctx: PRContext) -> str:
    return (
        f"{MARKER}\n"
        "## AI Review\n\n"
        "No reviewable code changes detected in this PR (based on file extensions filter).\n\n"
        "### Potential Bugs\n- None in scope (no reviewable code diff).\n\n"
        "### Architectural Concerns\n- None in scope.\n\n"
        "### Recommendations\n"
        "- If you want docs/process review too, extend the reviewable suffix allowlist.\n\n"
        "### Sources\n- N/A\n"
    )


def _build_comment(ctx: PRContext, review: str) -> str:
    return (
        f"{MARKER}\n"
        f"<!-- pr:{ctx.number} repo:{ctx.repo} -->\n\n"
        f"{review.strip()}\n"
    )


def _ensure_index(rag: Rag) -> None:
    if rag.store.count() == 0:
        stats = rag.reindex(force=False)
        print(f"[reviewer] index initialized: {stats}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ai_assistant.reviewer")
    parser.add_argument("--pr", type=int, help="PR number")
    parser.add_argument("--repo", help="owner/repo (defaults to GITHUB_REPOSITORY)")
    parser.add_argument("--event-path", help="GitHub event JSON path (defaults to GITHUB_EVENT_PATH)")
    parser.add_argument("--reindex-only", action="store_true", help="only refresh RAG index and exit")
    parser.add_argument("--dry-run", action="store_true", help="print review markdown and skip posting")
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=MAX_DIFF_CHARS,
        help=f"truncate PR diff to this many characters (default: {MAX_DIFF_CHARS})",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = Settings.load()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    rag = Rag(settings, LLMClient(settings))
    try:
        if args.reindex_only:
            stats = rag.reindex(force=False)
            print(f"[reviewer] reindex-only: {stats}")
            return

        repo = args.repo or os.getenv("GITHUB_REPOSITORY", "").strip()
        if not repo:
            raise RuntimeError("--repo is required (or set GITHUB_REPOSITORY)")

        pr_number = args.pr
        if pr_number is None:
            event_path_value = args.event_path or os.getenv("GITHUB_EVENT_PATH", "")
            if not event_path_value:
                raise RuntimeError("--pr is required outside GitHub Actions")
            pr_number = _read_pr_number(Path(event_path_value))

        _ensure_index(rag)
        ctx = _load_pr_context(repo=repo, pr_number=pr_number, max_diff_chars=args.max_diff_chars)

        reviewable_files = [p for p in ctx.changed_files if _is_reviewable(p)]
        if not reviewable_files or not ctx.diff.strip():
            body = _no_review_message(ctx)
            if args.dry_run:
                print(body)
                return
            _write_or_update_comment(repo=ctx.repo, pr_number=ctx.number, body=body)
            print("[reviewer] posted no-reviewable-changes note")
            return

        rag_query = _build_retrieval_query(ctx)
        rag_hits = rag.retrieve(rag_query, k=RAG_TOP_K)
        prompt = _review_prompt(ctx, rag_hits)
        review = _generate_review(settings, prompt)
        body = _build_comment(ctx, review)

        if args.dry_run:
            print(body)
            return

        _write_or_update_comment(repo=ctx.repo, pr_number=ctx.number, body=body)
        print(f"[reviewer] review comment posted for PR #{ctx.number}")
    finally:
        rag.store.close()


if __name__ == "__main__":
    main()
