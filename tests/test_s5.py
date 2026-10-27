"""S5: Cancellation tests."""
import asyncio
import httpx
import pytest
from httpx import ASGITransport
from app.main import app


async def _wait_status(client, run_id, expected, timeout=3.0):
    start = asyncio.get_event_loop().time()
    while True:
        r = await client.get(f"/v1/runs/{run_id}")
        if r.json()["status"] == expected:
            return
        if asyncio.get_event_loop().time() - start > timeout:
            raise AssertionError(f"timeout waiting for {expected}, got {r.json()['status']}")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cancel_loop():
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # mock model 默认 delay 0.05，跑 8 个词需要 0.4s
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"script": "chat"}
        })
        rid = r.json()["run_id"]
        
        # 等待它进入 running
        await _wait_status(c, rid, "running")
        
        # 立即取消
        await c.post(f"/v1/runs/{rid}/cancel")
        
        # 等待它变为 cancelled
        await _wait_status(c, rid, "cancelled")