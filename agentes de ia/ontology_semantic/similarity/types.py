"""types.py - Tipos publicos del modulo similarity.

Mantenidos en archivo separado para evitar ciclos de import entre engine,
embeddings y precompute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BehavioralFlag(str, Enum):
    """Estado de la senal comportamental para un par dado.

    Se usa para que ``composite_score`` sepa cuando renormalizar pesos.

    Values:
        AVAILABLE: ambos SKUs tienen serie de ventas mensuales completa.
        MISSING_BOTH: ninguno tiene historia (ambos cold-start).
        MISSING_A: solo el SKU A no tiene historia.
        MISSING_B: solo el SKU B no tiene historia.
        UNAVAILABLE_GLOBAL: la fuente de datos mensual no esta integrada
            todavia. ESTE ES EL ESTADO ACTUAL del sistema (Bloque 5)
            mientras Cris/Mauri completan VENTAS_DET por mes.
    """
    AVAILABLE = "available"
    MISSING_BOTH = "missing_both"
    MISSING_A = "missing_a"
    MISSING_B = "missing_b"
    UNAVAILABLE_GLOBAL = "unavailable_global"


@dataclass(frozen=True)
class SimilarityResult:
    """Resultado tipado de una comparacion de similitud par-a-par.

    Es ``frozen`` para que pueda usarse como key en sets y para evitar
    mutaciones accidentales aguas abajo en el dispatcher (Bloque 7).
    """

    sku_a: str
    sku_b: str
    score_lexical: float
    score_structural: float
    score_behavioral: float
    score_trend: float
    score_total: float
    confidence: float
    behavioral_flag: BehavioralFlag = BehavioralFlag.UNAVAILABLE_GLOBAL
    flags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for label, val in [
            ("score_lexical", self.score_lexical),
            ("score_structural", self.score_structural),
            ("score_behavioral", self.score_behavioral),
            ("score_trend", self.score_trend),
            ("score_total", self.score_total),
            ("confidence", self.confidence),
        ]:
            if val < -0.001 or val > 1.001:
                raise ValueError(
                    f"SimilarityResult.{label}={val} fuera de [0, 1] "
                    f"para par ({self.sku_a}, {self.sku_b})"
                )

    def to_dict(self) -> dict[str, object]:
        """Serializa a dict para Neo4j / JSON / tests."""
        return {
            "sku_a": self.sku_a,
            "sku_b": self.sku_b,
            "score_lex": round(self.score_lexical, 6),
            "score_str": round(self.score_structural, 6),
            "score_beh": round(self.score_behavioral, 6),
            "score_trd": round(self.score_trend, 6),
            "score_total": round(self.score_total, 6),
            "confidence": round(self.confidence, 6),
            "behavioral_flag": self.behavioral_flag.value,
            "flags": list(self.flags),
        }
