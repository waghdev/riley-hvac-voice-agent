"""Mock CRM: takes leads the way a real CRM's API would, and can be told to fail.

    uv run uvicorn mock_crm.app:from_env --factory --port 8080

POST /leads    Store a lead. Needs an Idempotency-Key header. A key seen before gets the first
               result back (200) instead of a second copy (201).
GET  /leads    The stored leads, newest first.
POST /control  {"fail_next": 3, "status": 503, "delay_seconds": 2.5}: fail the next N lead
               requests with that status, and/or delay every request, to show crm_client's
               retries and outbox. {} resets.

Env (from_env): MOCK_CRM_DB (SQLite file, default data/mock_crm.sqlite3), MOCK_CRM_FAIL_NEXT,
MOCK_CRM_DELAY_SECONDS. Fake test data only, and no auth: run it on localhost.
"""

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]


class Lead(BaseModel):
    """What the agent sends (crm_client.build_lead). Required fields are what a dispatcher needs
    to call the customer back."""

    kind: Literal["booking", "callback"]
    call_id: str
    first_name: str
    callback_number: str
    zip_code: str | None = None
    category: str | None = None
    symptoms: str | None = None
    priority: bool = False
    vulnerable_occupant: str | None = None
    callback_reason: str | None = None
    booking_id: str | None = None
    window_start: str | None = None
    window_end: str | None = None


class Control(BaseModel):
    fail_next: int = 0  # how many upcoming lead requests fail
    status: int = 500  # the status they fail with
    delay_seconds: float = 0.0  # added to every request


def create_app(db_path: Path, control: Control | None = None) -> FastAPI:
    app = FastAPI(title="Mock CRM (Kestrel Comfort demo)")
    # Endpoints are plain functions, so FastAPI runs them in a thread pool; the lock keeps the
    # failure counter right when requests overlap.
    switch = {"control": control or Control()}
    lock = threading.Lock()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect() -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)  # autocommit
        try:
            yield db
        finally:
            db.close()

    with connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL
            )"""
        )

    def misbehave() -> None:
        """Apply the failure switch: delay, then maybe fail before touching any data."""
        with lock:
            ctl = switch["control"]
            fail = ctl.fail_next > 0
            if fail:
                ctl.fail_next -= 1
        time.sleep(ctl.delay_seconds)
        if fail:
            raise HTTPException(status_code=ctl.status, detail="simulated failure")

    @app.post("/leads", status_code=201)
    def create_lead(
        lead: Lead,
        response: Response,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="Idempotency-Key header required")
        misbehave()
        with connect() as db:
            # INSERT OR IGNORE plus the UNIQUE key: two requests with one key store one lead.
            cur = db.execute(
                "INSERT OR IGNORE INTO leads (idempotency_key, payload, received_at)"
                " VALUES (?, ?, ?)",
                (idempotency_key, lead.model_dump_json(), datetime.now(UTC).isoformat()),
            )
            (lead_id,) = db.execute(
                "SELECT id FROM leads WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        if cur.rowcount == 0:
            response.status_code = 200
            return {"lead_id": f"L{lead_id:05d}", "status": "duplicate"}
        return {"lead_id": f"L{lead_id:05d}", "status": "created"}

    @app.get("/leads")
    def list_leads() -> list[dict[str, Any]]:
        with connect() as db:
            rows = db.execute(
                "SELECT id, idempotency_key, payload, received_at FROM leads ORDER BY id DESC"
            ).fetchall()
        return [
            {"lead_id": f"L{i:05d}", "idempotency_key": k, "received_at": at, **json.loads(p)}
            for i, k, p, at in rows
        ]

    @app.post("/control")
    def set_control(new: Control) -> Control:
        with lock:
            switch["control"] = new
        return new

    return app


def from_env() -> FastAPI:
    """The app uvicorn runs (--factory), configured from the environment."""
    return create_app(
        Path(os.getenv("MOCK_CRM_DB", REPO_ROOT / "data" / "mock_crm.sqlite3")),
        Control(
            fail_next=int(os.getenv("MOCK_CRM_FAIL_NEXT", "0")),
            delay_seconds=float(os.getenv("MOCK_CRM_DELAY_SECONDS", "0")),
        ),
    )
