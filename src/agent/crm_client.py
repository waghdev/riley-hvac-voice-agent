"""Delivers leads to the CRM so that none is lost and none arrives twice (CLAUDE.md section 7).

1. Outbox first: the lead goes into a local SQLite outbox (pending) before any network call, so
   a crash or a hang-up at any moment leaves it there to send again.
2. POST {MOCK_CRM_URL}/leads with an Idempotency-Key header (from the call id and the window).
   A retry, or a redelivery of a lead that did get through, can't create a duplicate: the CRM
   answers a key it has seen with the first result.
3. Server errors (5xx), 408, 429 and network errors or timeouts are retried with exponential
   backoff and full jitter, up to a fixed number of attempts. Any other 4xx means the request
   itself is wrong, so the lead is marked rejected instead of retried.
4. Delivered: marked delivered. Still failing: left pending with the last error, for
   scripts/redeliver_outbox.py.

No LiveKit. tools.py hands leads to LeadSender, which delivers them in the background, so the
caller never waits on the CRM.
"""

import asyncio
import hashlib
import json
import logging
import random
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from agent.calendar import Window, booking_key
from agent.state import CallState

# Lead keys are logged (they're hashes); what the caller said is not.
logger = logging.getLogger("riley.crm")

PENDING, DELIVERED, REJECTED = "pending", "delivered", "rejected"


def callback_key(call_id: str) -> str:
    """Idempotency key for a callback request: one per call."""
    return hashlib.sha256(f"{call_id}:callback".encode()).hexdigest()[:32]


def build_lead(state: CallState, window: Window | None) -> tuple[str, dict[str, Any]]:
    """The idempotency key and CRM payload for a booked call (with its window) or a callback
    request (no window). A booking's key is the calendar's, so both dedupe the same way."""
    if window is not None:
        key, kind = booking_key(state.call_id, window.id), "booking"
    else:
        key, kind = callback_key(state.call_id), "callback"
    return key, {
        "kind": kind,
        "call_id": state.call_id,
        "first_name": state.first_name,
        "callback_number": state.callback_number,
        "zip_code": state.zip_code,
        "category": state.category,
        "symptoms": state.symptoms,
        "priority": state.priority,
        "vulnerable_occupant": state.vulnerable_occupant,
        "callback_reason": state.callback_reason,
        "booking_id": state.booking_id,
        "window_start": window.start.isoformat() if window else None,
        "window_end": window.end.isoformat() if window else None,
    }


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4  # in total, including the first
    base_delay: float = 0.5  # seconds before the first retry, at most; doubles each retry
    max_delay: float = 4.0
    timeout: float = 3.0  # per attempt

    def delay(self, retry: int, rand: Callable[[], float] = random.random) -> float:
        """Full jitter: a random wait between 0 and min(max_delay, base_delay * 2^(retry-1)).
        The randomness spreads out retries from many calls, so a recovering CRM isn't hit by
        all of them at the same moment."""
        return rand() * min(self.max_delay, self.base_delay * 2 ** (retry - 1))


DEFAULT_POLICY = RetryPolicy()


def _retryable(status: int) -> bool:
    return status >= 500 or status in (408, 429)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Outbox:
    """Every lead and its delivery status, in SQLite. A connection per call, like calendar.py,
    so it's safe from worker threads and from several processes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS outbox (
                    idempotency_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,  -- JSON; fake test callers only
                    status TEXT NOT NULL,  -- pending, delivered or rejected
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)  # autocommit
        try:
            yield db
        finally:
            db.close()

    def add(self, key: str, payload: dict[str, Any]) -> None:
        """Store a lead as pending. Adding a key that's already there changes nothing."""
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO outbox (idempotency_key, payload, status, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?)",
                (key, json.dumps(payload), PENDING, now, now),
            )

    def record(self, key: str, status: str, attempts: int, error: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE outbox SET status = ?, attempts = attempts + ?, last_error = ?,"
                " updated_at = ? WHERE idempotency_key = ?",
                (status, attempts, error, _now(), key),
            )

    def pending(self) -> list[tuple[str, dict[str, Any]]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT idempotency_key, payload FROM outbox WHERE status = ? ORDER BY created_at",
                (PENDING,),
            ).fetchall()
        return [(key, json.loads(payload)) for key, payload in rows]

    def status(self, key: str) -> tuple[str, int, str | None] | None:
        """(status, attempts so far, last error) for a lead, or None if it isn't here."""
        with self._connect() as db:
            return db.execute(
                "SELECT status, attempts, last_error FROM outbox WHERE idempotency_key = ?", (key,)
            ).fetchone()


class CrmClient:
    """Sends leads from the outbox to the CRM. base_url None: no CRM configured (the deployed
    demo), so leads stay pending in the outbox.

    transport, sleep and rand are for tests: a fake CRM, and no real waiting or randomness.
    """

    def __init__(
        self,
        base_url: str | None,
        outbox: Outbox,
        policy: RetryPolicy = DEFAULT_POLICY,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.outbox = outbox
        self._base_url = base_url
        self._policy = policy
        self._transport = transport
        self._sleep = sleep
        self._rand = rand

    async def enqueue(self, key: str, payload: dict[str, Any]) -> None:
        """Step 1: into the outbox. SQLite blocks, so it runs off the event loop."""
        await asyncio.to_thread(self.outbox.add, key, payload)

    async def deliver(self, key: str, payload: dict[str, Any]) -> str:
        """Steps 1 to 4. Returns the lead's status afterwards."""
        await self.enqueue(key, payload)
        return await self.send(key, payload)

    async def send(self, key: str, payload: dict[str, Any]) -> str:
        """Steps 2 to 4, for a lead already in the outbox."""
        if not self._base_url:
            await self._record(key, PENDING, 0, "no CRM configured (MOCK_CRM_URL unset)")
            logger.info("lead queued: no CRM configured", extra={"lead": key})
            return PENDING
        error = ""
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._policy.timeout, transport=self._transport
        ) as http:
            for attempt in range(1, self._policy.attempts + 1):
                if attempt > 1:
                    await self._sleep(self._policy.delay(attempt - 1, self._rand))
                try:
                    response = await http.post(
                        "/leads", json=payload, headers={"Idempotency-Key": key}
                    )
                except httpx.TransportError as e:  # refused, reset, timed out
                    error = type(e).__name__
                else:
                    if response.is_success:
                        await self._record(key, DELIVERED, attempt)
                        logger.info("lead delivered", extra={"lead": key, "attempts": attempt})
                        return DELIVERED
                    error = f"HTTP {response.status_code}"
                    if not _retryable(response.status_code):
                        await self._record(key, REJECTED, attempt, error)
                        logger.warning("lead rejected", extra={"lead": key, "error": error})
                        return REJECTED
                logger.info(
                    "lead attempt failed", extra={"lead": key, "attempt": attempt, "error": error}
                )
        await self._record(key, PENDING, self._policy.attempts, error)
        logger.warning("lead left in the outbox", extra={"lead": key, "error": error})
        return PENDING

    async def redeliver_pending(self) -> dict[str, str]:
        """Send every pending lead again. Returns each lead's status afterwards."""
        leads = await asyncio.to_thread(self.outbox.pending)
        return {key: await self.send(key, payload) for key, payload in leads}

    async def _record(self, key: str, status: str, attempts: int, error: str | None = None) -> None:
        await asyncio.to_thread(self.outbox.record, key, status, attempts, error)


class LeadSender:
    """Delivers leads in the background, so the caller never waits on the CRM, and gives them a
    bounded time to finish when the call ends. A lead cut off there is still pending in the
    outbox, because it was stored before the first attempt."""

    def __init__(self, client: CrmClient) -> None:
        self.client = client
        self._tasks: set[asyncio.Task[None]] = set()

    async def send(self, key: str, payload: dict[str, Any]) -> None:
        """Store the lead (done when this returns), then deliver it in the background."""
        await self.client.enqueue(key, payload)
        task = asyncio.create_task(self._deliver(key, payload))
        self._tasks.add(task)  # a reference, so the task isn't garbage-collected mid-flight
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, key: str, payload: dict[str, Any]) -> None:
        try:
            await self.client.send(key, payload)
        except Exception:  # a bug, not a CRM failure; the lead is still pending in the outbox
            logger.exception("lead delivery crashed", extra={"lead": key})

    async def drain(self, timeout: float) -> None:
        """Wait up to `timeout` seconds for deliveries in flight, then stop them."""
        if not self._tasks:
            return
        _, unfinished = await asyncio.wait(set(self._tasks), timeout=timeout)
        for task in unfinished:
            task.cancel()
        if unfinished:
            logger.warning("leads still sending at hang-up", extra={"count": len(unfinished)})
