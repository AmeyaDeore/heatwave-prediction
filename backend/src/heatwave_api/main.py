"""Application entry point. Run with: uv run uvicorn heatwave_api.main:app --reload"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from heatwave_api.config import get_settings

settings = get_settings()

app = FastAPI(title="Heatwave Early Warning API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
