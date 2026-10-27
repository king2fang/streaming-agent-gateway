"""S8: Harness fault injection tests."""
import asyncio
import httpx
import pytest
from httpx import ASGITransport
from app.main import app

def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

async def _wait_terminal(client, run_id, timeout=3.0):
    start = asyncio.get_event_loop().time()
    while True:
        r = await client.get(f"/v1/runs/{run_id}")
        status = r.json()["status"]
        if status in ("completed", "failed", "cancelled"):
            return status
        if asyncio.get_event_loop().time() - start > timeout:
            raise AssertionError(f"timeout for {run_id}, status: {status}")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_fault_error():
    """Test API error injection."""
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"fault": "error"}
        })
        rid = r.json()["run_id"]
        status = await _wait_terminal(c, rid)
        assert status == "failed"
        
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "event: error" in body
        assert "mock_api_error" in body


@pytest.mark.asyncio
async def test_fault_drop():
    """Test unexpected stream end."""
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"fault": "drop"}
        })
        rid = r.json()["run_id"]
        status = await _wait_terminal(c, rid)
        assert status == "failed"
        
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "stream_interrupted" in body
