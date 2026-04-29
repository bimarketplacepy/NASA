"""Servicio de detección de tendencias del Proyecto NASA (Tarea Mateo).

Pipeline end-to-end alineado con la spec del ingeniero (v2):

1. Recibe posts crudos de redes sociales (mock o scraping real).
2. Extrae trends con LLM en formato ``TrendOutputCincoCampos``.
3. Valida descripcion/fuente/velocidad/confianza con SHACL.
4. Cruza con el catalogo via SimilarityEngine para obtener
   ``productos_existentes_similares`` como ``list[ProductoSimilar]``.
5. Construye ``TrendSignal`` canonico (schemas/tendencias.py).
6. Inyecta al knowledge graph via ``trend_injector.inyectar_trend_validado``,
   que usa el bridge OWL real de Abi cuando esta disponible y cae al
   ``OntologiaClient`` mock cuando no.

Decisiones explicitas v2:
- ESTE SERVICIO NO ROUTEA. La eleccion de algoritmo (ROBUST_AFFINE vs
  HEURISTIC_BUFFER vs los ~6 algoritmos del paper) es trabajo del
  dispatcher de Abi, no de Mateo. Se elimino ``_decidir_enrutamiento``.
- ``boost_demanda_sugerido`` y ``motor_sugerido`` ya NO viven en el
  TrendSignal. El optimizer calcula su boost a partir de
  ``velocidad_crecimiento`` directamente.

Author: Proyecto NASA - Tarea 2 (Mateo)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from pydantic import ValidationError

from clients.data_loader import DataLoader
from clients.llm_client import LLMClient
from clients.ontologia_client import OntologiaClient

# Usa SimilarityEngine real de Abi (Bloque 6) si está disponible;
# cae al mock léxico mientras tanto.
try:
    from ontology_semantic.similarity import SimilarityEngine  # type: ignore[import]
    _usando_similarity_real = True
except (ImportError, Exception):
    from clients.similarity_mock import SimilarityEngineMock as SimilarityEngine  # type: ignore[assignment]
    _usando_similarity_real = False

from schemas.tendencias import (
    ProductoSimilar,
    TrendOutputCincoCampos,
    TrendSignal,
)
from services.trends.semantic_matcher import SemanticMatcher
from services.trends.shacl_validator import SHACLValidator
from services.trends.trend_injector import inyectar_trend_validado


_CINCO_KEYS = (
    "descripcion",
    "fuente",
    "velocidad_crecimiento",
    "confianza_extraccion",
    "productos_existentes_similares",
)


def _normalizar_dict_tendencia_llm(raw: dict[str, Any]) -> dict[str, Any]:
    """Alinea el dict del LLM/scraper al contrato de TrendOutputCincoCampos.

    - Recorta descripcion a 500 caracteres y trimea.
    - Normaliza la fuente al enum de FuenteTrend (TIKTOK/INSTAGRAM/PINTEREST/
      GOOGLE_TRENDS/OTHER), mapeando aliases conocidos. Cualquier valor no
      reconocido cae a OTHER.
    - Convierte velocidad_crecimiento a porcentaje [0, 1000].
    - Acota confianza_extraccion a [0, 1].
    - Garantiza que productos_existentes_similares sea list[str].
    """
    t = dict(raw)
    desc = str(t.get("descripcion", "")).strip()
    t["descripcion"] = desc[:500]

    fuente = str(t.get("fuente", "")).strip().upper().replace(" ", "_")
    aliases = {
        "TIK_TOK": "TIKTOK",
        "META": "INSTAGRAM",
        "IG": "INSTAGRAM",
        "PIN": "PINTEREST",
        "GOOGLE": "GOOGLE_TRENDS",
        "TRENDS": "GOOGLE_TRENDS",
    }
    fuente = aliases.get(fuente, fuente)
    if fuente not in {"TIKTOK", "INSTAGRAM", "PINTEREST", "GOOGLE_TRENDS"}:
        fuente = "OTHER"
    t["fuente"] = fuente

    try:
        vel = float(t.get("velocidad_crecimiento", 0.0))
    except (TypeError, ValueError):
        vel = 0.0
    if 0.0 < vel < 1.0:
        vel *= 100.0
    t["velocidad_crecimiento"] = max(0.0, min(1000.0, vel))

    try:
        conf = float(t.get("confianza_extraccion", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    while conf > 1.0:
        conf /= 100.0
    t["confianza_extraccion"] = max(0.0, min(1.0, conf))

    ps = t.get("productos_existentes_similares", [])
    if isinstance(ps, str):
        ps = [ps] if ps.strip() else []
    elif ps is None:
        ps = []
    else:
        ps = [str(x).strip() for x in ps if str(x).strip()]
    t["productos_existentes_similares"] = ps

    return t


def _dicts_a_payload_shacl(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtra los dicts del LLM a los que cumplen el contrato de 5 campos.

    Anade timestamp por defecto si falta para que la validacion SHACL no
    rechace por falta de fechaDeteccion.
    """
    salida: list[dict[str, Any]] = []
    for raw in items:
        try:
            n = _normalizar_dict_tendencia_llm(raw)
            cinco = TrendOutputCincoCampos.model_validate({k: n[k] for k in _CINCO_KEYS})
            ts = n.get("timestamp") or datetime.now(timezone.utc).isoformat()
            salida.append({**cinco.model_dump(mode="python"), "timestamp": ts})
        except (ValidationError, KeyError) as exc:
            logger.warning(
                f"Tendencia descartada por contrato 5 campos: {exc}"
            )
    return salida


def _trend_id_estable(descripcion: str, fuente: str, fecha: datetime) -> str:
    """Genera un trend_id idempotente y legible.

    Args:
        descripcion: Texto del trend.
        fuente: Plataforma normalizada.
        fecha: Timestamp de deteccion.

    Returns:
        Identificador con prefijo ``trend_`` y hash corto del contenido.
    """
    seed = f"{descripcion}|{fuente}|{fecha.date().isoformat()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"trend_{digest}"


def _extraer_keywords(texto: str) -> list[str]:
    """Extrae keywords basicas del texto del trend (sin LLM)."""
    stopwords = {
        "el", "la", "de", "y", "a", "en", "que", "es", "con", "por", "para",
        "un", "una", "los", "las", "del", "al", "se", "su", "sus", "esta",
        "estos", "estas", "este", "ese", "esa", "esos", "esas",
    }
    palabras = texto.lower().split()
    keywords = [
        p.strip(",.!?;:#")
        for p in palabras
        if len(p) > 3 and p.strip(",.!?;:#") not in stopwords
    ]
    # Devuelve top 10 sin duplicados preservando orden.
    vistos: dict[str, None] = {}
    for kw in keywords:
        if kw and kw not in vistos:
            vistos[kw] = None
    return list(vistos.keys())[:10]


class TrendsService:
    """Orquestador del pipeline de tendencias.

    Args:
        llm_client: Cliente Gemini para extraccion estructurada.
        data_loader: Acceso a CSVs sinteticos.
        ontologia_client: Cliente del knowledge graph (mock o real).
        shacl_validator: Validador SHACL. Si es None se crea uno con shapes
            inline.
        semantic_matcher: Validador semantico contra catalogo (TF-IDF o
            embeddings). Si es None se instancia con TF-IDF.
        similarity_engine: Motor de similitud composite. Si es None usa el
            mock lexico hasta que Abi entregue el real.
        shapes_path: Ruta opcional al shapes.ttl externo de Abi. Si es None,
            se usa el inline default del shacl_validator.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        data_loader: DataLoader,
        ontologia_client: OntologiaClient,
        shacl_validator: Optional[SHACLValidator] = None,
        semantic_matcher: Optional[SemanticMatcher] = None,
        similarity_engine: Optional[SimilarityEngine] = None,
        shapes_path: str | Path | None = None,
    ) -> None:
        self.llm = llm_client
        self.data = data_loader
        self.ontologia = ontologia_client
        self.shapes_path = shapes_path
        self.validator = shacl_validator or SHACLValidator(shapes_path=shapes_path)
        self.semantic_matcher = semantic_matcher or SemanticMatcher(data_loader=data_loader)
        self.similarity_engine = similarity_engine or SimilarityEngine(data_loader=data_loader)
        modo = "real (Abi Bloque 6)" if _usando_similarity_real else "mock léxico"
        logger.info(f"TrendsService listo: SHACL + similarity={modo} + injector adaptador")

    # ================================================================
    # Pipeline principal
    # ================================================================

    async def procesar_senales_scrapeadas(
        self,
        raw_data: list[dict[str, Any]],
        umbral_confianza_minima: float = 0.4,
        umbral_semantico: float | None = None,
        umbral_similitud: float = 0.6,
        inyectar_en_grafo: bool = True,
    ) -> list[TrendSignal]:
        """Ejecuta el pipeline completo y devuelve TrendSignals canonicos.

        Args:
            raw_data: Posts crudos del scraper (cada uno es un dict).
            umbral_confianza_minima: Umbral de confianza para que el trend
                se inyecte al grafo.
            umbral_semantico: Umbral de match semantico contra catalogo.
                Si es None se usa el del semantic_matcher.
            umbral_similitud: Umbral del SimilarityEngine para incluir
                productos en ``productos_existentes_similares``.
            inyectar_en_grafo: Si True, inyecta trends validados via
                ``trend_injector``. Si False, solo retorna la lista.

        Returns:
            Lista de ``TrendSignal`` que pasaron SHACL + semantica +
            confianza minima. Cada TrendSignal tiene
            ``validado_shacl=True`` y ``provisional=True``.
        """
        logger.info(f"Pipeline trends: {len(raw_data)} posts crudos")

        # Paso 1: extraccion LLM
        crudos = await self._extraer_con_llm(raw_data)
        normalizados = _dicts_a_payload_shacl(crudos)
        logger.info(f"  paso 1 (LLM): {len(normalizados)} dicts normalizados")

        # Paso 2: validacion SHACL sobre dicts crudos (rechazo temprano)
        validas_shacl, invalidas_shacl = self.validator.validar_batch(normalizados)
        if invalidas_shacl:
            logger.warning(
                f"  paso 2 (SHACL): {len(invalidas_shacl)} rechazadas"
            )
        logger.info(f"  paso 2 (SHACL): {len(validas_shacl)} OK")

        # Paso 3: validacion semantica contra catalogo
        umbral_sem = umbral_semantico if umbral_semantico is not None else self.semantic_matcher.umbral
        aprobadas_sem, rechazadas_sem = self.semantic_matcher.validar_batch(
            validas_shacl, umbral_aprobacion=umbral_sem
        )
        if rechazadas_sem:
            logger.warning(
                f"  paso 3 (semantica): {len(rechazadas_sem)} rechazadas (match debil)"
            )
        logger.info(f"  paso 3 (semantica): {len(aprobadas_sem)} OK")

        # Paso 4: enriquecer con SimilarityEngine -> list[ProductoSimilar]
        signals: list[TrendSignal] = []
        for trend_dict in aprobadas_sem:
            try:
                ts = await self._construir_trend_signal(trend_dict, umbral_similitud)
            except (ValidationError, ValueError) as exc:
                logger.warning(
                    f"  paso 4 (similarity): trend descartado: {exc}"
                )
                continue
            signals.append(ts)
        logger.info(f"  paso 4 (similarity): {len(signals)} TrendSignals construidos")

        # Paso 5: filtrar por confianza minima
        signals = [s for s in signals if s.confianza_extraccion >= umbral_confianza_minima]
        logger.info(f"  paso 5 (confianza>={umbral_confianza_minima}): {len(signals)} OK")

        # Paso 6: inyeccion al grafo via adaptador (bridge OWL si existe, mock si no)
        if inyectar_en_grafo:
            inyectados = 0
            for ts in signals:
                if inyectar_trend_validado(ts, shapes_path=self.shapes_path):
                    inyectados += 1
            logger.info(f"  paso 6 (inyeccion): {inyectados}/{len(signals)} en grafo")

        return signals

    # ================================================================
    # Paso 1: extraccion LLM
    # ================================================================

    async def _extraer_con_llm(self, raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Llama a Gemini para extraer trends en formato JSON.

        Args:
            raw_data: Posts crudos del scraper.

        Returns:
            Lista de dicts crudos con las 5 claves del contrato.
        """
        catalogo = self.data.load_productos()
        catalogo_resumido = [
            {"sku": p.sku, "nombre": p.nombre, "categoria": p.categoria_id}
            for p in list(catalogo.values())[:50]
        ]

        prompt = f"""
Sos un analista de tendencias de retail navideno. Analiza el siguiente corpus
de posts de redes sociales y extrae productos navidenos emergentes que
muestran senales de viralidad.

CRITERIOS DE VIRALIDAD:
- Mencionado por multiples autores independientes.
- Metricas crecientes (likes, shares, views).
- Sentimiento mayoritariamente positivo.
- Idealmente NO esta en el catalogo (es novedad).

CATALOGO ACTUAL (primeros 20 SKUs para excluir):
{catalogo_resumido[:20]}

POSTS A ANALIZAR ({len(raw_data)} posts):
{raw_data}

DEVOLVE JSON con array `tendencias`. Cada elemento tiene EXACTAMENTE estas 5 claves:
{{
  "tendencias": [
    {{
      "descripcion": "Descripcion >= 10 chars",
      "fuente": "TIKTOK|INSTAGRAM|PINTEREST|GOOGLE_TRENDS|OTHER",
      "velocidad_crecimiento": <float 0-1000 (porcentaje semanal)>,
      "confianza_extraccion": <float 0-1>,
      "productos_existentes_similares": []
    }}
  ]
}}

Si no hay tendencias claras devolve {{"tendencias": []}}. Devolve SOLO JSON,
sin markdown ni explicaciones.
""".strip()

        try:
            response = await self.llm.generate_structured(
                prompt=prompt,
                raw_posts=raw_data,
                temperature=0.2,
                max_tokens=4000,
            )
            if isinstance(response, dict) and "tendencias" in response:
                trends = response["tendencias"]
            elif isinstance(response, list):
                trends = response
            else:
                logger.error(f"Respuesta LLM con forma inesperada: {type(response)}")
                trends = []
            for trend in trends:
                if "timestamp" not in trend or not trend["timestamp"]:
                    trend["timestamp"] = datetime.now(timezone.utc).isoformat()
            return trends
        except Exception as exc:  # noqa: BLE001 - degradar a lista vacia
            logger.error(f"Extraccion LLM fallo: {exc}")
            return []

    # ================================================================
    # Paso 4: construccion del TrendSignal canonico
    # ================================================================

    async def _construir_trend_signal(
        self,
        trend_dict: dict[str, Any],
        umbral_similitud: float,
    ) -> TrendSignal:
        """Convierte un dict validado en un TrendSignal canonico.

        - Resuelve fecha_deteccion desde timestamp del LLM o now().
        - Construye productos_existentes_similares como
          ``list[ProductoSimilar]`` enriqueciendo con datos del catalogo
          y scoring del SimilarityEngine.
        - Genera trend_id estable por contenido (idempotencia).
        """
        descripcion = str(trend_dict["descripcion"]).strip()
        fuente = str(trend_dict["fuente"]).strip()
        ts_raw = trend_dict.get("timestamp")
        if isinstance(ts_raw, datetime):
            fecha_deteccion = ts_raw
        elif isinstance(ts_raw, str) and ts_raw.strip():
            fecha_deteccion = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            fecha_deteccion = datetime.now(timezone.utc)

        keywords = _extraer_keywords(descripcion)
        skus_llm = list(trend_dict.get("productos_existentes_similares") or [])

        candidatos = await self.similarity_engine.encontrar_similares(
            texto=descripcion,
            keywords=keywords,
            k=10,
            umbral=umbral_similitud,
            incluir_desglose=False,
        )
        productos: list[ProductoSimilar] = []
        skus_vistos: set[str] = set()
        for cand in candidatos:
            if cand.sku in skus_vistos:
                continue
            productos.append(
                ProductoSimilar(
                    sku=cand.sku,
                    score=float(cand.score),
                    nombre=cand.nombre,
                    categoria=cand.categoria,
                    precio_referencia=float(cand.precio),
                )
            )
            skus_vistos.add(cand.sku)

        # Mergear los SKUs sugeridos por el LLM si existen en catalogo.
        catalogo = self.data.load_productos()
        for sku in skus_llm:
            if sku in skus_vistos:
                continue
            producto = catalogo.get(sku)
            if producto is None:
                continue
            productos.append(
                ProductoSimilar(
                    sku=sku,
                    score=float(trend_dict.get("score_match_semantico", 0.0) or 0.0),
                    nombre=producto.nombre,
                    categoria=getattr(producto, "categoria_id", "DESCONOCIDA"),
                    precio_referencia=float(getattr(producto, "precio_referencia", 0.0)),
                )
            )
            skus_vistos.add(sku)

        productos = productos[:10]

        trend_id = trend_dict.get("trend_id") or _trend_id_estable(
            descripcion, fuente, fecha_deteccion
        )

        return TrendSignal(
            trend_id=str(trend_id),
            descripcion=descripcion,
            palabras_clave=keywords,
            fuente=fuente,
            fecha_deteccion=fecha_deteccion,
            metadata_fuente={
                "score_match_semantico": float(trend_dict.get("score_match_semantico", 0.0) or 0.0),
                "validacion_semantica": str(trend_dict.get("validacion_semantica", "")),
            },
            velocidad_crecimiento=float(trend_dict["velocidad_crecimiento"]),
            confianza_extraccion=float(trend_dict["confianza_extraccion"]),
            productos_existentes_similares=productos,
            validado_shacl=False,  # se marca True al inyectar
            provisional=True,
        )


__all__ = ["TrendsService"]
