"""Router de salud del servicio."""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def healthcheck() -> dict[str, str]:
    """Valida disponibilidad basica de la API."""
    return {"status": "ok"}
