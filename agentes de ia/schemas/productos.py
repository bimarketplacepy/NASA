"""Schemas de productos y categorias."""

from pydantic import BaseModel


class Producto(BaseModel):
    """Producto del catalogo."""

    sku: str
    nombre: str
    categoria_id: str
    perecedero: bool
    vida_util_dias: int | None = None
    precio_referencia: float
    margen_objetivo: float
    descripcion: str
    tags: list[str]


class Categoria(BaseModel):
    """Categoria comercial."""

    categoria_id: str
    nombre: str
    patron_estacional: list[float]
    elasticidad_precio: float
