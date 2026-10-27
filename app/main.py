from fastapi import FastAPI
from app.config import settings
from app.api.runs import router as runs_router

app = FastAPI(title="Streaming Agent Gateway", version="0.0.1")
app.include_router(runs_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "version": app.version}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
