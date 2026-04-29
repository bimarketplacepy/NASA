"""Router de productos y forecast por SKU."""

from fastapi import APIRouter, HTTPException, Query

from schemas.productos import Producto
from schemas.simulacion import ForecastResult
from services.runtime import runtime

router = APIRouter(prefix="/productos", tags=["productos"])


@router.get("", response_model=list[Producto])
async def list_productos(
    categoria: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> list[Producto]:
    """Lista productos con filtro opcional por categoria y paginacion."""
    items = list(runtime.data_loader.load_productos().values())
    if categoria:
        items = [p for p in items if p.categoria_id == categoria]
    start = (page - 1) * size
    end = start + size
    return items[start:end]


@router.get("/{sku}", response_model=Producto)
async def get_producto(sku: str) -> Producto:
    """Retorna detalle de producto por SKU."""
    prod = runtime.data_loader.load_productos().get(sku)
    if prod is None:
        raise HTTPException(status_code=404, detail={"error_code": "PRODUCTO_NOT_FOUND", "sku": sku})
    return prod


@router.get("/{sku}/forecast", response_model=ForecastResult)
async def get_producto_forecast(sku: str, semanas: int = Query(1, ge=1, le=26)) -> ForecastResult:
    """Retorna forecast de demanda para SKU."""
    if sku not in runtime.data_loader.load_productos():
        raise HTTPException(status_code=404, detail={"error_code": "PRODUCTO_NOT_FOUND", "sku": sku})
    return runtime.forecast_service.forecast(sku, semanas_adelante=semanas, n_samples=200)
