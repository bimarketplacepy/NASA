"""DecisionContext: snapshot inmutable del estado relevante para decidir.

El dispatcher recibe un DecisionContext ya construido (no consulta Neo4j).
Para construirlo desde el grafo se usa el helper opcional `from_ontology()`
que toma un OntologyClientV2 y un sku y arma todos los campos.

Decision de diseno: dataclass plano con campos explicitos. NO usamos un
dict generico para que las reglas YAML que referencian
`context.tipo_sku == 'existing'` fallen rapido si el campo no existe (en
construccion, no en evaluacion de regla 47).

Integracion con Bloque 6: si la decision propuesta ya fue evaluada
deonticamente, el resultado vive en `eval_deontica`. El dispatcher lee
ese campo para no invocar algoritmo si esta bloqueada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _utc_now() -> datetime:
    """datetime UTC timezone-aware (reemplazo de datetime.utcnow() deprecado en 3.12)."""
    return datetime.now(timezone.utc)


class TipoSku(str, Enum):
    """Familia del SKU desde la perspectiva del dispatcher.

    EXISTING: SKU con historial de ventas suficiente (>= cobertura minima).
    NEW: SKU sin historial (cold-start). Se apoya en similar_top_k.
    TRENDING: SKU con senal de tendencia activa (TrendSignal del catalogo).
              Puede ser EXISTING o NEW que ademas detecto tendencia.
    """

    EXISTING = "existing"
    NEW = "new"
    TRENDING = "trending"


@dataclass(frozen=True)
class SimilarRef:
    """Referencia a un producto similar (output del Bloque 5).

    Subset de SimilarityResult con solo los campos que necesita el
    dispatcher para decidir. No incluye flags ni breakdown por scorer
    (esos quedan en el Bloque 5 para auditoria).
    """

    sku: str
    score_total: float
    confidence: float = 0.5


@dataclass(frozen=True)
class EventoProximo:
    """Snapshot del proximo evento comercial relevante."""

    nombre: str
    dias_hasta: int
    impacto_demanda_estimado: float = 1.0  # multiplicador respecto a baseline


@dataclass(frozen=True)
class TrendSignal:
    """Senal de tendencia (cuando exista TrendSignal ABox poblada)."""

    fuente: str  # ej "google_trends", "social_listening", "manual"
    valor: float  # magnitud de la tendencia (positiva o negativa)
    confianza: float = 0.0  # [0,1]


@dataclass(frozen=True)
class DecisionContext:
    """Snapshot rico del contexto de una decision de planificacion.

    Inmutable. Construido por el caller (orquestador del flujo) o via el
    helper `from_ontology()` que arma desde OntologyClientV2.

    Args:
        sku: identificador del producto (siempre como string para evitar
             el bug latente del v1 con int/string).
        tipo_sku: clasificacion para el dispatcher.
        nombre: nombre comercial (para razonamiento legible).
        categoria: categoria merceologica.

        semanas_historia: cuantas semanas de historial de ventas. 0 si new.
        cantidad_stock: stock actual.
        velocidad: rotacion proxy (Bloque 4).
        volatilidad_forecast: desvio relativo del forecast historico [0,1+].
                              0=demanda predecible, 1+=alta volatilidad.
        cold_start_confidence: confianza del Bloque 5 si tipo_sku=NEW.
                               1.0 si EXISTING (no aplica).

        similar_top_k: lista ordenada (por score desc) de SKUs similares.
                       Si tipo_sku=NEW, el dispatcher puede usar el primero
                       para heredar parametros.
        evento_proximo: si hay evento dentro del horizonte de planificacion.
        trend_signal: si hay senal de tendencia activa.

        presupuesto_categoria_disponible_usd: cuanto queda en el budget.
        moq_unidades: minimum order quantity del proveedor.
        proveedores_disponibles: cantidad activa.

        eval_deontica: resultado de evaluar la decision contra el catalogo
                       deontico (Bloque 6). None si no se evaluo todavia.
        evaluated_at: timestamp UTC.
    """

    # Identidad
    sku: str
    tipo_sku: TipoSku
    nombre: str = ""
    categoria: str = ""

    # Historia y volatilidad
    semanas_historia: int = 0
    cantidad_stock: float = 0.0
    velocidad: float = 0.0
    volatilidad_forecast: float = 0.5
    cold_start_confidence: float = 1.0

    # Senales del Bloque 5 / 4
    similar_top_k: tuple[SimilarRef, ...] = ()
    evento_proximo: Optional[EventoProximo] = None
    trend_signal: Optional[TrendSignal] = None

    # Restricciones operativas / financieras
    presupuesto_categoria_disponible_usd: float = 0.0
    moq_unidades: float = 0.0
    proveedores_disponibles: int = 0

    # Integracion deontica (Bloque 6)
    # eval_deontica: typing como `Optional[Any]` para evitar import circular.
    # El dispatcher comprueba `eval_deontica.permitida` si no es None.
    eval_deontica: Optional[object] = None

    # Metadata
    evaluated_at: datetime = field(default_factory=_utc_now)

    # -------------------------------------------------------------------------
    # Properties auxiliares para reglas YAML mas legibles
    # -------------------------------------------------------------------------

    @property
    def tiene_historia_suficiente(self) -> bool:
        return self.semanas_historia >= 52

    @property
    def es_volatil(self) -> bool:
        return self.volatilidad_forecast >= 0.3

    @property
    def similar_top_score(self) -> float:
        """Score total del similar mas cercano, o 0 si no hay similares."""
        return self.similar_top_k[0].score_total if self.similar_top_k else 0.0

    @property
    def similar_top_sku(self) -> Optional[str]:
        return self.similar_top_k[0].sku if self.similar_top_k else None

    @property
    def trend_confidence(self) -> float:
        return self.trend_signal.confianza if self.trend_signal else 0.0

    @property
    def evento_dentro_de_lead_time(self) -> bool:
        """True si hay evento proximo dentro del horizonte de pedido (4 sem)."""
        return self.evento_proximo is not None and self.evento_proximo.dias_hasta <= 28

    @property
    def deontica_bloqueada(self) -> bool:
        """True si hay eval_deontica y NO esta permitida."""
        return self.eval_deontica is not None and not getattr(
            self.eval_deontica, "permitida", True
        )

    @property
    def deontica_motivos(self) -> tuple[str, ...]:
        """Lista de norm_ids que bloquean la decision (vacia si permitida)."""
        if self.eval_deontica is None:
            return ()
        bloqueada = tuple(getattr(self.eval_deontica, "bloqueada_por", ()))
        pendientes = tuple(
            getattr(self.eval_deontica, "obligaciones_pendientes", ())
        )
        return bloqueada + pendientes

    # -------------------------------------------------------------------------
    # Construccion desde dict / OntologyClientV2
    # -------------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionContext":
        """Construye desde dict JSON-friendly.

        Convierte campos especiales:
        - tipo_sku: str -> TipoSku enum
        - similar_top_k: list[dict] -> tuple[SimilarRef, ...]
        - evento_proximo: dict -> EventoProximo
        - trend_signal: dict -> TrendSignal
        - evaluated_at: ISO string -> datetime
        """
        d = dict(data)
        if "tipo_sku" in d and not isinstance(d["tipo_sku"], TipoSku):
            d["tipo_sku"] = TipoSku(d["tipo_sku"])
        if "similar_top_k" in d:
            d["similar_top_k"] = tuple(
                SimilarRef(**s) if isinstance(s, dict) else s
                for s in d["similar_top_k"]
            )
        if isinstance(d.get("evento_proximo"), dict):
            d["evento_proximo"] = EventoProximo(**d["evento_proximo"])
        if isinstance(d.get("trend_signal"), dict):
            d["trend_signal"] = TrendSignal(**d["trend_signal"])
        if isinstance(d.get("evaluated_at"), str):
            d["evaluated_at"] = datetime.fromisoformat(d["evaluated_at"])
        # eval_deontica: si viene como dict (deserializacion JSON), lo
        # envolvemos en un SimpleNamespace para que las properties
        # `deontica_bloqueada` / `deontica_motivos` (que hacen getattr)
        # funcionen igual que con el objeto nativo del Bloque 6.
        ev = d.get("eval_deontica")
        if isinstance(ev, dict):
            from types import SimpleNamespace

            d["eval_deontica"] = SimpleNamespace(
                permitida=ev.get("permitida", True),
                bloqueada_por=tuple(ev.get("bloqueada_por", ())),
                obligaciones_pendientes=tuple(
                    ev.get("obligaciones_pendientes", ())
                ),
            )
        return cls(**d)


def from_ontology(
    ont_client,
    sku: str,
    eval_deontica: Optional[object] = None,
    k_similares: int = 5,
) -> DecisionContext:
    """Helper: arma un DecisionContext consultando OntologyClientV2.

    Lookup tolerante: si una llamada al cliente falla, el campo queda en
    su default y se loguea (no propaga la falla). Esto permite usar el
    dispatcher en entornos donde Neo4j no esta corriendo (tests).

    Args:
        ont_client: instancia de OntologyClientV2 (o un mock con la misma
            API: `producto(sku)`, `productos_similares(sku, k)`).
        sku: producto a contextualizar (string o int -> normalizado a str).
        eval_deontica: si la decision ya fue evaluada deonticamente, el
            resultado se inyecta en el contexto.
        k_similares: cuantos similares pedir a la base.

    Returns:
        DecisionContext con los campos disponibles. Los faltantes
        quedan en defaults (no falla si el SKU no existe).
    """
    sku_str = str(sku)

    # Lookup del producto (best-effort)
    nombre = ""
    categoria = ""
    perecedero = False
    try:
        info = ont_client.producto(sku_str)
        if info:
            nombre = str(info.get("nombre", ""))
            categoria = str(info.get("categoria", ""))
            perecedero = bool(info.get("perecedero", False))
    except Exception:
        pass  # default vacio

    # Similares (best-effort)
    similares: tuple[SimilarRef, ...] = ()
    try:
        sim_results = ont_client.productos_similares(sku_str, k=k_similares)
        similares = tuple(
            SimilarRef(
                sku=str(getattr(r, "sku_b", getattr(r, "sku", ""))),
                score_total=float(getattr(r, "score_total", 0.0)),
                confidence=float(getattr(r, "confidence", 0.5)),
            )
            for r in sim_results
        )
    except Exception:
        pass

    # Inferir tipo_sku rough: si no hay historia conocida, NEW; sino EXISTING
    # (caller puede sobreescribir si tiene mas info)
    tipo_sku = TipoSku.NEW if not nombre else TipoSku.EXISTING

    return DecisionContext(
        sku=sku_str,
        tipo_sku=tipo_sku,
        nombre=nombre,
        categoria=categoria,
        similar_top_k=similares,
        eval_deontica=eval_deontica,
        # Resto de campos quedan en sus defaults
    )
