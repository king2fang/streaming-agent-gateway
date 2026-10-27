"""S4: Adapter tests with MockTransport."""
import pytest
import httpx
from app.models.openai_compat import OpenAICompatibleAdapter

@pytest.mark.asyncio
async def test_adapter_stream_parse():
    """Simulate an OpenAI SSE stream."""
    sse_data = (
        'data: {"choices":[{"delta":{"reasoning_content":"Think"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"calc","arguments":""}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"a\\":1}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        'data: [DONE]\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_data.encode())

    # Monkeypatch httpx.AsyncClient to use MockTransport
    orig_client = httpx.AsyncClient
    httpx.AsyncClient = lambda **kwargs: orig_client(transport=httpx.MockTransport(handler), **kwargs)

    try:
        adapter = OpenAICompatibleAdapter("test", "http://api.test", "sk-123", "test-model")
        events = []
        async for evt in adapter.stream([{"role": "user", "content": "hi"}], cancel=None):
            events.append(evt)
        
        assert len(events) == 5
        assert events[0].content == "Think"
        assert events[1].content == "Hello"
        assert events[2].name == "calc"
        assert events[2].args_delta == ""
        assert events[3].args_delta == '{"a":1}'
    finally:
        httpx.AsyncClient = orig_client
