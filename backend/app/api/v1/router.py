from fastapi import APIRouter

from app.api.v1 import health, projects, requirements

api_router = APIRouter()
api_router.include_router(projects.router)
api_router.include_router(requirements.router)

__all__ = ["api_router", "health"]
