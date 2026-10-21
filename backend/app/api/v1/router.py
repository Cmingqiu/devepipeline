from fastapi import APIRouter

from app.api.v1 import artifacts, health, projects, requirements, runs, stream

api_router = APIRouter()
api_router.include_router(projects.router)
api_router.include_router(requirements.router)
api_router.include_router(runs.router)
api_router.include_router(artifacts.router)
api_router.include_router(stream.router)

__all__ = ["api_router", "health"]
