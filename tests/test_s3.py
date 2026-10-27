"""S3: Agent Loop + MockModel + Tools."""
import asyncio
import httpx
import pytest
from httpx import ASGITransport
from app.main import app


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
async def test_chat_loop():
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"script": "chat"}
        })
        rid = r.json()["run_id"]
        await _wait_terminal(c, rid)
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "event: message.delta" in body
        assert "event: message.completed" in body
        assert "event: run.completed" in body


@pytest.mark.asyncio
async def test_tool_loop():
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "calc"}],
            "metadata": {"script": "tool"}
        })
        rid = r.json()["run_id"]
        await _wait_terminal(c, rid)
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "event: reasoning.delta" in body
        assert "event: tool_call.started" in body
        assert "event: tool_call.arguments.delta" in body
        assert "event: tool_call.completed" in body
        assert "event: tool_result" in body
        # 由于 mock 脚本把 1+1 算出来 "2"，验证是否成功返回
        assert '\"content\": \"2\"' in body
