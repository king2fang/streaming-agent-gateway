"""S2: store + api integration."""
import asyncio
from collections import deque
import httpx
import pytest
from httpx import ASGITransport
from app.main import app
from app.api.runs import registry
from app.store import RunBuffer


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_terminal(client, run_id, timeout=5.0):
    start = asyncio.get_event_loop().time()
    while True:
        r = await client.get(f"/v1/runs/{run_id}")
        if r.json()["status"] in ("completed", "failed", "cancelled"):
            return r.json()["status"]
        if asyncio.get_event_loop().time() - start > timeout:
            raise AssertionError(f"timeout for {run_id}")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_create_run():
    async with _client() as c:
        r = await c.post("/v1/runs",
                         json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200
        b = r.json()
        assert "run_id" in b and b["status"] == "pending"
        await _wait_terminal(c, b["run_id"])


@pytest.mark.asyncio
async def test_404():
    async with _client() as c:
        assert (await c.get("/v1/runs/run-x")).status_code == 404
        assert (await c.get("/v1/runs/run-x/stream")).status_code == 404
        assert (await c.post("/v1/runs/run-x/cancel")).status_code == 404


@pytest.mark.asyncio
async def test_full_stream():
    async with _client() as c:
        r = await c.post("/v1/runs",
                         json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]})
        rid = r.json()["run_id"]
        await _wait_terminal(c, rid)
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = (await resp.aread()).decode()
        assert "event: run.started" in body
        assert "event: message.delta" in body
        assert "event: message.completed" in body
        assert "chat.completion.chunk" in body
        assert "data: [DONE]" in body
        assert body.count("data: [DONE]") == 1


@pytest.mark.asyncio
async def test_resume_last_event_id():
    buf = RunBuffer("run-resume", "mock", 0)
    registry.runs["run-resume"] = buf
    for i in range(3):
        await buf.append("message.delta", {"content": f"t{i}"})
    await buf.append("run.completed", {"finish_reason": "stop"})
    async with _client() as c:
        async with c.stream("GET", "/v1/runs/run-resume/stream",
                            headers={"Last-Event-ID": "2"}) as resp:
            body = (await resp.aread()).decode()
    assert "id: 3" in body
    assert "id: 4" in body
    assert "id: 1" not in body
    assert "id: 2" not in body


@pytest.mark.asyncio
async def test_gap_signal():
    buf = RunBuffer("run-gap", "mock", 0)
    buf.events = deque(maxlen=2)
    registry.runs["run-gap"] = buf
    for i in range(5):
        await buf.append("message.delta", {"content": f"t{i}"})
    await buf.append("run.completed", {"finish_reason": "stop"})
    async with _client() as c:
        async with c.stream("GET", "/v1/runs/run-gap/stream",
                            headers={"Last-Event-ID": "0"}) as resp:
            body = (await resp.aread()).decode()
    assert "event: gap" in body


@pytest.mark.asyncio
async def test_cancel():
    async with _client() as c:
        r = await c.post("/v1/runs",
                         json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]})
        rid = r.json()["run_id"]
        await asyncio.sleep(0.15)
        cresp = await c.post(f"/v1/runs/{rid}/cancel")
        assert cresp.status_code == 200
        status = await _wait_terminal(c, rid, timeout=3.0)
        assert status == "cancelled"


@pytest.mark.asyncio
async def test_list():
    async with _client() as c:
        r1 = await c.post("/v1/runs",
                          json={"model": "mock", "messages": [{"role": "user", "content": "a"}]})
        r2 = await c.post("/v1/runs",
                          json={"model": "mock", "messages": [{"role": "user", "content": "b"}]})
        await _wait_terminal(c, r1.json()["run_id"])
        await _wait_terminal(c, r2.json()["run_id"])
        r = await c.get("/v1/runs")
        assert r.status_code == 200
        assert len(r.json()["runs"]) >= 2


@pytest.mark.asyncio
async def test_multi_subscriber():
    buf = RunBuffer("run-multi", "mock", 0)
    registry.runs["run-multi"] = buf
    for i in range(3):
        await buf.append("message.delta", {"content": f"t{i}"})
    await buf.append("run.completed", {"finish_reason": "stop"})

    async def consume():
        async with _client() as c:
            async with c.stream("GET", "/v1/runs/run-multi/stream") as resp:
                return (await resp.aread()).decode()

    b1 = await consume()
    b2 = await consume()
    assert b1 == b2
    assert "data: [DONE]" in b1
