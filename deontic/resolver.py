"""DeonticResolver: evalua decisiones contra el catalogo de normas.

Pipeline en 5 pasos:

  1. Filtrar normas VIGENTES (validFrom <= now <= validUntil).
  2. Filtrar normas APLICABLES (predicado appliesWhen devuelve True).
  3. Aplicar :defeats EXPLICITO: cualquier norma aplicable que sea blanco
     de un :defeats de otra norma aplicable queda derrotada.
  4. Detectar CONFLICTOS por target compartido entre modalidades incompatibles
     (O vs F, F vs P) y resolver por:
        (a) :defeats explicito (ya aplicado en paso 3, redundancia segura).
        (b) prioridad numerica (mayor gana, derrota la menor).
     Si empate de prioridad sin :defeats: levanta UnresolvedDeonticConflict.
     Si la norma menor es defeasible=False: levanta UnresolvedDeonticConflict.
  5. Calcular VEREDICTO:
        bloqueada_por = Prohibitions aplicables no derrotadas
        obligaciones_pendientes = Obligations aplicables no derrotadas
        permitida = ambas listas vacias

Cada evaluacion se loguea (si audit_path) en un JSONL append-only para
auditoria humana y preludio del Bloque 8 (PROV-O).

Decision de diseno: el target es el unico mecanismo de deteccion de
conflictos. Dos normas con `target` distinto NO son conflicto aunque
sean aplicables simultaneamente. Esto permite que muchas normas convivan
sin paradojas (por ejemplo, todas las F del catalogo aplican
independientemente — son "razones para bloquear", se acumulan en
bloqueada_por sin choque entre si).
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from deontic.norm import (
    EvaluacionDeontica,
    Modality,
    NormaInvalida,
    Norm,
    Obligation,
    Permission,
    Prohibition,
    UnresolvedDeonticConflict,
)
from deontic.predicates import get_predicate

# Namespace del marketplace (mismo que marketplace.ttl)
MKT = Namespace("http://marketplace.com.py/onto/v1#")


# =============================================================================
# Helpers de parsing TTL
# =============================================================================


def _local_name(uri: Any) -> str:
    """Extrae local-name de un URI (post '#' o post ultimo '/')."""
    s = str(uri)
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    return s.rsplit("/", 1)[-1]


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Asegura que un datetime sea timezone-aware (default UTC).

    rdflib convierte xsd:dateTime sin zona a datetime naive. Convertimos a
    UTC para que las comparaciones con `datetime.now(timezone.utc)` no
    exploten con TypeError.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_python(value: Any) -> Any:
    """Convierte rdflib.Literal a tipo Python nativo, o None."""
    if value is None:
        return None
    if isinstance(value, Literal):
        return value.toPython()
    return str(value)


def _parse_normas_ttl(path: Path) -> list[Norm]:
    """Carga normas_marketplace.ttl y materializa instancias Norm.

    Args:
        path: ruta al .ttl

    Returns:
        lista de Norm (subclase concreta segun rdf:type).

    Raises:
        FileNotFoundError: el TTL no existe.
        NormaInvalida: alguna norma del TTL no tiene atributos requeridos
            o tiene priority fuera de rango.
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"No existe el TTL de normas: {path}")

    g = Graph()
    g.parse(str(path), format="turtle")

    normas: list[Norm] = []

    for owl_class, py_class in (
        (MKT.Obligation, Obligation),
        (MKT.Permission, Permission),
        (MKT.Prohibition, Prohibition),
    ):
        for s in g.subjects(RDF.type, owl_class):
            normas.append(_norma_desde_subject(g, s, py_class))

    if not normas:
        raise NormaInvalida(
            f"El TTL {path} no contiene instancias de :Obligation, "
            f":Permission ni :Prohibition. Revisa los rdf:type."
        )

    return normas


def _norma_desde_subject(g: Graph, s: URIRef, cls: type) -> Norm:
    """Extrae todas las propiedades de una norma desde el grafo."""
    norm_id = _local_name(s)

    applies_when = _to_python(g.value(s, MKT.appliesWhen))
    if not applies_when:
        raise NormaInvalida(f"Norma {norm_id} no tiene :appliesWhen.")

    target = _to_python(g.value(s, MKT.target))
    if not target:
        raise NormaInvalida(f"Norma {norm_id} no tiene :target.")

    priority_v = _to_python(g.value(s, MKT.priority))
    if priority_v is None:
        raise NormaInvalida(f"Norma {norm_id} no tiene :priority.")
    try:
        priority = int(priority_v)
    except (TypeError, ValueError) as e:
        raise NormaInvalida(
            f"Norma {norm_id}: priority no es entero ({priority_v!r})."
        ) from e

    valid_from = _ensure_aware(_to_python(g.value(s, MKT.validFrom)))
    valid_until = _ensure_aware(_to_python(g.value(s, MKT.validTo)))

    defeasible_v = _to_python(g.value(s, MKT.defeasible))
    defeasible = True if defeasible_v is None else bool(defeasible_v)

    defeats = tuple(
        _local_name(o) for o in g.objects(s, MKT.defeats)
    )

    source = _to_python(g.value(s, MKT.source)) or ""

    return cls(  # type: ignore[call-arg]
        norm_id=norm_id,
        applies_when=str(applies_when),
        target=str(target),
        priority=priority,
        valid_from=valid_from,
        valid_until=valid_until,
        defeasible=defeasible,
        defeats=defeats,
        source=str(source),
    )


# =============================================================================
# Resolver
# =============================================================================


@dataclass
class _Conflicto:
    """Conflicto detectado entre dos normas aplicables.

    Solo para uso interno del resolver durante la resolucion.
    """

    n1: Norm
    n2: Norm
    motivo: str


class DeonticResolver:
    """Evalua decisiones contra un catalogo de normas con resolucion defeasible.

    Inmutable post-construccion (la lista de normas no muta). Multiples
    instancias pueden coexistir (por ejemplo, una para normas globales y
    otra para normas de proveedores especificos).

    Args:
        normas: catalogo de normas. Se valida que no haya colision de
            norm_id (cada id debe ser unico).
        audit_path: ruta JSONL donde apendar cada evaluacion. None
            desactiva el audit trail.

    Raises:
        NormaInvalida: hay norm_id duplicados, predicados appliesWhen no
            registrados, o :defeats apunta a un norm_id inexistente en
            el catalogo (verificacion pre-flight: rompe en construccion,
            no en runtime de evaluar()).
    """

    def __init__(
        self,
        normas: Iterable[Norm],
        audit_path: Optional[Path] = None,
    ) -> None:
        self.normas: tuple[Norm, ...] = tuple(normas)
        self.audit_path: Optional[Path] = (
            Path(audit_path) if audit_path is not None else None
        )
        self._validate_pre_flight()

    @classmethod
    def from_ttl(
        cls,
        ttl_path: str | Path,
        audit_path: Optional[str | Path] = None,
    ) -> "DeonticResolver":
        """Construye un resolver cargando normas desde un Turtle."""
        normas = _parse_normas_ttl(Path(ttl_path))
        ap = Path(audit_path) if audit_path is not None else None
        return cls(normas, audit_path=ap)

    # -------------------------------------------------------------------------
    # Validaciones pre-flight (al construir)
    # -------------------------------------------------------------------------

    def _validate_pre_flight(self) -> None:
        ids = [n.norm_id for n in self.normas]
        dupes = {x for x in ids if ids.count(x) > 1}
        if dupes:
            raise NormaInvalida(f"norm_id duplicados en catalogo: {sorted(dupes)}")

        ids_set = set(ids)
        for n in self.normas:
            for d_id in n.defeats:
                if d_id not in ids_set:
                    raise NormaInvalida(
                        f"Norma {n.norm_id} declara :defeats {d_id} "
                        f"pero {d_id} no existe en el catalogo."
                    )
            # Verificar que el predicado existe en el registry
            try:
                get_predicate(n.applies_when)
            except KeyError as e:
                raise NormaInvalida(
                    f"Norma {n.norm_id}: predicado '{n.applies_when}' no "
                    f"esta registrado. Asegurate de importar el modulo "
                    f"que lo registra antes de instanciar el resolver."
                ) from e

    # -------------------------------------------------------------------------
    # API publica: evaluar
    # -------------------------------------------------------------------------

    def evaluar(
        self,
        decision_propuesta: Mapping[str, Any],
        contexto: Mapping[str, Any],
    ) -> EvaluacionDeontica:
        """Evalua una decision propuesta contra el catalogo.

        Args:
            decision_propuesta: dict con la decision a evaluar (campos como
                tipo, monto_usd, aprobacion_supervisor, etc. Ver docstring
                de predicados_marketplace.py).
            contexto: dict con el estado del mundo relevante (perecedero,
                sku_critico, proveedores_disponibles, etc.). Si incluye
                la key "now" (datetime), se usa como instante de
                evaluacion; sino se usa datetime.now(timezone.utc).

        Returns:
            EvaluacionDeontica inmutable con veredicto y razonamiento.

        Raises:
            UnresolvedDeonticConflict: dos normas aplicables tienen target
                compartido y modalidades en conflicto que no se pueden
                resolver por :defeats explicito ni prioridad numerica.
        """
        now_value = contexto.get("now")
        if isinstance(now_value, datetime):
            now = _ensure_aware(now_value)
            assert now is not None  # mypy / explicit
        else:
            now = datetime.now(timezone.utc)

        razonamiento: list[str] = [
            f"Evaluacion deontica en {now.isoformat()}",
            f"Catalogo: {len(self.normas)} normas cargadas.",
        ]

        # 1. Vigentes -----------------------------------------------------
        vigentes: list[Norm] = []
        no_vigentes: list[Norm] = []
        for n in self.normas:
            if n.is_valid_at(now):
                vigentes.append(n)
            else:
                no_vigentes.append(n)
        razonamiento.append(
            f"Paso 1 - vigencia: {len(vigentes)} vigentes, "
            f"{len(no_vigentes)} fuera de fecha."
        )
        if no_vigentes:
            razonamiento.append(
                f"  fuera de vigencia: {sorted(n.norm_id for n in no_vigentes)}"
            )

        # 2. Aplicables ---------------------------------------------------
        aplicables: list[Norm] = []
        no_aplicables: list[Norm] = []
        for n in vigentes:
            pred = get_predicate(n.applies_when)
            try:
                fired = pred(decision_propuesta, contexto)
            except Exception as e:
                razonamiento.append(
                    f"  ! predicado {n.applies_when} de {n.norm_id} "
                    f"levanto {type(e).__name__}: {e}. Tratado como no aplicable."
                )
                fired = False
            if fired:
                aplicables.append(n)
            else:
                no_aplicables.append(n)
        razonamiento.append(
            f"Paso 2 - aplicabilidad: {len(aplicables)} aplicables, "
            f"{len(no_aplicables)} silenciosas."
        )
        if aplicables:
            razonamiento.append(
                f"  aplicables: {sorted(n.norm_id for n in aplicables)}"
            )

        if not aplicables:
            razonamiento.append(
                "Paso 3 - sin normas aplicables: la decision es libre "
                "(ninguna norma del catalogo dice nada al respecto)."
            )
            evaluation = EvaluacionDeontica(
                permitida=True,
                bloqueada_por=(),
                obligaciones_pendientes=(),
                normas_aplicadas=(),
                normas_derrotadas=(),
                razonamiento=tuple(razonamiento),
                evaluated_at=now,
            )
            self._audit(decision_propuesta, contexto, evaluation)
            return evaluation

        # 3. Defeats explicitos ------------------------------------------
        derrotadas: dict[str, str] = {}
        ids_aplicables = {n.norm_id for n in aplicables}

        for n in aplicables:
            for d_id in n.defeats:
                if d_id not in ids_aplicables:
                    continue  # no aplicable, nada que derrotar
                if d_id in derrotadas:
                    continue
                derrotada = next(o for o in aplicables if o.norm_id == d_id)
                if not derrotada.defeasible:
                    raise UnresolvedDeonticConflict(
                        f"Norma {n.norm_id} declara :defeats sobre {d_id} "
                        f"pero {d_id} es defeasible=False (no derrotable)."
                    )
                derrotadas[d_id] = (
                    f":defeats explicito de {n.norm_id} (priority {n.priority})"
                )
        if derrotadas:
            razonamiento.append(
                f"Paso 3 - :defeats explicitos: derrotadas {sorted(derrotadas)}"
            )
        else:
            razonamiento.append("Paso 3 - sin :defeats explicitos aplicables.")

        # 4. Conflictos por target + resolucion por prioridad -------------
        no_derrotadas = [n for n in aplicables if n.norm_id not in derrotadas]
        conflictos = self._detectar_conflictos(no_derrotadas)

        for c in conflictos:
            n1, n2 = c.n1, c.n2
            # Si alguna ya quedo derrotada por defeats en este loop, skip.
            if n1.norm_id in derrotadas or n2.norm_id in derrotadas:
                continue
            ganador, perdedor, motivo = self._resolver_por_prioridad(n1, n2)
            if perdedor is None:
                # Empate sin :defeats explicito
                raise UnresolvedDeonticConflict(
                    f"Conflicto {c.motivo} entre {n1.norm_id} (prio {n1.priority}) "
                    f"y {n2.norm_id} (prio {n2.priority}): empate de prioridad "
                    f"sin :defeats explicito. Resolveer agregando :defeats "
                    f"o cambiando prioridades."
                )
            if not perdedor.defeasible:
                raise UnresolvedDeonticConflict(
                    f"Conflicto {c.motivo} entre {n1.norm_id} y {n2.norm_id}: "
                    f"{perdedor.norm_id} (prio {perdedor.priority}) seria "
                    f"derrotada por {ganador.norm_id} (prio {ganador.priority}) "
                    f"pero es defeasible=False."
                )
            derrotadas[perdedor.norm_id] = motivo

        if any(c for c in conflictos):
            razonamiento.append(
                f"Paso 4 - conflictos por target: {len(conflictos)} pares "
                f"detectados, resueltos por prioridad."
            )
        else:
            razonamiento.append("Paso 4 - sin conflictos por target.")

        # 5. Veredicto ----------------------------------------------------
        aplicadas_finales = [
            n for n in aplicables if n.norm_id not in derrotadas
        ]

        bloqueada_por = tuple(
            n.norm_id
            for n in aplicadas_finales
            if n.modality == Modality.PROHIBITION
        )
        obligaciones_pendientes = tuple(
            n.norm_id
            for n in aplicadas_finales
            if n.modality == Modality.OBLIGATION
        )
        permitida = not bloqueada_por and not obligaciones_pendientes

        razonamiento.append(
            f"Paso 5 - veredicto: permitida={permitida}, "
            f"bloqueada_por={list(bloqueada_por)}, "
            f"obligaciones_pendientes={list(obligaciones_pendientes)}."
        )

        evaluation = EvaluacionDeontica(
            permitida=permitida,
            bloqueada_por=bloqueada_por,
            obligaciones_pendientes=obligaciones_pendientes,
            normas_aplicadas=tuple(n.norm_id for n in aplicadas_finales),
            normas_derrotadas=tuple(sorted(derrotadas.items())),
            razonamiento=tuple(razonamiento),
            evaluated_at=now,
        )
        self._audit(decision_propuesta, contexto, evaluation)
        return evaluation

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    @staticmethod
    def _detectar_conflictos(normas: list[Norm]) -> list[_Conflicto]:
        """Pares (n1, n2) con mismo target y modalidades incompatibles.

        Pares incompatibles:
            - O vs F (Obligation vs Prohibition)
            - F vs P (Prohibition vs Permission)

        O vs P sobre mismo target NO es conflicto (P es congruente con O).
        Dos modalidades iguales NO es conflicto (refuerzan).
        """
        conflictos: list[_Conflicto] = []
        incompatibles = (
            {Modality.OBLIGATION, Modality.PROHIBITION},
            {Modality.PROHIBITION, Modality.PERMISSION},
        )
        for n1, n2 in itertools.combinations(normas, 2):
            if n1.target != n2.target:
                continue
            mods = {n1.modality, n2.modality}
            if mods in incompatibles:
                if mods == {Modality.OBLIGATION, Modality.PROHIBITION}:
                    motivo = "O vs F"
                else:
                    motivo = "F vs P"
                conflictos.append(_Conflicto(n1=n1, n2=n2, motivo=motivo))
        return conflictos

    @staticmethod
    def _resolver_por_prioridad(
        n1: Norm, n2: Norm
    ) -> tuple[Norm, Optional[Norm], str]:
        """Compara prioridades. Devuelve (ganador, perdedor, motivo).

        Si empate, perdedor=None (caller decide raise).
        """
        if n1.priority > n2.priority:
            return (
                n1,
                n2,
                f"derrotada por mayor prioridad de {n1.norm_id} "
                f"({n1.priority} > {n2.priority})",
            )
        if n2.priority > n1.priority:
            return (
                n2,
                n1,
                f"derrotada por mayor prioridad de {n2.norm_id} "
                f"({n2.priority} > {n1.priority})",
            )
        return (n1, None, "empate")

    # -------------------------------------------------------------------------
    # Audit trail JSONL
    # -------------------------------------------------------------------------

    def _audit(
        self,
        decision: Mapping[str, Any],
        contexto: Mapping[str, Any],
        evaluation: EvaluacionDeontica,
    ) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": _safe_for_json(decision),
            "contexto": _safe_for_json(contexto),
            "result": evaluation.to_dict(),
        }
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(line, ensure_ascii=False, default=str) + "\n"
            )


def _safe_for_json(value: Any) -> Any:
    """Convierte recursivamente a tipos JSON-serializables."""
    if isinstance(value, Mapping):
        return {str(k): _safe_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_for_json(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
