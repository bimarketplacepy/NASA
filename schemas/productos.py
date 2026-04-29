"""Schema minimal de Producto que requieren los modulos de trends/.

trends/semantic_matcher.py accede `p.nombre`, `p.descripcion`, `p.tags`
(list[str]), `p.categoria_id`. Si el catalogo Pegasus no tiene
descripcion/tags como columnas, usar defaults vacios y el matcher
cae a nombre + categoria.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Producto(BaseModel):
    """Producto del catalogo Pegasus segun lo que trends/ necesita."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    sku: str = Field(..., min_length=1)
    nombre: str = ""
    nombre_corto: str = ""
    descripcion: str = ""
    categoria_id: str = ""
    grupo_id: str = ""
    precio_referencia: float = 0.0
    pais_origen: str = ""
    perecedero: bool = False
    tags: list[str] = Field(default_factory=list)
