"""
forecast/forecast.py
---------------------
Servicio de forecasting estacional + caracterizacion de series.

Implementa los items #19 y #20 del plan de Tarea 3:
  - forecast(sku, semanas_adelante, boost_tendencia, sku_donante) async
  - caracterizar_serie(sku) publico para el dispatcher de Abi

Es un wrapper sobre statsmodels.ExponentialSmoothing (Holt-Winters) con:
  - Resolucion de fuente: own / inherited / category_default / trend_only
  - Cold-start via sku_donante (lo pasa Abi desde su similarity engine)
  - Samples Monte Carlo internos para percentiles (n_sims chico, ~20)
  - Confianza global decisional configurable

Spec autoritativo: Especificaciones_CRIS.pdf v2, secciones 4.3, 4.4, 4.5.

Nota sobre tipos: la spec define sku como str. El grafo guarda
:Producto.sku como int (decision de Abi al cargar productos.csv). Por
eso este modulo castea int(sku) ANTES de cualquier query Cypher. Si te
olvidas del cast, el MATCH no devuelve nada y el sistema asume cold-start
silenciosamente. Ojo con esto al extenderlo.

Marketplace SA Paraguay - Linea Navidad - Tarea 3 (Cris).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from forecast.config import ForecastConfig
from forecast.models import CaracteristicasSerie, ForecastResult


logger = logging.getLogger(__name__)


class ForecastService:
    """Servicio de forecasting + caracterizacion para Tarea 3.

    Es la pieza que el dispatcher de Abi consume (paso 4-5 del flujo
    end-to-end de la spec, seccion 6).

    Cold-start (busqueda semantica interna) — orden de prioridad cuando
    el caller NO pasa sku_donante y el SKU no tiene historia propia:

    1. Si se inyecto ``donor_finder`` callable, se usa (override de tests
       o del dispatcher de Abi cuando quiera lógica custom).
    2. Si el OntologyClient soporta ``productos_similares()`` (es decir,
       es un :class:`OntologyClientV2`), se consulta el top-1 de aristas
       :SIMILAR_A precomputadas en Neo4j.
    3. Fallback: histórico promedio de la categoria del SKU
       (fuente='category_default').
    4. Si la categoria tampoco tiene datos: fuente='trend_only'.

    Para que funcione el paso 2, alguien tuvo que correr previamente:
        python -m ontology_semantic.similarity.precompute_top_k run

    Si ese precompute no esta hecho, productos_similares devuelve [] y
    el forecast cae al paso 3 sin romper.

    Attributes:
        ont: OntologyClient v1 o v2 de Abi para consultar el grafo.
        config: ForecastConfig con todos los parametros tuneables.
        donor_finder: Override callable opcional para cold-start.
    """

    def __init__(
        self,
        ont_client,  # OntologyClient v1 o OntologyClientV2 (no se importa para evitar ciclo)
        config: Optional[ForecastConfig] = None,
        donor_finder: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.ont = ont_client
        self.config = config or ForecastConfig()
        self.donor_finder = donor_finder
        # Detectar si el cliente expone busqueda de similares precomputados.
        # OntologyClientV2 tiene productos_similares; OntologyClient v1 no.
        self._tiene_similares = hasattr(ont_client, "productos_similares")
        self._rng = np.random.default_rng(self.config.semilla_random)

    # =========================================================================
    # API PUBLICA
    # =========================================================================

    async def forecast(
        self,
        sku: str,
        semanas_adelante: int = 8,
        boost_tendencia: float = 1.0,
        sku_donante: Optional[str] = None,
    ) -> ForecastResult:
        """Pronostica unidades por semana para un SKU.

        Args:
            sku: SKU objetivo (string como define la spec).
            semanas_adelante: Horizonte del pronostico. Default 8.
            boost_tendencia: Multiplicador final del pronostico para
                ajustes adhoc (ej: tendencia viral detectada por Mateo).
                1.0 = sin boost. >1 amplifica, <1 atenua.
            sku_donante: Si se pasa, hereda historia de ese SKU
                (cold-start dirigido por similarity engine de Abi).

        Returns:
            ForecastResult con media + std + percentiles + samples +
            metadata decisional (fuente, confianza, caracteristicas).
        """
        # 1. Resolver fuente y obtener historico.
        historico_propio = self._consultar_ventas_semanales(sku)
        semanas_propias = int(len(historico_propio))

        if sku_donante is not None:
            historico = self._consultar_ventas_semanales(sku_donante)
            fuente: str = "inherited"
        elif semanas_propias >= self.config.min_semanas_propias:
            historico = historico_propio
            fuente = "own"
        else:
            # Sin donante explicito y sin historia propia: probar busqueda
            # semantica interna (callable custom > similares precomputados),
            # luego fallback categoria.
            donante_inferido = self._buscar_donante(sku)
            if donante_inferido:
                sku_donante = donante_inferido
                historico = self._consultar_ventas_semanales(sku_donante)
                fuente = "inherited"
            else:
                historico_cat = self._consultar_ventas_categoria(sku)
                if len(historico_cat) > 0:
                    historico = historico_cat
                    fuente = "category_default"
                else:
                    historico = pd.Series(dtype=float)
                    fuente = "trend_only"

        # 2. Caracterizar la serie usada (no la propia: la usada).
        caracteristicas = self._caracterizar(historico)

        # 3. Pronosticar.
        media, std = self._pronosticar(historico, semanas_adelante, boost_tendencia)

        # 4. Samples Monte Carlo internos + percentiles.
        samples = self._muestrear(media, std)
        p5 = np.percentile(samples, 5, axis=0).tolist()
        p50 = np.percentile(samples, 50, axis=0).tolist()
        p95 = np.percentile(samples, 95, axis=0).tolist()

        # 5. Confianza global decisional.
        confianza = self._calcular_confianza(caracteristicas, fuente)

        # 6. Construir resultado validado por Pydantic.
        return ForecastResult(
            sku=str(sku),
            media=media,
            std=std,
            p5=p5,
            p50=p50,
            p95=p95,
            samples=samples,
            fuente=fuente,  # type: ignore[arg-type]
            sku_donante=sku_donante,
            semanas_de_historia_propia=semanas_propias,
            confianza_global=confianza,
            caracteristicas_serie=caracteristicas,
        )

    def caracterizar_serie(self, sku: str) -> CaracteristicasSerie:
        """Caracteriza la serie historica de un SKU para el dispatcher.

        El dispatcher de Abi llama esto ANTES de llamar a forecast() para
        decidir que algoritmo usar (EWMA bounded vs robust affine + buffer,
        etc., ver spec seccion 4.4).

        Args:
            sku: SKU a caracterizar.

        Returns:
            CaracteristicasSerie con volatilidad, ciclicidad, tendencia
            local, autocorrelacion lag-1 y semanas_efectivas.
        """
        historico = self._consultar_ventas_semanales(sku)
        return self._caracterizar(historico)

    # =========================================================================
    # PRIVADOS - busqueda semantica interna (cold-start)
    # =========================================================================

    def _buscar_donante(self, sku: str) -> Optional[str]:
        """Busca un sku_donante para cold-start.

        Orden de prioridad:
        1. ``self.donor_finder`` callable inyectado (override de tests
           o del dispatcher de Abi). Si devuelve un sku, se usa.
        2. ``ont.productos_similares()`` si el cliente es OntologyClientV2:
           top-1 de aristas :SIMILAR_A precomputadas con score por encima
           de ``config.umbral_similitud_donante``.
        3. ``None`` si nada anterior produjo un candidato. El forecast
           cae a category_default.

        Args:
            sku: SKU objetivo que necesita un donante.

        Returns:
            sku_donante (str) o None.
        """
        # Prioridad 1: callable override.
        if self.donor_finder is not None:
            try:
                candidato = self.donor_finder(sku)
                if candidato:
                    return str(candidato)
            except Exception as exc:
                logger.warning("donor_finder fallo para sku=%s: %s", sku, exc)

        # Prioridad 2: aristas :SIMILAR_A del grafo (OntologyClientV2).
        if self._tiene_similares:
            try:
                similares = self.ont.productos_similares(
                    sku=sku,
                    k=1,
                    umbral=self.config.umbral_similitud_donante,
                )
                if similares:
                    return str(similares[0].sku_b)
            except Exception as exc:
                logger.warning(
                    "productos_similares fallo para sku=%s: %s "
                    "(verificar que precompute_top_k haya corrido)",
                    sku, exc,
                )

        return None

    # =========================================================================
    # PRIVADOS - acceso al grafo
    # =========================================================================

    def _consultar_ventas_semanales(self, sku: str) -> pd.Series:
        """Devuelve la serie de unidades vendidas ordenada cronologicamente.

        Castea el sku a int internamente para coincidir con
        :Producto.sku que se guarda como int en Neo4j.
        """
        try:
            sku_int = int(sku)
        except (ValueError, TypeError):
            logger.warning("SKU '%s' no se puede castear a int", sku)
            return pd.Series(dtype=float)

        query = """
            MATCH (p:Producto {sku: $sku_int})-[:TIENE_VENTAS]->(v:VentaSemanal)
            RETURN v.anio AS anio, v.semana AS semana, v.unidades AS unidades
            ORDER BY anio, semana
        """
        with self.ont.driver.session() as session:
            registros = list(session.run(query, sku_int=sku_int))

        if not registros:
            return pd.Series(dtype=float)

        unidades = [float(r["unidades"]) for r in registros]
        return pd.Series(unidades, name="unidades")

    def _consultar_ventas_categoria(self, sku: str) -> pd.Series:
        """Promedio semanal de ventas en la categoria del SKU.

        Fallback cuando el SKU no tiene historia propia ni donante.
        Suma unidades por (anio, semana) sobre todos los SKUs de la
        misma categoria, dividido por el numero de SKUs distintos que
        vendieron en esa semana (promedio por SKU activo).
        """
        try:
            sku_int = int(sku)
        except (ValueError, TypeError):
            return pd.Series(dtype=float)

        query = """
            MATCH (p:Producto {sku: $sku_int})-[:PERTENECE_A]->(c:Categoria)
            MATCH (otros:Producto)-[:PERTENECE_A]->(c)
            MATCH (otros)-[:TIENE_VENTAS]->(v:VentaSemanal)
            WITH v.anio AS anio, v.semana AS semana,
                 sum(v.unidades) AS unidades_total,
                 count(DISTINCT otros) AS skus_activos
            RETURN anio, semana,
                   toFloat(unidades_total) / skus_activos AS unidades_promedio
            ORDER BY anio, semana
        """
        with self.ont.driver.session() as session:
            registros = list(session.run(query, sku_int=sku_int))

        if not registros:
            return pd.Series(dtype=float)

        return pd.Series(
            [float(r["unidades_promedio"]) for r in registros],
            name="unidades_promedio_categoria",
        )

    # =========================================================================
    # PRIVADOS - logica numerica
    # =========================================================================

    def _caracterizar(self, historico: pd.Series) -> CaracteristicasSerie:
        """Calcula metricas descriptivas de una serie."""
        n = len(historico)
        if n < 8:
            return CaracteristicasSerie(
                volatilidad=0.0,
                ciclicidad=0.0,
                tendencia_local=0.0,
                autocorrelacion_lag1=0.0,
                semanas_efectivas=n,
            )

        h = historico.astype(float)

        media = float(h.mean())
        std = float(h.std(ddof=0))
        volatilidad = (std / media) if media > 0 else 0.0

        ciclicidad = 0.0
        if n > self.config.seasonal_periods:
            ac52 = h.autocorr(lag=self.config.seasonal_periods)
            if pd.notna(ac52):
                ciclicidad = float(ac52)

        tendencia_local = 0.0
        ultimas12 = h.tail(12)
        if len(ultimas12) >= 2:
            x = np.arange(len(ultimas12))
            slope, _ = np.polyfit(x, ultimas12.values.astype(float), 1)
            tendencia_local = float(slope)

        autocorrelacion_lag1 = 0.0
        ac1 = h.autocorr(lag=1)
        if pd.notna(ac1):
            autocorrelacion_lag1 = float(ac1)

        return CaracteristicasSerie(
            volatilidad=volatilidad,
            ciclicidad=ciclicidad,
            tendencia_local=tendencia_local,
            autocorrelacion_lag1=autocorrelacion_lag1,
            semanas_efectivas=n,
        )

    def _pronosticar(
        self,
        historico: pd.Series,
        h: int,
        boost: float,
    ) -> tuple[list[float], list[float]]:
        """Holt-Winters multiplicativo si hay >=2 ciclos, sino sin estacional.

        Devuelve (media, std) como dos listas de longitud h.
        Si la serie es muy corta para Holt-Winters, cae a media historica.
        """
        n = len(historico)

        # Sin datos: devolver ceros con incertidumbre por default.
        if n == 0:
            return [0.0] * h, [1.0] * h

        # Datos minimos pero insuficientes para Holt-Winters: media + std.
        if n < 4:
            media_hist = float(historico.mean()) * boost
            std_hist = float(historico.std(ddof=0)) or 1.0
            return [media_hist] * h, [std_hist] * h

        # Decidir componentes segun longitud disponible.
        usar_estacional = (
            self.config.seasonal is not None
            and n >= self.config.min_semanas_estacional
        )
        seasonal_arg = self.config.seasonal if usar_estacional else None
        periods_arg = self.config.seasonal_periods if usar_estacional else None
        trend_arg = self.config.trend if n >= 8 else None

        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            modelo = ExponentialSmoothing(
                historico.astype(float).values,
                trend=trend_arg,
                seasonal=seasonal_arg,
                seasonal_periods=periods_arg,
                initialization_method="estimated",
            )
            fit = modelo.fit(optimized=True)
            pred = np.asarray(fit.forecast(h)) * boost
            pred = np.maximum(pred, 0.0)

            residuos = np.asarray(fit.resid)
            std_resid = float(np.nanstd(residuos)) if residuos.size else 0.0
            if not np.isfinite(std_resid) or std_resid <= 0.0:
                std_resid = max(1.0, float(np.nanmean(historico)) * 0.3)

            return pred.tolist(), [std_resid] * h

        except Exception as exc:
            logger.warning(
                "Holt-Winters fallo (%s); fallback a media historica", exc
            )
            media_hist = float(historico.mean()) * boost
            std_hist = float(historico.std(ddof=0)) or 1.0
            return [media_hist] * h, [std_hist] * h

    def _muestrear(self, media: list[float], std: list[float]) -> np.ndarray:
        """Genera samples ~N(media, std) con n_sims chicos.

        Devuelve array shape (n_sims, len(media)). Se trunca en 0 (las
        ventas no pueden ser negativas).
        """
        n_sims = self.config.n_sims
        loc = np.asarray(media)
        scale = np.maximum(np.asarray(std), 1e-6)  # evitar scale=0
        samples = self._rng.normal(loc=loc, scale=scale, size=(n_sims, len(media)))
        return np.maximum(samples, 0.0)

    def _calcular_confianza(
        self, c: CaracteristicasSerie, fuente: str,
    ) -> float:
        """Score [0, 1] que el dispatcher usa para ponderar la prediccion.

        Formula configurable (forecast/config.py):

            confianza = w_h * factor_historia
                      + w_v * factor_volatilidad
                      + w_c * factor_ciclicidad
                      + w_f * factor_fuente

        Donde cada factor esta normalizado a [0, 1]:
          - factor_historia    = min(1, semanas_efectivas / semanas_referencia)
          - factor_volatilidad = max(0, 1 - volatilidad)
          - factor_ciclicidad  = (ciclicidad + 1) / 2     (de [-1,1] a [0,1])
          - factor_fuente      = config.confianza_por_fuente[fuente]
        """
        cfg = self.config

        f_h = min(1.0, c.semanas_efectivas / cfg.semanas_referencia)
        f_v = max(0.0, 1.0 - c.volatilidad)
        f_c = (c.ciclicidad + 1.0) / 2.0
        f_f = cfg.confianza_por_fuente.get(fuente, 0.5)

        score = (
            cfg.peso_historia * f_h
            + cfg.peso_volatilidad * f_v
            + cfg.peso_ciclicidad * f_c
            + cfg.peso_fuente * f_f
        )
        return float(np.clip(score, 0.0, 1.0))
