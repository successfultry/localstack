from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from typing import Any

from ..config import Settings
from ..llm_client import LLMClient
from ..rag import MIN_SCORE, Hit, Rag
from .crm_tools import get_ticket, get_user

RAG_TOP_K = 8
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def _is_model_unavailable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    tokens = ("model_not_found", "does not exist", "unavailable", "access", "not have access")
    return any(t in text for t in tokens)


def _chat_with_fallback(settings: Settings, system: str, user: str) -> str:
    llm = LLMClient(settings)
    try:
        return llm.chat(system, user)
    except Exception as exc:  # noqa: BLE001
        if settings.llm_model == "gpt-4o" or not _is_model_unavailable_error(exc):
            raise
        fallback_settings = replace(settings, llm_model="gpt-4o")
        print(
            f"[support] llm model '{settings.llm_model}' unavailable; falling back to 'gpt-4o'",
            file=sys.stderr,
        )
        return LLMClient(fallback_settings).chat(system, user)


def _pick_language(question: str, preferred_language: str) -> str:
    pref = preferred_language.strip().lower()
    if pref in {"ru", "russian"}:
        return "ru"
    if pref in {"en", "english"}:
        return "en"
    if CYRILLIC_RE.search(question):
        return "ru"
    return "en"


def _build_rag_query(question: str, ticket: dict[str, Any], user: dict[str, Any]) -> str:
    return (
        f"Question: {question}\n"
        f"Ticket subject: {ticket.get('subject', '')}\n"
        f"Ticket error: {ticket.get('error', '')}\n"
        f"Ticket product area: {ticket.get('product_area', '')}\n"
        f"User os/docker: {user.get('os_docker', '')}\n"
        f"User localstack version: {user.get('localstack_version', '')}\n"
        f"Last user message: {ticket.get('last_user_message', '')}"
    )


def _format_doc_context(hits: list[Hit]) -> str:
    if not hits:
        return "No product documentation context available."
    return "\n\n".join(f"[{h.path}] (score={h.score:.3f})\n{h.text}" for h in hits)


def _render_sources(hits: list[Hit]) -> list[str]:
    out: list[str] = []
    for hit in hits:
        if hit.path not in out:
            out.append(hit.path)
    return out


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = raw[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _as_str_list(value: Any, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _clamp_confidence(value: Any, default: float) -> float:
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = default
    return max(0.0, min(1.0, val))


def _normalize_structured_answer(
    raw_answer: str, lang: str, default_confidence: float, default_escalate: bool
) -> dict[str, Any]:
    payload = _extract_json_object(raw_answer) or {}
    diagnosis = str(payload.get("diagnosis", "")).strip()
    if not diagnosis:
        diagnosis = raw_answer.strip()[:600] or (
            "Не удалось получить структурированный ответ." if lang == "ru" else "Failed to get structured answer."
        )
    likely_causes = _as_str_list(payload.get("likely_causes"), max_items=5)
    steps = _as_str_list(payload.get("steps"), max_items=6)
    need_from_user = _as_str_list(payload.get("need_from_user"), max_items=5)
    confidence = _clamp_confidence(payload.get("confidence"), default=default_confidence)
    escalate = payload.get("escalate", default_escalate)
    return {
        "language": "ru" if lang == "ru" else "en",
        "diagnosis": diagnosis,
        "likely_causes": likely_causes,
        "steps": steps,
        "need_from_user": need_from_user,
        "confidence": confidence,
        "escalate": bool(escalate),
    }


def answer_support_question(ticket_id: str, question: str, reindex: bool = False) -> dict[str, Any]:
    settings = Settings.load()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    ticket = get_ticket(ticket_id)
    user_id = str(ticket.get("user_id", "")).strip()
    if not user_id:
        raise ValueError(f"ticket has no user_id: {ticket_id}")
    user = get_user(user_id)

    llm = LLMClient(settings)
    rag = Rag(settings, llm)
    try:
        if reindex:
            rag.reindex(force=False)
        elif rag.store.count() == 0:
            rag.reindex(force=False)

        rag_query = _build_rag_query(question, ticket, user)
        hits = rag.retrieve(rag_query, k=RAG_TOP_K)
        useful_hits = [h for h in hits if h.score >= MIN_SCORE]
        lang = _pick_language(question, str(user.get("preferred_language", "")))

        lang_instruction = (
            "All user-facing text values must be in Russian."
            if lang == "ru"
            else "All user-facing text values must be in English."
        )

        if useful_hits:
            docs_instruction = (
                "Use documentation context when making product claims. "
                "Do not include citations in text fields; sources are returned separately."
            )
        else:
            docs_instruction = (
                "No relevant product docs were retrieved above threshold. "
                "State that docs context is insufficient, avoid inventing LocalStack facts, "
                "and rely only on ticket/user context."
            )

        system = (
            "You are a LocalStack support assistant.\n"
            f"{lang_instruction}\n"
            "Return ONLY valid JSON object with keys:\n"
            "diagnosis (string), likely_causes (array of strings), steps (array of strings),\n"
            "need_from_user (array of strings), confidence (number 0..1), escalate (boolean).\n"
            "Keep diagnosis under 3 short sentences. Keep steps actionable and concise.\n"
            "Do not return markdown, code fences, or extra keys.\n"
            f"{docs_instruction}"
        )

        prompt = (
            f"Ticket:\n{json.dumps(ticket, ensure_ascii=False, indent=2)}\n\n"
            f"User:\n{json.dumps(user, ensure_ascii=False, indent=2)}\n\n"
            f"Question:\n{question}\n\n"
            f"Documentation context:\n{_format_doc_context(useful_hits)}"
        )
        answer = _chat_with_fallback(settings, system, prompt)
        default_escalate = not useful_hits
        default_confidence = 0.45 if default_escalate else 0.78
        structured = _normalize_structured_answer(
            raw_answer=answer,
            lang=lang,
            default_confidence=default_confidence,
            default_escalate=default_escalate,
        )
        user_context_used = {
            "user_id": user.get("user_id"),
            "plan": user.get("plan"),
            "os_docker": user.get("os_docker"),
            "localstack_version": user.get("localstack_version"),
            "preferred_language": user.get("preferred_language"),
        }
        return {
            "ticket_id": ticket_id,
            **structured,
            "sources": _render_sources(useful_hits),
            "user_context_used": user_context_used,
        }
    finally:
        rag.store.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ai_assistant.support.assistant")
    parser.add_argument("--ticket", required=True, help="ticket ID, e.g. TCK-1001")
    parser.add_argument("--question", required=True, help="user support question")
    parser.add_argument("--reindex", action="store_true", help="refresh index if requested")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = answer_support_question(
        ticket_id=args.ticket,
        question=args.question,
        reindex=args.reindex,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

