"""Router de inventario."""

from fastapi import APIRouter

from services.runtime import runtime

router = APIRouter(prefix="/inventario", tags=["inventario"])


@router.get("")
async def get_inventario() -> dict[str, int]:
    """Retorna inventario actual por SKU."""
    return runtime.data_loader.load_inventario()


@router.get("/alertas")
async def get_alertas_inventario() -> list[dict]:
    """Genera alertas simples por bajo inventario."""
    inv = runtime.data_loader.load_inventario()
    productos = runtime.data_loader.load_productos()
    alertas: list[dict] = []
    for sku, stock in inv.items():
        if stock <= 20:
            alertas.append(
                {
                    "sku": sku,
                    "nombre": productos[sku].nombre if sku in productos else sku,
                    "tipo": "BAJO_STOCK",
                    "stock_actual": stock,
                }
            )
    return alertas
