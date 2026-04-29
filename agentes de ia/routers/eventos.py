"""Router de eventos comerciales."""

from fastapi import APIRouter

from schemas.eventos import EventoComercial
from services.runtime import runtime

router = APIRouter(prefix="/eventos", tags=["eventos"])


@router.get("", response_model=list[EventoComercial])
async def list_eventos() -> list[EventoComercial]:
    """Lista eventos comerciales disponibles."""
    return runtime.data_loader.load_eventos()
