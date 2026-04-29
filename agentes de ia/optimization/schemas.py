"""Schemas Pydantic centrales de la biblioteca de optimizacion (Tarea 4).

Todos los algoritmos consumen y producen estas estructuras. Los contratos
estan alineados con las specs v2 del equipo NASA:

- ``ForecastResult`` y ``CaracteristicasSerie``: contrato de Cris (Tarea 3).
- ``Restriccion``: contrato de Abi (capa deontica, Bloque 5).
- ``TrendSignal`` y ``ProductoSimilar``: contrato de Mateo (Tarea 2).

Cualquier cambio aqui ROMPE contratos con el resto del equipo. Discutirlo
en grupo antes de implementar.

Referencias: Especificaciones Tecnicas v2 (Mati y Cris).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# Forecast (contrato de Cris - Tarea 3)
# ============================================================


class CaracteristicasSerie(BaseModel):
    """Caracteristicas estadisticas de la serie temporal de un SKU.

    El dispatcher de Abi consulta estos valores para decidir que algoritmo
    invocar. Por ejemplo: si volatilidad < 0.3 y semanas_efectivas > 52,
    elige ``affine_simple`` (EWMA bounded). Si es alta volatilidad y
    cold-start, elige ``cold_inherit`` o ``inv_buffer``.

    Attributes:
        volatilidad: Coeficiente de variacion (std / media). 0 a 1+.
        ciclicidad: Autocorrelacion a lag 52 (estacionalidad anual). -1 a 1.
        tendencia_local: Pendiente de las ultimas 12 semanas. Puede ser negativa.
        autocorrelacion_lag1: Autocorrelacion a lag 1 (persistencia).
        semanas_efectivas: Cantidad real de semanas con datos no nulos.
    """

    volatilidad: float = Field(ge=0.0)
    ciclicidad: float = Field(ge=-1.0, le=1.0, default=0.0)
    tendencia_local: float = 0.0
    autocorrelacion_lag1: float = Field(ge=-1.0, le=1.0, default=0.0)
    semanas_efectivas: int = Field(ge=0)


class ForecastResult(BaseModel):
    """Resultado del forecasting de Cris para un SKU.

    Contiene la prediccion con intervalos de incertidumbre y metadata sobre
    la fuente de los datos. Los algoritmos de optimizacion consumen esto
    como entrada principal.

    Compatibilidad: incluye properties con los nombres antiguos
    (``media_demanda``, ``p5_demanda``, etc.) para no romper codigo legacy
    que pueda existir en el repo. Los nombres nuevos (listas) son los
    canonicos.

    Attributes:
        sku: Identificador del producto.
        media: Lista de predicciones de media por semana del horizonte.
        std: Desviacion estandar por semana del horizonte.
        p5: Percentil 5 (peor caso conservador) por semana.
        p50: Mediana por semana.
        p95: Percentil 95 (mejor caso optimista) por semana.
        samples: Array numpy con muestras Monte Carlo (n_sims, horizonte).
        fuente: De donde salieron los datos del forecast.
        sku_donante: Si fuente == 'inherited', el SKU del que se hereda.
        semanas_de_historia_propia: Semanas con datos propios del SKU.
        confianza_global: Confianza agregada del forecast en 0-1.
        caracteristicas_serie: Estadisticas de la serie usada.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sku: str
    media: list[float]
    std: list[float] = Field(default_factory=list)
    p5: list[float]
    p50: list[float]
    p95: list[float]
    samples: Any = None  # numpy.ndarray opcional; no se valida

    # Metadata para vision decisional v2
    fuente: Literal["own", "inherited", "category_default", "trend_only"] = "own"
    sku_donante: Optional[str] = None
    semanas_de_historia_propia: int = Field(ge=0, default=0)
    confianza_global: float = Field(ge=0.0, le=1.0, default=0.85)
    caracteristicas_serie: CaracteristicasSerie

    # ----- Helpers de conveniencia -----

    @property
    def horizonte_semanas(self) -> int:
        """Cantidad de semanas que abarca el forecast."""
        return len(self.media)

    @property
    def media_demanda(self) -> float:
        """Media total a lo largo del horizonte (compat con codigo legacy)."""
        return float(sum(self.media))

    @property
    def p5_demanda(self) -> float:
        """Suma de p5 en el horizonte (compat legacy)."""
        return float(sum(self.p5))

    @property
    def p50_demanda(self) -> float:
        """Suma de p50 en el horizonte (compat legacy)."""
        return float(sum(self.p50))

    @property
    def p95_demanda(self) -> float:
        """Suma de p95 en el horizonte (compat legacy)."""
        return float(sum(self.p95))

    @property
    def desviacion_estandar(self) -> float:
        """Desviacion total en el horizonte (compat legacy)."""
        if not self.std:
            return 0.0
        return float(sum(self.std))

    @property
    def volatilidad(self) -> float:
        """Volatilidad de la serie (compat legacy, equivale al campo nuevo)."""
        return self.caracteristicas_serie.volatilidad

    @property
    def confianza(self) -> float:
        """Alias legacy de confianza_global."""
        return self.confianza_global


# ============================================================
# Restricciones deonticas (contrato de Abi - Bloque 5)
# ============================================================


SeveridadRestriccion = Literal["obligatoria", "prohibitiva", "recomendada"]


class Restriccion(BaseModel):
    """Restriccion derivada de una norma deontica evaluada por Abi.

    Los algoritmos reciben una lista de estas y deben incorporarlas como
    constraints adicionales. Si la severidad es ``prohibitiva``, el dispatcher
    NO invoca al algoritmo (la decision esta bloqueada antes).

    Tipos comunes:
        - ``min_proveedores``: cantidad minima de proveedores distintos.
        - ``buffer_minimo``: factor multiplicativo de seguridad sobre cantidad.
        - ``preferir_proveedor_local``: prioriza candidatos por region.
        - ``no_exceder_dias_validez``: para perecederos.
        - ``cap_presupuesto``: limita el costo total.
    """

    tipo: str
    parametros: dict[str, Any] = Field(default_factory=dict)
    fuente_norma_id: Optional[str] = None
    severidad: SeveridadRestriccion = "obligatoria"


# ============================================================
# TrendSignal (contrato de Mateo - Tarea 2)
# ============================================================


class ProductoSimilar(BaseModel):
    """Producto del catalogo identificado como similar."""

    sku: str
    score: float = Field(ge=0.0, le=1.0)
    nombre: str = ""


class TrendSignal(BaseModel):
    """Senial de tendencia detectada por el scraper de Mateo."""

    descripcion: str
    fuente: Literal["tiktok", "instagram", "pinterest", "other"] = "other"
    fecha_deteccion: Optional[datetime] = None
    velocidad_crecimiento: float = 0.0
    confianza_extraccion: float = Field(ge=0.0, le=1.0, default=0.5)
    palabras_clave: list[str] = Field(default_factory=list)
    productos_existentes_similares: list[ProductoSimilar] = Field(default_factory=list)
    metadata_fuente: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Proveedores y eventos
# ============================================================


class ProveedorCandidato(BaseModel):
    """Proveedor candidato para abastecer un SKU."""

    proveedor_id: str
    nombre: str
    precio_unitario: float = Field(gt=0.0)
    moq: int = Field(ge=0, default=0)  # minimum order quantity
    lead_time_dias: int = Field(ge=0, default=0)
    confiabilidad: float = Field(ge=0.0, le=1.0, default=0.9)
    region: str = "nacional"
    moneda: str = "USD"
    capacidad_max_semanal: Optional[int] = None


class EventoProximo(BaseModel):
    """Evento del calendario comercial relevante para la decision."""

    nombre: str
    fecha: Optional[datetime] = None
    factor_demanda: float = 1.0
    categorias_afectadas: list[str] = Field(default_factory=list)


# ============================================================
# DecisionContext (input de IAlgorithm.run)
# ============================================================


class DecisionContext(BaseModel):
    """Contexto completo de una decision de compra para un SKU.

    Es el input principal de cada algoritmo. Lo arma el dispatcher de Abi
    juntando datos del grafo, forecast de Cris, trends de Mateo, etc.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sku: str
    forecast: ForecastResult
    proveedores_candidatos: list[ProveedorCandidato] = Field(default_factory=list)
    eventos_proximos: list[EventoProximo] = Field(default_factory=list)
    presupuesto_disponible: float = Field(ge=0.0)
    trend_signal: Optional[TrendSignal] = None
    normas_aplicables: list[str] = Field(default_factory=list)
    sku_donante: Optional[str] = None
    es_perecedero: bool = False
    dias_validez: Optional[int] = None
    horizonte_semanas: int = Field(default=8, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# RecomendacionCompra (output de IAlgorithm.run)
# ============================================================


class RecomendacionCompra(BaseModel):
    """Resultado de un algoritmo de optimizacion para un SKU.

    Devuelve cantidades con intervalos de incertidumbre (p5/p50/p95),
    metricas de riesgo (VaR, CVaR) y trazabilidad de la decision.
    """

    sku: str
    cantidad_central: int = Field(ge=0)
    cantidad_p5: int = Field(ge=0)  # peor caso conservador
    cantidad_p95: int = Field(ge=0)  # mejor caso optimista

    proveedor_sugerido: str
    proveedores_alternativos: list[str] = Field(default_factory=list)

    costo_esperado: float = Field(ge=0.0)
    var_95: float = Field(ge=0.0, default=0.0)  # Value at Risk al 95%
    cvar_95: float = Field(ge=0.0, default=0.0)  # Conditional VaR al 95%

    razon_eleccion: list[str] = Field(default_factory=list)
    algoritmo_id: str
    restricciones_aplicadas: list[str] = Field(default_factory=list)
    timestamp_generacion: datetime = Field(default_factory=datetime.utcnow)
    confianza_resultado: float = Field(ge=0.0, le=1.0, default=0.7)


# ============================================================
# Interfaz IAlgorithm
# ============================================================


@runtime_checkable
class IAlgorithm(Protocol):
    """Contrato que todo algoritmo de la biblioteca debe cumplir.

    El dispatcher de Abi llama ``precondiciones(ctx)`` para verificar si el
    algoritmo aplica al contexto, y luego ``run()`` con las restricciones
    deonticas y parametros adicionales.
    """

    id: str
    nombre: str
    paper_seccion: str

    def precondiciones(self, ctx: DecisionContext) -> bool:
        """Indica si este algoritmo es aplicable al contexto."""
        ...

    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        """Ejecuta la optimizacion y devuelve una recomendacion."""
        ...


__all__ = [
    "CaracteristicasSerie",
    "ForecastResult",
    "Restriccion",
    "SeveridadRestriccion",
    "ProductoSimilar",
    "TrendSignal",
    "ProveedorCandidato",
    "EventoProximo",
    "DecisionContext",
    "RecomendacionCompra",
    "IAlgorithm",
]


# ============================================================
# Test rapido
# ============================================================


if __name__ == "__main__":
    # Demuestra que los schemas son construibles con la nueva forma
    caract = CaracteristicasSerie(
        volatilidad=0.24,
        ciclicidad=0.45,
        tendencia_local=0.02,
        autocorrelacion_lag1=0.7,
        semanas_efectivas=78,
    )
    forecast = ForecastResult(
        sku="SKU_001",
        media=[95.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0],
        std=[18.0] * 8,
        p5=[60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0],
        p50=[95.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0],
        p95=[140.0, 145.0, 150.0, 155.0, 160.0, 165.0, 170.0, 175.0],
        fuente="own",
        semanas_de_historia_propia=78,
        confianza_global=0.88,
        caracteristicas_serie=caract,
    )

    proveedor = ProveedorCandidato(
        proveedor_id="PROV_NAC_01",
        nombre="Norte Festivo SA",
        precio_unitario=12.5,
        moq=100,
        lead_time_dias=7,
        confiabilidad=0.92,
    )

    ctx = DecisionContext(
        sku="SKU_001",
        forecast=forecast,
        proveedores_candidatos=[proveedor],
        presupuesto_disponible=15000.0,
    )

    rec = RecomendacionCompra(
        sku="SKU_001",
        cantidad_central=900,
        cantidad_p5=620,
        cantidad_p95=1280,
        proveedor_sugerido="PROV_NAC_01",
        costo_esperado=11250.0,
        var_95=1200.0,
        cvar_95=1800.0,
        razon_eleccion=["Lead time bajo", "Alta confiabilidad"],
        algoritmo_id="open_loop",
    )

    print(f"Forecast media_total={forecast.media_demanda:.0f}, p95_total={forecast.p95_demanda:.0f}")
    print(f"Volatilidad accesible legacy: {forecast.volatilidad}")
    print(f"Recomendacion: {rec.cantidad_central} unidades (p5={rec.cantidad_p5}, p95={rec.cantidad_p95})")
