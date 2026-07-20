"""HTTP routers grouped by the Java business domains."""

from fastapi import APIRouter


def application_routers() -> list[APIRouter]:
    """Return every migrated business router; imports stay explicit for coverage auditing."""
    from app.routers.agent import router as agent_router
    from app.routers.config import config_router
    from app.routers.correctword import correctword_router
    from app.routers.device import device_router
    from app.routers.knowledge import knowledge_router
    from app.routers.model import model_router
    from app.routers.security import security_router
    from app.routers.sys import sys_router
    from app.routers.timbre import timbre_router
    from app.routers.voiceclone import voiceclone_router

    return [
        security_router,
        sys_router,
        config_router,
        agent_router,
        device_router,
        voiceclone_router,
        model_router,
        timbre_router,
        correctword_router,
        knowledge_router,
    ]
