from fastapi import FastAPI
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
