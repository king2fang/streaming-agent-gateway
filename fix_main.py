"""Fix: add static mount to main.py. Run: python fix_main.py"""
import sys
from pathlib import Path

MAIN_CODE = """from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.api.runs import router as runs_router

app = FastAPI(title="Streaming Agent Gateway", version="0.0.1")
app.include_router(runs_router)

@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "version": app.version}

# 关键点：挂载静态资源目录。必须放在最后，这样优先匹配 API 路由，剩下的全部走前端
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
"""

def main():
    root = Path.cwd()
    if not (root / "pyproject.toml").exists():
        if (root / "streaming-agent-gateway").exists():
            root = root / "streaming-agent-gateway"
        else:
            sys.exit(f"not a gateway project: {root}")
    
    p = root / "app" / "main.py"
    p.write_text(MAIN_CODE, encoding="utf-8", newline="\n")
    print(f"  = {p.relative_to(root)} updated successfully.")
    print("\nDone. Next:")
    print("1. Restart uvicorn")
    print("2. Open http://127.0.0.1:8000/")

if __name__ == "__main__":
    main()