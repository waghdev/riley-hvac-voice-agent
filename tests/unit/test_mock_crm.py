"""The mock CRM's contract, and crm_client against it end to end, in process (no sockets)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.crm_client import DELIVERED, CrmClient, Outbox
from mock_crm.app import Control, create_app

LEAD = {"kind": "booking", "call_id": "c1", "first_name": "Jordan", "callback_number": "6025550142"}


@pytest.fixture
def crm(tmp_path) -> TestClient:
    return TestClient(create_app(tmp_path / "crm.sqlite3"))


def post(crm: TestClient, key: str | None = "k1", body=LEAD) -> httpx.Response:
    return crm.post("/leads", json=body, headers={"Idempotency-Key": key} if key else {})


def test_a_lead_is_stored_once_per_idempotency_key(crm):
    first, again = post(crm), post(crm)
    assert (first.status_code, first.json()["status"]) == (201, "created")
    assert (again.status_code, again.json()["status"]) == (200, "duplicate")
    assert again.json()["lead_id"] == first.json()["lead_id"]
    assert len(crm.get("/leads").json()) == 1


def test_the_idempotency_key_is_required(crm):
    assert post(crm, key=None).status_code == 400


def test_a_lead_without_a_callback_number_is_refused(crm):
    assert post(crm, body={**LEAD, "callback_number": None}).status_code == 422


def test_the_failure_switch_fails_the_next_requests_then_recovers(crm):
    crm.post("/control", json={"fail_next": 2, "status": 503})
    assert [post(crm).status_code for _ in range(3)] == [503, 503, 201]


async def test_crm_client_rides_out_failures_and_stores_one_lead(tmp_path):
    # The demo in one test: the CRM fails twice, the client retries with the same key, and
    # the CRM ends up with exactly one copy of the lead.
    app = create_app(tmp_path / "crm.sqlite3", Control(fail_next=2))

    async def no_wait(_: float) -> None:
        return None

    client = CrmClient(
        "http://crm.test",
        Outbox(tmp_path / "outbox.sqlite3"),
        transport=httpx.ASGITransport(app=app),
        sleep=no_wait,
    )
    assert await client.deliver("k1", LEAD) == DELIVERED
    assert await client.deliver("k1", LEAD) == DELIVERED  # a redelivery: still one lead
    assert len(TestClient(app).get("/leads").json()) == 1
