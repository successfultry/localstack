from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("localstack-support-crm")

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_PATH = DATA_DIR / "users.json"
TICKETS_PATH = DATA_DIR / "tickets.json"


def _read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"invalid JSON payload in {path}")
    out: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            out.append(item)
    return out


@mcp.tool()
def get_ticket(ticket_id: str) -> dict[str, Any]:
    """Return one support ticket by ID."""
    ticket_id = ticket_id.strip()
    if not ticket_id:
        raise ValueError("ticket_id is required")
    for ticket in _read_json(TICKETS_PATH):
        if str(ticket.get("ticket_id", "")).strip() == ticket_id:
            return ticket
    raise ValueError(f"ticket not found: {ticket_id}")


@mcp.tool()
def get_user(user_id: str) -> dict[str, Any]:
    """Return one CRM user by ID."""
    user_id = user_id.strip()
    if not user_id:
        raise ValueError("user_id is required")
    for user in _read_json(USERS_PATH):
        if str(user.get("user_id", "")).strip() == user_id:
            return user
    raise ValueError(f"user not found: {user_id}")


@mcp.tool()
def list_user_tickets(user_id: str) -> list[dict[str, Any]]:
    """List all tickets for a user ID."""
    user_id = user_id.strip()
    if not user_id:
        raise ValueError("user_id is required")
    tickets = [t for t in _read_json(TICKETS_PATH) if str(t.get("user_id", "")).strip() == user_id]
    tickets.sort(key=lambda t: str(t.get("ticket_id", "")))
    return tickets


if __name__ == "__main__":
    mcp.run()

