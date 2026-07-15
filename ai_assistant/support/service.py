from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..config import Settings
from ..llm_client import LLMClient
from ..rag import Rag
from .assistant import answer_support_question


class SupportHandler(BaseHTTPRequestHandler):
    server_version = "LocalStackSupport/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        self._write_json(HTTPStatus.OK, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/support/answer":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("request body is empty")
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            ticket_id = str(payload.get("ticket_id", "")).strip()
            question = str(payload.get("question", "")).strip()
            if not ticket_id:
                raise ValueError("ticket_id is required")
            if not question:
                raise ValueError("question is required")

            result = answer_support_question(ticket_id=ticket_id, question=question, reindex=False)
            self._write_json(HTTPStatus.OK, result)
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "not found" in message.lower():
                self._write_json(HTTPStatus.NOT_FOUND, {"error": message})
                return
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": message})

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ai_assistant.support.service")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8787, help="bind port")
    parser.add_argument("--reindex", action="store_true", help="rebuild the docs index before start")
    return parser.parse_args()


def _maybe_reindex(force: bool) -> None:
    if not force:
        return
    settings = Settings.load()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    rag = Rag(settings, LLMClient(settings))
    try:
        stats = rag.reindex(force=False)
        print(f"[support-service] reindex: {stats}")
    finally:
        rag.store.close()


def main() -> None:
    args = _parse_args()
    _maybe_reindex(force=args.reindex)
    server = ThreadingHTTPServer((args.host, args.port), SupportHandler)
    print(f"[support-service] listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

