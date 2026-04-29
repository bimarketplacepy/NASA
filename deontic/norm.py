"""Dataclasses inmutables para normas deonticas + resultado de evaluacion.

Las normas se cargan desde TTL (ontology_semantic/normas_marketplace.ttl) y se
construyen via fabrica en `resolver._parse_normas_ttl`. NO se construyen a
mano salvo en tests. `frozen=True` para evitar mutaciones accidentales en
runtime (las normas son datos de configuracion, no estado).

Modalidades:
    O - Obligation - obliga una accion o estado.
    P - Permission - explicitamente permite una accion (puede derrotar F).
    F - Prohibition - prohibe una accion.

Las tres modalidades son disjuntas (corresponden a las clases :Obligation,
:Permission, :Prohibition de la TBox marketplace.ttl, declaradas como
owl:AllDisjointClasses).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Modality(str, Enum):
    """Las tres modalidades deonticas primitivas (O, P, F).

    Hereda de str para que `Modality.OBLIGATION == "obligation"` sea True
    (util para JSON serialization y comparaciones).
    """

    OBLIGATION = "obligation"
    PERMISSION = "permission"
    PROHIBITION = "prohibition"


# =============================================================================
# Excepciones del modulo
# =============================================================================


class NormaInvalida(ValueError):
    """La definicion de una norma no es coherente.

    Casos:
        - priority fuera de [0, 100].
        - valid_from > valid_until.
        - applies_when nombra un predicado no registrado.
        - falta atributo requerido en el TTL fuente.
    """


class UnresolvedDeonticConflict(RuntimeError):
    """Conflicto deontico que no pudo resolverse.

    Disparado por el resolver cuando dos normas aplicables tienen el mismo
    target con modalidades en conflicto (O-F o F-P) y la resolucion no logra
    un ganador via :defeats explicito ni prioridad numerica (empate o no
    defeasible).

    El operador debe revisar el catalogo de normas y agregar :defeats o
    cambiar prioridades.
    """


# =============================================================================
# Norm + subclases por modalidad (frozen, kw_only)
# =============================================================================


@dataclass(frozen=True, kw_only=True)
class Norm:
    """Norma deontica generica. Subclases especifican modalidad.

    Args:
        norm_id: Identificador local (ej: "F_compra_perecedero_sin_viabilidad").
            Se deriva del local-name del IRI en el TTL fuente.
        modality: Una de las tres modalidades. Las subclases (Obligation,
            Permission, Prohibition) la fijan automaticamente.
        applies_when: Nombre de predicado registrado via @register_predicate.
            El predicado recibe (decision, contexto) y devuelve bool. La
            semantica varia con la modalidad (ver docstring de modulo
            resolver.py).
        target: Etiqueta abstracta del acto/estado regulado. Dos normas
            con el mismo `target` son candidatas a conflicto si las
            modalidades son incompatibles (O-F o F-P).
        priority: Prioridad 0-100. Mayor = mas fuerte. Usado en resolucion
            por prioridad cuando no hay :defeats explicito.
        valid_from: Inicio de vigencia (UTC). None = sin inicio (siempre
            vigente desde el origen).
        valid_until: Fin de vigencia (UTC). None = sin caducidad.
        defeasible: True si puede ser derrotada por otra norma. Una norma no
            defeasible NUNCA queda derrotada; si entra en conflicto sin
            forma de resolver, el resolver levanta UnresolvedDeonticConflict.
        defeats: tupla de norm_id que esta norma derrota explicitamente
            cuando ambas son aplicables al mismo contexto.
        source: Justificacion de negocio (string libre) para audit trail.
    """

    norm_id: str
    modality: Modality
    applies_when: str
    target: str
    priority: int
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    defeasible: bool = True
    defeats: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.priority, int):
            raise NormaInvalida(
                f"priority de {self.norm_id} debe ser int, recibido "
                f"{type(self.priority).__name__}"
            )
        if not (0 <= self.priority <= 100):
            raise NormaInvalida(
                f"priority de {self.norm_id} debe estar en [0,100], "
                f"recibido: {self.priority}"
            )
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from > self.valid_until
        ):
            raise NormaInvalida(
                f"valid_from > valid_until en {self.norm_id}: "
                f"{self.valid_from} > {self.valid_until}"
            )
        if not self.applies_when:
            raise NormaInvalida(
                f"{self.norm_id} no tiene applies_when (predicado obligatorio)."
            )
        if not self.target:
            raise NormaInvalida(
                f"{self.norm_id} no tiene target (etiqueta de conflicto)."
            )

    def is_valid_at(self, when: datetime) -> bool:
        """Devuelve True si la norma esta vigente en el instante `when`.

        Una norma sin valid_from se considera vigente desde el origen.
        Una norma sin valid_until se considera vigente sin caducidad.
        """
        if self.valid_from is not None and when < self.valid_from:
            return False
        if self.valid_until is not None and when > self.valid_until:
            return False
        return True


@dataclass(frozen=True, kw_only=True)
class Obligation(Norm):
    """Obligation: la decision debe satisfacer la condicion."""

    modality: Modality = Modality.OBLIGATION


@dataclass(frozen=True, kw_only=True)
class Permission(Norm):
    """Permission: la condicion esta explicitamente permitida.

    Util para definir excepciones a Prohibitions (via :defeats) o para
    documentar permisos que de otro modo serian ambiguos.
    """

    modality: Modality = Modality.PERMISSION


@dataclass(frozen=True, kw_only=True)
class Prohibition(Norm):
    """Prohibition: la decision NO debe satisfacer la condicion."""

    modality: Modality = Modality.PROHIBITION


# =============================================================================
# Resultado de evaluacion (inmutable)
# =============================================================================


@dataclass(frozen=True)
class EvaluacionDeontica:
    """Resultado de evaluar una decision contra el catalogo de normas.

    Inmutable. Se serializa al audit trail JSONL via `to_dict()`.

    Attributes:
        permitida: True sii no hay Prohibitions ni Obligations aplicables
            no derrotadas. Decision puede ejecutarse.
        bloqueada_por: norm_ids de Prohibitions aplicables y no derrotadas.
            Si no esta vacio, la decision esta bloqueada.
        obligaciones_pendientes: norm_ids de Obligations aplicables y no
            derrotadas (no satisfechas por la decision). Bloquean la
            ejecucion hasta cumplirse.
        normas_aplicadas: norm_ids que pasaron vigencia + applies_when y NO
            fueron derrotadas. Set final que justifica el veredicto.
        normas_derrotadas: tupla de pares (norm_id, motivo) explicando por
            que una norma aplicable quedo descartada.
        razonamiento: lista de strings paso a paso del proceso del resolver.
            Para mostrar al operador / log de auditoria.
        evaluated_at: instante en que se evaluo (UTC).
    """

    permitida: bool
    bloqueada_por: tuple[str, ...]
    obligaciones_pendientes: tuple[str, ...]
    normas_aplicadas: tuple[str, ...]
    normas_derrotadas: tuple[tuple[str, str], ...]  # (norm_id, motivo)
    razonamiento: tuple[str, ...]
    evaluated_at: datetime

    def to_dict(self) -> dict:
        """Serializa a dict JSON-friendly para audit trail."""
        return {
            "permitida": self.permitida,
            "bloqueada_por": list(self.bloqueada_por),
            "obligaciones_pendientes": list(self.obligaciones_pendientes),
            "normas_aplicadas": list(self.normas_aplicadas),
            "normas_derrotadas": {nid: motivo for nid, motivo in self.normas_derrotadas},
            "razonamiento": list(self.razonamiento),
            "evaluated_at": self.evaluated_at.isoformat(),
        }
