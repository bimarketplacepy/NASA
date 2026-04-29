"""Router de proveedores."""

from fastapi import APIRouter, HTTPException

from schemas.proveedores import Proveedor
from services.runtime import runtime

router = APIRouter(prefix="/proveedores", tags=["proveedores"])


@router.get("", response_model=list[Proveedor])
async def list_proveedores() -> list[Proveedor]:
    """Lista proveedores disponibles."""
    return list(runtime.data_loader.load_proveedores().values())


@router.get("/{proveedor_id}", response_model=Proveedor)
async def get_proveedor(proveedor_id: str) -> Proveedor:
    """Retorna proveedor por ID."""
    prov = runtime.data_loader.load_proveedores().get(proveedor_id)
    if prov is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "PROVEEDOR_NOT_FOUND", "proveedor_id": proveedor_id},
        )
    return prov
