"""
forecast/monte_carlo.py
------------------------
Motor Monte Carlo deontico-aware (item #21 del plan Tarea 3).

Simula escenarios de demanda + valorizacion de una cartera de compra
respetando las restricciones que provienen de la capa deontica de Abi
(Bloque 5). Cada restriccion se asocia a una norma (PROV-O); cuando un
escenario viola una norma se descarta del muestreo y se contabiliza
para que el dispatcher pueda explicar el sesgo.

Spec autoritativo: Especificaciones_CRIS.pdf v2, seccion 4.5.

Tipos de restriccion soportadas en esta primera version:
  - 'no_exceder_dias_validez' (perecederos: total_vendido en
    primeras (dias_validez/7) semanas debe cubrir cantidad_comprada).
  - 'cantidad_minima_proveedor' (MOQ del proveedor;
    parametros.moq o item.cantidad_minima_proveedor).
  - 'presupuesto_maximo_pyg' (cap a la suma costo_total de la cartera;
    parametros.presupuesto_pyg).

Mati / Abi pueden agregar mas tipos extendiendo
:meth:`MonteCarloSimulator._evaluar_restricciones`.

Marketplace SA Paraguay - Linea Navidad - Tarea 3 (Cris).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from forecast.config import ForecastConfig
from forecast.models import ForecastResult


# =============================================================================
# Modelos Pydantic
# =============================================================================

class Restriccion(BaseModel):
    """Restriccion deontica que filtra escenarios del muestreo.

    Spec seccion 4.5. Cada restriccion proviene de una norma de la capa
    deontica de Abi (Bloque 5). El field ``fuente_norma_id`` permite
    trazar PROV-O para que el LLM explique por que se descarto un
    escenario.

    Attributes:
        tipo: Identificador del tipo de restriccion. Tipos conocidos:
            'no_exceder_dias_validez', 'cantidad_minima_proveedor',
            'presupuesto_maximo_pyg'. Tipos desconocidos se ignoran
            silenciosamente con un warning (forward-compatible).
        parametros: Parametros especificos del tipo. Estructura:
            no_exceder_dias_validez -> {} (lee de Item.dias_validez).
            cantidad_minima_proveedor -> {'moq': int} opcional.
            presupuesto_maximo_pyg -> {'presupuesto_pyg': float}.
        fuente_norma_id: Identificador de la norma origen (ej. 'N-001').
    """

    tipo: str
    parametros: dict = Field(default_factory=dict)
    fuente_norma_id: str


class Item(BaseModel):
    """Producto a comprar dentro de una cartera Monte Carlo.

    Lleva la metadata necesaria para evaluar restricciones sin tener
    que volver al grafo durante la simulacion (n_sims grande).

    Attributes:
        sku: SKU del producto.
        cantidad_comprada: Cuantas unidades se planea comprar.
        precio_costo_pyg: Costo unitario en guaranies.
        precio_venta_pyg: Precio de venta unitario en guaranies.
        perecedero: True si el producto vence.
        dias_validez: Si perecedero, dias hasta vencimiento desde la
            llegada al deposito. None si no aplica.
        proveedor_id: Id del proveedor (para PROV-O).
        cantidad_minima_proveedor: MOQ del proveedor (None si no aplica).
    """

    sku: str
    cantidad_comprada: int = Field(ge=0)
    precio_costo_pyg: float = Field(ge=0)
    precio_venta_pyg: float = Field(ge=0)
    perecedero: bool = False
    dias_validez: Optional[int] = Field(default=None, ge=0)
    proveedor_id: Optional[int] = None
    cantidad_minima_proveedor: Optional[int] = Field(default=None, ge=0)


class ResultadoMonteCarlo(BaseModel):
    """Resultado de una corrida Monte Carlo.

    Attributes:
        n_simulaciones: n_sims solicitados.
        n_validos: Escenarios que sobrevivieron a las restricciones.
        n_descartados: n_simulaciones - n_validos.
        violaciones_por_norma: Conteo de violaciones por fuente_norma_id.
            Permite al razonador / LLM explicar el sesgo: "se descartaron
            X escenarios por la norma N-001".
        ingresos_total_media: Ingresos totales esperados (PYG) sobre
            escenarios validos.
        ingresos_total_p5: Percentil 5 (cota inferior 90%).
        ingresos_total_p50: Mediana.
        ingresos_total_p95: Percentil 95 (cota superior 90%).
        costo_total_pyg: Costo total fijo de la cartera (no varia entre
            escenarios; depende solo de cantidad_comprada * precio_costo).
        desglose_por_sku: Por SKU, dict con vendidas (media, p5, p50,
            p95) y sobrestock_media (cantidad comprada - vendidas).
    """

    n_simulaciones: int = Field(ge=0)
    n_validos: int = Field(ge=0)
    n_descartados: int = Field(ge=0)
    violaciones_por_norma: dict = Field(default_factory=dict)

    ingresos_total_media: float = 0.0
    ingresos_total_p5: float = 0.0
    ingresos_total_p50: float = 0.0
    ingresos_total_p95: float = 0.0
    costo_total_pyg: float = 0.0
    desglose_por_sku: dict = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


# =============================================================================
# Simulador
# =============================================================================

class MonteCarloSimulator:
    """Motor Monte Carlo de cartera con filtrado deontico.

    Acepta una lista de items (que comprar) + sus forecasts (modelo de
    demanda) + restricciones de la capa deontica. Resamplea n_sims
    escenarios de demanda, evalua cada uno contra las restricciones,
    descarta los invalidos y reporta metricas sobre los validos.

    Attributes:
        config: ForecastConfig (heredamos semilla_random para reproducir).
    """

    # Tipos de restriccion conocidos (forward-compat: desconocidos se ignoran).
    TIPOS_ITEM = {
        "no_exceder_dias_validez",
        "cantidad_minima_proveedor",
    }
    TIPOS_GLOBAL = {
        "presupuesto_maximo_pyg",
    }

    def __init__(self, config: Optional[ForecastConfig] = None) -> None:
        self.config = config or ForecastConfig()
        self._rng = np.random.default_rng(self.config.semilla_random)

    async def simular(
        self,
        items: list[Item],
        forecasts: dict,  # dict[sku_str, ForecastResult]
        restricciones: Optional[list[Restriccion]] = None,
        n_sims: int = 10000,
    ) -> ResultadoMonteCarlo:
        """Corre n_sims escenarios y devuelve metricas filtradas.

        Args:
            items: Lista de Item a evaluar. Si vacia, raise.
            forecasts: Dict ``sku -> ForecastResult``. Cada item.sku
                debe tener su forecast.
            restricciones: Lista de Restriccion. None / [] = sin filtros.
            n_sims: Cantidad de escenarios. Default 10000 (spec sec 5).

        Returns:
            ResultadoMonteCarlo con metricas y desglose.

        Raises:
            ValueError: si items vacio o falta forecast para algun sku.
        """
        if not items:
            raise ValueError("items vacio")

        for it in items:
            if it.sku not in forecasts:
                raise ValueError(
                    f"Falta forecast para sku={it.sku}. "
                    f"Pasa forecasts={{'{it.sku}': ForecastResult, ...}}"
                )

        restricciones = restricciones or []
        n_items = len(items)

        # Horizonte = min de las longitudes de los forecasts.
        horizonte = min(len(forecasts[it.sku].media) for it in items)
        if horizonte == 0:
            raise ValueError("Algun forecast tiene horizonte 0")

        # Samplear demanda por item: shape (n_items, n_sims, horizonte).
        samples_demanda = self._samplear_demanda(items, forecasts, n_sims, horizonte)

        # Demanda total por item por escenario: (n_items, n_sims).
        demanda_total = samples_demanda.sum(axis=2)

        # Evaluar restricciones.
        mask_item, mask_global, violaciones = self._evaluar_restricciones(
            items, samples_demanda, restricciones, n_sims, horizonte,
        )

        # Un escenario es valido si TODOS los items son validos Y la global pasa.
        mask_validos = mask_item.all(axis=0) & mask_global
        n_validos = int(mask_validos.sum())
        n_descartados = n_sims - n_validos

        # Costo fijo de la cartera (no varia entre escenarios).
        costo_total = sum(
            it.cantidad_comprada * it.precio_costo_pyg for it in items
        )

        if n_validos == 0:
            return ResultadoMonteCarlo(
                n_simulaciones=n_sims,
                n_validos=0,
                n_descartados=n_descartados,
                violaciones_por_norma=dict(violaciones),
                costo_total_pyg=float(costo_total),
            )

        # Calcular ingresos por escenario valido.
        ingresos_por_sim = np.zeros(n_validos)
        desglose: dict = {}

        for i, it in enumerate(items):
            demanda_validas = demanda_total[i, mask_validos]
            # Vendidas = min(demanda, cantidad_comprada). Sobrestock = comprado - vendidas.
            vendidas = np.minimum(demanda_validas, it.cantidad_comprada)
            ingresos_item = vendidas * it.precio_venta_pyg
            ingresos_por_sim += ingresos_item

            sobrestock = it.cantidad_comprada - vendidas
            desglose[it.sku] = {
                "vendidas_media": float(vendidas.mean()),
                "vendidas_p5":   float(np.percentile(vendidas, 5)),
                "vendidas_p50":  float(np.percentile(vendidas, 50)),
                "vendidas_p95":  float(np.percentile(vendidas, 95)),
                "sobrestock_media": float(sobrestock.mean()),
            }

        return ResultadoMonteCarlo(
            n_simulaciones=n_sims,
            n_validos=n_validos,
            n_descartados=n_descartados,
            violaciones_por_norma=dict(violaciones),
            ingresos_total_media=float(ingresos_por_sim.mean()),
            ingresos_total_p5=float(np.percentile(ingresos_por_sim, 5)),
            ingresos_total_p50=float(np.percentile(ingresos_por_sim, 50)),
            ingresos_total_p95=float(np.percentile(ingresos_por_sim, 95)),
            costo_total_pyg=float(costo_total),
            desglose_por_sku=desglose,
        )

    # =========================================================================
    # Internals
    # =========================================================================

    def _samplear_demanda(
        self,
        items: list,
        forecasts: dict,
        n_sims: int,
        horizonte: int,
    ) -> np.ndarray:
        """Genera samples ~N(media, std) por item, clip 0.

        Returns:
            Array shape (n_items, n_sims, horizonte) con demanda muestreada.
        """
        out = np.zeros((len(items), n_sims, horizonte), dtype=np.float64)
        for i, it in enumerate(items):
            fr: ForecastResult = forecasts[it.sku]
            media = np.asarray(fr.media[:horizonte], dtype=np.float64)
            std = np.asarray(fr.std[:horizonte], dtype=np.float64)
            scale = np.maximum(std, 1e-6)
            samples = self._rng.normal(loc=media, scale=scale, size=(n_sims, horizonte))
            out[i] = np.maximum(samples, 0.0)
        return out

    def _evaluar_restricciones(
        self,
        items: list,
        samples_demanda: np.ndarray,
        restricciones: list,
        n_sims: int,
        horizonte: int,
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """Evalua todas las restricciones.

        Returns:
            tuple ``(mask_item, mask_global, violaciones)`` donde:
              - mask_item: bool array (n_items, n_sims). True = valido para ese item.
              - mask_global: bool array (n_sims,). True = valido a nivel cartera.
              - violaciones: dict fuente_norma_id -> count.
        """
        n_items = len(items)
        mask_item = np.ones((n_items, n_sims), dtype=bool)
        mask_global = np.ones(n_sims, dtype=bool)
        violaciones: dict = defaultdict(int)

        for r in restricciones:
            if r.tipo == "no_exceder_dias_validez":
                self._aplicar_dias_validez(
                    items, samples_demanda, r, mask_item, violaciones, horizonte,
                )
            elif r.tipo == "cantidad_minima_proveedor":
                self._aplicar_moq(items, r, mask_item, violaciones, n_sims)
            elif r.tipo == "presupuesto_maximo_pyg":
                self._aplicar_presupuesto(items, r, mask_global, violaciones, n_sims)
            # Tipos desconocidos se ignoran (forward-compat).

        return mask_item, mask_global, dict(violaciones)

    def _aplicar_dias_validez(
        self,
        items: list,
        samples_demanda: np.ndarray,
        r: Restriccion,
        mask_item: np.ndarray,
        violaciones: dict,
        horizonte: int,
    ) -> None:
        """Marca como invalido todo escenario donde un perecedero no se vende
        a tiempo. Spec: 'no simular escenarios donde un perecedero excede
        dias_validez'.
        """
        for i, it in enumerate(items):
            if not it.perecedero or it.dias_validez is None:
                continue
            semanas_validez = max(1, it.dias_validez // 7)
            if semanas_validez >= horizonte:
                continue  # toda la ventana cabe en validez, no hay riesgo

            demanda_en_rango = samples_demanda[i, :, :semanas_validez].sum(axis=1)
            valido = demanda_en_rango >= it.cantidad_comprada
            invalidos = ~valido
            if invalidos.any():
                violaciones[r.fuente_norma_id] += int(invalidos.sum())
                mask_item[i] &= valido

    def _aplicar_moq(
        self,
        items: list,
        r: Restriccion,
        mask_item: np.ndarray,
        violaciones: dict,
        n_sims: int,
    ) -> None:
        """Restriccion 'cantidad_minima_proveedor': descarta items que no
        cumplen MOQ. Si la viola, TODA la fila del item queda invalida
        (es estatica, no depende de la demanda muestreada).
        """
        moq_global = r.parametros.get("moq")
        for i, it in enumerate(items):
            moq = moq_global if moq_global is not None else it.cantidad_minima_proveedor
            if moq is None:
                continue
            if it.cantidad_comprada < int(moq):
                violaciones[r.fuente_norma_id] += n_sims
                mask_item[i] = False

    def _aplicar_presupuesto(
        self,
        items: list,
        r: Restriccion,
        mask_global: np.ndarray,
        violaciones: dict,
        n_sims: int,
    ) -> None:
        """Restriccion global 'presupuesto_maximo_pyg': si el costo total
        excede el cap, TODA la simulacion queda invalida.
        """
        presupuesto = r.parametros.get("presupuesto_pyg")
        if presupuesto is None:
            return
        costo_total = sum(
            it.cantidad_comprada * it.precio_costo_pyg for it in items
        )
        if costo_total > float(presupuesto):
            violaciones[r.fuente_norma_id] += n_sims
            mask_global[:] = False
