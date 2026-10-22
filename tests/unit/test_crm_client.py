"""CRM delivery: outbox first, retries with backoff, idempotency, and background sending.

No network: httpx.MockTransport plays the CRM, sleeps are recorded instead of waited, and the
jitter is pinned to its maximum so the delays are exact.
"""

import asyncio

import httpx
import pytest

from agent.calendar import Window
from agent.crm_client import (
    DELIVERED,
    PENDING,
    REJECTED,
    CrmClient,
    LeadSender,
    Outbox,
    RetryPolicy,
    build_lead,
    callback_key,
)
from agent.state import CallState

KEY = "lead-key-1"
LEAD = {"kind": "booking", "call_id": "c1", "first_name": "Jordan", "callback_number": "6025550142"}


class FakeCrm:
    """Answers requests in turn from a script: a status code, or an httpx exception class. The
    last entry repeats."""

    def __init__(self, *script) -> None:
        self.script = script
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script[min(len(self.requests), len(self.script)) - 1]
        if isinstance(step, type) and issubclass(step, Exception):
            raise step("simulated", request=request)
        return httpx.Response(step, json={})


@pytest.fixture
def outbox(tmp_path) -> Outbox:
    return Outbox(tmp_path / "outbox.sqlite3")


def client(outbox: Outbox, crm: FakeCrm | None, delays: list[float] | None = None) -> CrmClient:
    async def sleep(seconds: float) -> None:
        if delays is not None:
            delays.append(seconds)

    return CrmClient(
        "http://crm.test" if crm else None,
        outbox,
        transport=httpx.MockTransport(crm) if crm else None,
        sleep=sleep,
        rand=lambda: 1.0,  # full jitter at its maximum: the delay caps themselves
    )


async def test_a_lead_is_delivered_with_its_idempotency_key(outbox):
    crm = FakeCrm(201)
    assert await client(outbox, crm).deliver(KEY, LEAD) == DELIVERED
    (request,) = crm.requests
    assert request.url.path == "/leads"
    assert request.headers["Idempotency-Key"] == KEY
    assert request.read() == httpx.Request("POST", "/", json=LEAD).read()
    assert outbox.status(KEY) == (DELIVERED, 1, None)


async def test_server_errors_are_retried_with_backoff_until_delivered(outbox):
    crm, delays = FakeCrm(500, 503, 201), []
    assert await client(outbox, crm, delays).deliver(KEY, LEAD) == DELIVERED
    assert delays == [0.5, 1.0]  # exponential: 0.5 s, then 1 s
    assert {r.headers["Idempotency-Key"] for r in crm.requests} == {KEY}  # the same key each time
    assert outbox.status(KEY)[:2] == (DELIVERED, 3)


async def test_attempts_are_bounded_and_the_lead_stays_in_the_outbox(outbox):
    crm, delays = FakeCrm(500), []
    assert await client(outbox, crm, delays).deliver(KEY, LEAD) == PENDING
    assert len(crm.requests) == 4
    assert delays == [0.5, 1.0, 2.0]
    assert outbox.status(KEY) == (PENDING, 4, "HTTP 500")
    assert [key for key, _ in outbox.pending()] == [KEY]


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout])
async def test_network_errors_and_timeouts_are_retried(outbox, error):
    crm = FakeCrm(error, 201)
    assert await client(outbox, crm).deliver(KEY, LEAD) == DELIVERED
    assert len(crm.requests) == 2


@pytest.mark.parametrize("status", [408, 429])
async def test_busy_and_timeout_statuses_are_retried(outbox, status):
    crm = FakeCrm(status, 201)
    assert await client(outbox, crm).deliver(KEY, LEAD) == DELIVERED


@pytest.mark.parametrize("status", [400, 401, 422])
async def test_a_request_the_crm_refuses_is_not_retried(outbox, status):
    crm = FakeCrm(status)
    assert await client(outbox, crm).deliver(KEY, LEAD) == REJECTED
    assert len(crm.requests) == 1
    assert outbox.status(KEY) == (REJECTED, 1, f"HTTP {status}")
    assert outbox.pending() == []


async def test_without_a_crm_url_the_lead_waits_in_the_outbox(outbox):
    # The deployed demo: no CRM it can reach, so nothing is lost, just queued.
    assert await client(outbox, None).deliver(KEY, LEAD) == PENDING
    assert outbox.status(KEY)[0] == PENDING


async def test_pending_leads_are_redelivered_once_the_crm_is_back(outbox):
    await client(outbox, FakeCrm(503)).deliver(KEY, LEAD)
    crm = FakeCrm(201)
    assert await client(outbox, crm).redeliver_pending() == {KEY: DELIVERED}
    assert outbox.pending() == []
    assert outbox.status(KEY)[:2] == (DELIVERED, 5)  # 4 failed attempts, then 1 good one


async def test_the_same_lead_twice_is_one_outbox_row(outbox):
    outbox.add(KEY, LEAD)
    outbox.add(KEY, {**LEAD, "first_name": "Changed"})
    assert outbox.pending() == [(KEY, LEAD)]


def test_full_jitter_stays_within_the_capped_exponential():
    policy = RetryPolicy()
    assert [policy.delay(n, rand=lambda: 1.0) for n in (1, 2, 3, 4, 5, 10)] == [
        0.5, 1.0, 2.0, 4.0, 4.0, 4.0,
    ]  # fmt: skip
    assert policy.delay(3, rand=lambda: 0.0) == 0.0
    assert 0.0 <= policy.delay(3) <= 2.0


# --- Background sending -----------------------------------------------------------------------


async def test_the_caller_does_not_wait_for_delivery(outbox):
    release = asyncio.Event()

    async def slow_crm(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(201)

    sender = LeadSender(
        CrmClient("http://crm.test", outbox, transport=httpx.MockTransport(slow_crm))
    )
    await sender.send(KEY, LEAD)  # returns while the CRM is still "thinking"
    assert outbox.status(KEY)[0] == PENDING  # but the lead is already safe in the outbox
    release.set()
    await sender.drain(timeout=5)
    assert outbox.status(KEY)[0] == DELIVERED


async def test_hanging_up_stops_waiting_but_keeps_the_lead(outbox):
    async def stuck_crm(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(60)
        return httpx.Response(201)

    sender = LeadSender(
        CrmClient("http://crm.test", outbox, transport=httpx.MockTransport(stuck_crm))
    )
    await sender.send(KEY, LEAD)
    await sender.drain(timeout=0.05)
    assert outbox.status(KEY)[0] == PENDING  # redeliverable later


# --- What goes to the CRM ---------------------------------------------------------------------


def test_a_booking_lead_carries_the_window_and_the_calendars_key():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from agent.calendar import booking_key

    phx = ZoneInfo("America/Phoenix")
    window = Window(datetime(2026, 10, 22, 8, tzinfo=phx), datetime(2026, 10, 22, 10, tzinfo=phx))
    state = CallState(call_id="c1", first_name="Jordan", callback_number="6025550142")
    state.booking_id = "KC-1"
    key, lead = build_lead(state, window)
    assert key == booking_key("c1", window.id)
    assert (lead["kind"], lead["booking_id"]) == ("booking", "KC-1")
    assert lead["window_start"] == "2026-10-22T08:00:00-07:00"


def test_a_callback_lead_has_one_key_per_call():
    state = CallState(call_id="c1", first_name="Jordan", callback_number="6025550142")
    state.callback_reason = "billing"
    key, lead = build_lead(state, None)
    assert key == callback_key("c1")
    assert (lead["kind"], lead["callback_reason"], lead["window_start"]) == (
        "callback", "billing", None,
    )  # fmt: skip
