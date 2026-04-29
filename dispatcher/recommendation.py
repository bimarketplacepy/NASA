"""AlgorithmRecommendation: resultado del dispatcher.

El dispatcher recibe un DecisionContext y devuelve un AlgorithmRecommendation
con uno o mas AlgorithmStage compuestos (forma B del didactico Bloque 7:
lista de etapas tipadas por `kind`).

El AlgorithmRecommendation NO ejecuta el algoritmo (eso es Tarea 4 del
equipo). Solo describe que algoritmo invocar y con que parametros, mas
el rastro de razonamiento.

Ejemplo de Recommendation con 3 stages:
    AlgorithmRecommendation(
        sku="246295",
        stages=(
            AlgorithmStage(kind=Kind.POLICY_FORM, descriptor_id="affine_ordering_policy"),
            AlgorithmStage(kind=Kind.WEIGHTING, descriptor_id="ewma_smoothing", parametros={"alpha": 0.15}),
            AlgorithmStage(kind=Kind.UNCERTAINTY_SET, descriptor_id="bounded_deviations", parametros={"epsilon_factor": 1.5}),
        ),
        reglas_aplicadas=("regla_001_existing_estable",),
        confianza=0.90,
        razonamiento=(...)
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True)
class AlgorithmStage:
    """Una etapa de la combinacion de algoritmos.

    Cada stage corresponde a un AlgorithmDescriptor del catalogo
    (`dispatcher.algorithms`). El `kind` es redundante con
    `descriptor_id` (todo descriptor tiene un kind fijo) pero se duplica
    aca para que el consumidor de Tarea 4 pueda iterar `stages` por kind
    sin re-lookup en el catalogo.
    """

    kind: str  # Kind.value (ej: "policy_form", "weighting")
    descriptor_id: str  # ej: "affine_ordering_policy"
    parametros: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AlgorithmRecommendation:
    """Resultado de AlgorithmDispatcher.decidir().

    Args:
        sku: SKU para el cual se decidio.
        stages: tupla de stages compuestos. Vacia si la decision fue
            bloqueada deonticamente (en cuyo caso `bloqueada_por_deontica`
            no es vacio).
        reglas_aplicadas: ids de reglas YAML cuyas condiciones dispararon.
            En el modelo first-match-wins solo hay una; el campo es tupla
            por consistencia futura.
        confianza: [0,1]. Combina la confianza_base de la regla con
            ajustes (ej: cold_start_confidence baja arrastra hacia abajo).
        razonamiento: lista de strings paso a paso del proceso del
            dispatcher.
        bloqueada_por_deontica: norm_ids del Bloque 6 que bloquearon la
            decision. Vacio si la decision pasa el filtro deontico.
        evaluated_at: timestamp UTC de cuando se decidio.
    """

    sku: str
    stages: tuple[AlgorithmStage, ...]
    reglas_aplicadas: tuple[str, ...]
    confianza: float
    razonamiento: tuple[str, ...]
    bloqueada_por_deontica: tuple[str, ...] = ()
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def algoritmo_invocado(self) -> bool:
        """True si hay al menos un stage propuesto. False si bloqueada."""
        return len(self.stages) > 0

    @property
    def descriptores_ids(self) -> tuple[str, ...]:
        """Tupla de descriptor_ids en orden, util para hashing/comparacion."""
        return tuple(s.descriptor_id for s in self.stages)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(s.kind for s in self.stages)

    def to_dict(self) -> dict:
        """Serializa a dict JSON-friendly para audit / persistencia."""
        return {
            "sku": self.sku,
            "stages": [
                {
                    "kind": s.kind,
                    "descriptor_id": s.descriptor_id,
                    "parametros": dict(s.parametros),
                }
                for s in self.stages
            ],
            "reglas_aplicadas": list(self.reglas_aplicadas),
            "confianza": self.confianza,
            "razonamiento": list(self.razonamiento),
            "bloqueada_por_deontica": list(self.bloqueada_por_deontica),
            "evaluated_at": self.evaluated_at.isoformat(),
        }
