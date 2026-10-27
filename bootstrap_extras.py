"""S1 extras: .vscode/*, .gitignore, .gitattributes, .env.example, README. Run: python bootstrap_extras.py"""
import sys
from pathlib import Path

FILES = {

".gitignore": """# Python
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.venv/
venv/

# Pytest / Ruff
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/

# Runtime
data/
*.db
*.db-journal
*.db-wal
*.log

# Env
.env

# VSCode (keep only 3 configs)
.vscode/*
!.vscode/settings.json
!.vscode/launch.json
!.vscode/extensions.json

# OS
.DS_Store
Thumbs.db
""",

".gitattributes": """* text=auto eol=lf
*.bat  text eol=crlf
*.ps1  text eol=crlf
*.png  binary
*.db   binary
""",

".env.example": """HOST=127.0.0.1
PORT=8000
SQLITE_PATH=./data/gateway.db
MAX_EVENTS_PER_RUN=2000
RUN_RETENTION_SECONDS=86400
SSE_HEARTBEAT_SECONDS=15
MODEL_CONNECT_TIMEOUT=10
MODEL_FIRST_TOKEN_TIMEOUT=60
MODEL_TOTAL_TIMEOUT=600
MAX_TURNS=8
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DASHSCOPE_API_KEY=
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
HARNESS_MODE=off
GATEWAY_TOKEN=
""",

".vscode/settings.json": r'''{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "python.terminal.activateEnvironment": true,
  "python.envFile": "${workspaceFolder}/.env",
  "files.eol": "\n",
  "files.encoding": "utf8",
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true,
  "terminal.integrated.defaultProfile.windows": "PowerShell",
  "terminal.integrated.env.windows": {"PYTHONUTF8": "1"},
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {"source.organizeImports": "explicit"}
  }
}
''',

".vscode/launch.json": r'''{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Gateway: dev",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"],
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "Pytest: current file",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v"],
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env",
      "console": "integratedTerminal",
      "justMyCode": false
    }
  ]
}
''',

".vscode/extensions.json": r'''{
  "recommendations": [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "ms-python.debugpy",
    "charliermarsh.ruff"
  ]
}
''',

"README.md": """# Streaming Agent Gateway

Single-process agent gateway, SSE downlink, OpenAI chat.completion.chunk compatible.

## Platform
- Windows 10/11 + VSCode
- Python 3.11+

## Quick start

    python -m venv .venv
    .\\.venv\\Scripts\\Activate.ps1
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
""",

}


def main():
    root = Path.cwd()
    if not (root / "pyproject.toml").exists():
        if (root / "streaming-agent-gateway").exists():
            root = root / "streaming-agent-gateway"
        else:
            sys.exit(f"not a gateway project: {root} (no pyproject.toml)")

    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        print(f"  + {rel:28s} {content.count(chr(10)):3d} lines")

    # .env: copy from .env.example only if not exist
    env = root / ".env"
    if not env.exists():
        env.write_text(FILES[".env.example"], encoding="utf-8", newline="\n")
        print("  + .env (copied from .env.example)")
    else:
        print("  = .env (already exists, skipped)")

    print(f"\nDone: {len(FILES)} files + .env handled -> {root}")
    print("Next: pytest -v  (expect 14 passed)")


if __name__ == "__main__":
    main()