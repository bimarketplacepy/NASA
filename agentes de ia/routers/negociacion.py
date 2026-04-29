"""Router de borradores de negociacion."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.runtime import runtime

router = APIRouter(prefix="/negociacion", tags=["negociacion"])


class NegociacionRequest(BaseModel):
    recomendacion_id: str
    proveedor_id: str


@router.post("/borrador")
async def borrador_negociacion(payload: NegociacionRequest) -> dict:
    """Genera borrador de email para proveedor."""
    rec = runtime.last_recomendacion
    if rec is None or rec.recomendacion_id != payload.recomendacion_id:
        raise HTTPException(status_code=404, detail={"error_code": "RECOMENDACION_NOT_FOUND"})
    prov = runtime.data_loader.load_proveedores().get(payload.proveedor_id)
    if prov is None:
        raise HTTPException(status_code=404, detail={"error_code": "PROVEEDOR_NOT_FOUND"})

    items = [i for i in rec.items if i.proveedor_id == payload.proveedor_id]
    if not items:
        raise HTTPException(status_code=400, detail={"error_code": "PROVEEDOR_SIN_ITEMS_EN_RECOMENDACION"})
    body = runtime.negotiator_service.redactar(
        proveedor=prov,
        items=items,
        historial={"volumen_acumulado_usd": 12000.0, "frecuencia_anual": 2},
        perfil_operador={"operador_id": rec.operador_id},
    )
    return {"recomendacion_id": rec.recomendacion_id, "proveedor_id": payload.proveedor_id, "borrador": body}
