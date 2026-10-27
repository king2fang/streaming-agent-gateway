# Streaming Agent Gateway

Single-process agent gateway, SSE downlink, OpenAI chat.completion.chunk compatible.

## Platform
- Windows 10/11 + VSCode
- Python 3.11+

## Quick start

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -e ".[dev]"
    pytest
    uvicorn app.main:app --reload

## Verify

    curl.exe http://127.0.0.1:8000/healthz

## VSCode
- F5 -> "Gateway: dev" for debug server
- F5 -> "Pytest: current file" to debug tests

## Stages
- [x] S0 skeleton
- [x] S1 events + sse + chunk
- [ ] S2 store + minimal API
- [ ] S3 model + agent loop + mock
- [ ] S4 cancel + state machine
- [ ] S5 DeepSeek / Qwen adapters
- [ ] S6 sqlite persistence
- [ ] S7 web client
- [ ] S8 CLI client
- [ ] S9 harness
