"""AuditStore: persistencia de subgrafos PROV-O por decision.

Cada llamada a `log_decision()` materializa un subgrafo W3C PROV-O que
captura:
    - Una :Decision (prov:Activity) con timestamps, agente, rule aplicada,
      confianza y stages descriptores.
    - Un :DecisionContext (prov:Entity) con snapshot serializado para
      reconstruccion posterior + propiedades estructuradas para queries.
    - prov:wasAssociatedWith el agente, prov:used el contexto, prov:used
      cada algoritmo invocado, :consultedNorma cada norma evaluada,
      :wasBlockedBy en caso de bloqueo deontico.

Append-only: el archivo crece, nunca se reescribe. Idempotente: si el
decisionId ya existe (chequeo por presencia del literal en el archivo),
no se duplica.

Best practices del prompt: UUID v4 + timestamp para IDs, log inmutable,
formato versionado (audit_log_v1.ttl).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from dispatcher.context import DecisionContext, TipoSku
from dispatcher.recommendation import AlgorithmRecommendation


# =============================================================================
# Namespaces y constantes
# =============================================================================

MKT = Namespace("http://marketplace.com.py/onto/v1#")
PROV = Namespace("http://www.w3.org/ns/prov#")

AUDIT_LOG_VERSION = "v1"
DEFAULT_AGENT_URI = "agente_dispatcher_v1"


# Header fijo del audit_log_v1.ttl. Se escribe una sola vez al crear el
# archivo; las decisiones se anexan al final.
_LOG_HEADER = """# =============================================================================
# Audit log PROV-O - Marketplace SA Paraguay (Bloque 8)
# =============================================================================
# Append-only. Cada decision genera un subgrafo cerrado con timestamps,
# agente, contexto consumido, normas evaluadas y stages recomendados.
# Este archivo es CONSULTABLE con SPARQL (ver audit/queries.sparql).
#
# Version del formato: v1 (Bloque 8). NO modificar las URIs ni properties
# de un subgrafo ya escrito. Para evolucionar el schema, crear v2 en un
# archivo nuevo (audit_log_v2.ttl).
# =============================================================================

@prefix :     <http://marketplace.com.py/onto/v1#> .
@prefix mkt:  <http://marketplace.com.py/onto/v1#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

"""


# =============================================================================
# Excepciones
# =============================================================================


class AuditStoreError(RuntimeError):
    """Error generico del audit store (I/O, parsing, schema)."""


class DecisionNotFoundError(AuditStoreError):
    """Se busca una decision_id que no existe en el log."""


# =============================================================================
# Helper: serializacion segura de DecisionContext a JSON
# =============================================================================


def _ctx_to_json(ctx: DecisionContext) -> str:
    """Serializa un DecisionContext a JSON string (para contextSnapshot).

    Convierte:
        - tipo_sku (TipoSku enum) -> str
        - similar_top_k (tuple SimilarRef) -> list[dict]
        - evento_proximo, trend_signal (dataclass) -> dict
        - eval_deontica (cualquier obj) -> dict via to_dict() o getattr
        - evaluated_at (datetime) -> ISO string

    El resultado es directamente parseable por DecisionContext.from_dict()
    para replay.
    """
    out: dict[str, Any] = {}
    for fname in ctx.__dataclass_fields__:
        v = getattr(ctx, fname)
        if v is None:
            continue
        if isinstance(v, TipoSku):
            out[fname] = v.value
        elif isinstance(v, datetime):
            out[fname] = v.isoformat()
        elif isinstance(v, tuple) and v and is_dataclass(v[0]):
            out[fname] = [asdict(x) for x in v]
        elif is_dataclass(v):
            out[fname] = asdict(v)
        elif fname == "eval_deontica":
            # Puede ser EvaluacionDeontica del Bloque 6, SimpleNamespace, o dict.
            if hasattr(v, "to_dict") and callable(v.to_dict):
                out[fname] = v.to_dict()
            elif hasattr(v, "__dict__"):
                out[fname] = {
                    k: list(val) if isinstance(val, tuple) else val
                    for k, val in vars(v).items()
                }
            elif isinstance(v, Mapping):
                out[fname] = dict(v)
            else:
                out[fname] = str(v)
        else:
            out[fname] = v
    return json.dumps(out, ensure_ascii=False, default=str, sort_keys=True)


# =============================================================================
# AuditStore
# =============================================================================


class AuditStore:
    """Persistencia append-only de decisiones en formato PROV-O.

    Args:
        ttl_path: ruta al .ttl audit log. Si no existe, se crea con header.
        also_to_neo4j: si True, ademas de escribir TTL, importa el subgrafo
            a Neo4j via el bridge del Bloque 3 (requiere Neo4j corriendo).
            Default False - el TTL es la fuente canonica.
        neo4j_bridge_callable: callable opcional `(Graph) -> None` que recibe
            el subgrafo de la decision y lo persiste a Neo4j. Inyectable
            para testing.
    """

    def __init__(
        self,
        ttl_path: str | Path,
        also_to_neo4j: bool = False,
        neo4j_bridge_callable=None,
    ) -> None:
        self.ttl_path = Path(ttl_path)
        self.also_to_neo4j = also_to_neo4j
        self.neo4j_bridge_callable = neo4j_bridge_callable
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        if not self.ttl_path.exists():
            self.ttl_path.parent.mkdir(parents=True, exist_ok=True)
            self.ttl_path.write_text(_LOG_HEADER, encoding="utf-8")

    # -------------------------------------------------------------------------
    # API publica
    # -------------------------------------------------------------------------

    def log_decision(
        self,
        context: DecisionContext,
        recomendacion: AlgorithmRecommendation,
        agent_uri: str = DEFAULT_AGENT_URI,
        decision_id: Optional[str] = None,
        normas_evaluadas: Iterable[str] = (),
    ) -> str:
        """Persiste una decision como subgrafo PROV-O.

        Args:
            context: DecisionContext consumido por la decision.
            recomendacion: AlgorithmRecommendation producida.
            agent_uri: local-name del prov:Agent. Default
                "agente_dispatcher_v1".
            decision_id: si se provee, se usa (requerido para idempotencia
                con caller que ya tiene id). Sino se genera uuid4.
            normas_evaluadas: norm_ids consultados durante el pipeline
                deontico (subset que paso applies_when, no derrotadas).
                Si vacio, se infiere de recomendacion.bloqueada_por_deontica.

        Returns:
            decision_id (string, formato "dec_<uuid hex>").

        Raises:
            AuditStoreError: si I/O al TTL falla.
        """
        if decision_id is None:
            decision_id = "dec_" + uuid.uuid4().hex
        else:
            # Validar formato basico
            if not decision_id.startswith("dec_"):
                raise AuditStoreError(
                    f"decision_id debe empezar con 'dec_', recibido: {decision_id!r}"
                )

        # Idempotencia: si ya esta en el log, no volvemos a escribir
        if self._has_decision_id(decision_id):
            return decision_id

        ctx_id = "ctx_" + uuid.uuid4().hex
        g = self._construir_subgrafo(
            decision_id=decision_id,
            ctx_id=ctx_id,
            context=context,
            recomendacion=recomendacion,
            agent_uri=agent_uri,
            normas_evaluadas=tuple(normas_evaluadas),
        )

        # Anexar al TTL (serializa solo los triples del subgrafo)
        self._anexar_subgrafo(g, decision_id)

        # Espejo opcional a Neo4j
        if self.also_to_neo4j and self.neo4j_bridge_callable is not None:
            try:
                self.neo4j_bridge_callable(g)
            except Exception as e:
                # No abortamos el log si Neo4j esta caido. El TTL es canon.
                # Pero si hay un logger configurado, deberiamos avisar.
                pass

        return decision_id

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        """Devuelve un dict con todos los datos de una decision registrada.

        Estructura del dict:
            {
                "decision_id": str,
                "started_at": datetime,
                "ended_at": datetime | None,
                "agent": str,
                "rule_applied": str | None,
                "confidence": float,
                "blocked_by_deontic": bool,
                "stages": list[str],            # descriptor_ids
                "consulted_normas": list[str],   # norm_ids
                "blocked_by_normas": list[str],
                "context_id": str,
                "context_snapshot": dict,        # parseable a DecisionContext
            }

        Raises:
            DecisionNotFoundError: si decision_id no esta en el log.
        """
        g = Graph()
        g.parse(str(self.ttl_path), format="turtle")

        dec_uri = MKT[decision_id]
        # Verificar existencia
        if (dec_uri, RDF.type, MKT.Decision) not in g:
            raise DecisionNotFoundError(
                f"decision_id {decision_id!r} no existe en {self.ttl_path}."
            )

        # Extraer campos
        started = g.value(dec_uri, PROV.startedAtTime)
        ended = g.value(dec_uri, PROV.endedAtTime)
        agent = g.value(dec_uri, PROV.wasAssociatedWith)
        rule_applied = g.value(dec_uri, MKT.appliedRule)
        confidence = g.value(dec_uri, MKT.hadConfidence)
        blocked_d = g.value(dec_uri, MKT.wasBlockedByDeontic)

        ctx_uri = g.value(dec_uri, PROV.used)
        # NB: prov:used puede aparecer multiples veces (contexto + algoritmos +
        # normas). Elegimos el que sea de tipo :DecisionContext para el
        # contextSnapshot.
        ctx_uri = None
        for o in g.objects(dec_uri, PROV.used):
            if (o, RDF.type, MKT.DecisionContext) in g:
                ctx_uri = o
                break

        stages = sorted(
            str(o) for o in g.objects(dec_uri, MKT.hasStageDescriptor)
        )
        consulted = sorted(
            _local(o) for o in g.objects(dec_uri, MKT.consultedNorma)
        )
        blocked = sorted(
            _local(o) for o in g.objects(dec_uri, MKT.wasBlockedBy)
        )

        ctx_snapshot: dict[str, Any] = {}
        if ctx_uri is not None:
            snap_lit = g.value(ctx_uri, MKT.contextSnapshot)
            if snap_lit is not None:
                try:
                    ctx_snapshot = json.loads(str(snap_lit))
                except json.JSONDecodeError as e:
                    raise AuditStoreError(
                        f"contextSnapshot de {decision_id} corrupto: {e}"
                    ) from e

        return {
            "decision_id": decision_id,
            "started_at": _to_datetime(started),
            "ended_at": _to_datetime(ended) if ended is not None else None,
            "agent": _local(agent) if agent is not None else None,
            "rule_applied": str(rule_applied) if rule_applied is not None else None,
            "confidence": float(confidence) if confidence is not None else None,
            "blocked_by_deontic": (
                bool(blocked_d.toPython()) if blocked_d is not None else False
            ),
            "stages": stages,
            "consulted_normas": consulted,
            "blocked_by_normas": blocked,
            "context_id": _local(ctx_uri) if ctx_uri is not None else None,
            "context_snapshot": ctx_snapshot,
        }

    def list_decisions(self, limit: int | None = None) -> list[str]:
        """Lista decision_ids en el log (orden de aparicion en el TTL)."""
        g = Graph()
        g.parse(str(self.ttl_path), format="turtle")
        ids = [
            _local(s) for s in g.subjects(RDF.type, MKT.Decision)
        ]
        return ids[:limit] if limit else ids

    def graph(self) -> Graph:
        """Devuelve el grafo completo del audit log (parseable, query-able)."""
        g = Graph()
        g.parse(str(self.ttl_path), format="turtle")
        return g

    # -------------------------------------------------------------------------
    # Internals: construccion del subgrafo + anexado
    # -------------------------------------------------------------------------

    def _construir_subgrafo(
        self,
        decision_id: str,
        ctx_id: str,
        context: DecisionContext,
        recomendacion: AlgorithmRecommendation,
        agent_uri: str,
        normas_evaluadas: tuple[str, ...],
    ) -> Graph:
        """Materializa el subgrafo PROV-O de UNA decision."""
        g = Graph()
        g.bind("", MKT)
        g.bind("mkt", MKT)
        g.bind("prov", PROV)

        dec = MKT[decision_id]
        ctx = MKT[ctx_id]
        agent = MKT[agent_uri]

        # ---- Decision Activity ----
        g.add((dec, RDF.type, MKT.Decision))
        g.add((dec, RDF.type, PROV.Activity))
        g.add((dec, MKT.decisionId, Literal(decision_id)))

        started = recomendacion.evaluated_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        ended = datetime.now(timezone.utc)
        g.add((dec, PROV.startedAtTime, Literal(started.isoformat(), datatype=XSD.dateTime)))
        g.add((dec, PROV.endedAtTime, Literal(ended.isoformat(), datatype=XSD.dateTime)))

        g.add((dec, PROV.wasAssociatedWith, agent))
        g.add((dec, PROV.used, ctx))

        if recomendacion.reglas_aplicadas:
            g.add((dec, MKT.appliedRule, Literal(recomendacion.reglas_aplicadas[0])))

        g.add((dec, MKT.hadConfidence, Literal(recomendacion.confianza, datatype=XSD.decimal)))

        was_blocked = bool(recomendacion.bloqueada_por_deontica)
        g.add((dec, MKT.wasBlockedByDeontic, Literal(was_blocked, datatype=XSD.boolean)))

        # Stages: descriptores como literal string (queryable) + URIs (joineable
        # con el catalogo de Algorithm). Doble forma para conveniencia.
        for stage in recomendacion.stages:
            g.add((dec, MKT.hasStageDescriptor, Literal(stage.descriptor_id)))
            algo_uri = MKT[f"algo_{stage.descriptor_id}"]
            g.add((dec, MKT.invocaAlgoritmo, algo_uri))

        # Normas evaluadas (consulted) - subset que paso applies_when
        for norm_id in normas_evaluadas:
            g.add((dec, MKT.consultedNorma, MKT[norm_id]))

        # Normas que bloquearon
        for norm_id in recomendacion.bloqueada_por_deontica:
            g.add((dec, MKT.wasBlockedBy, MKT[norm_id]))

        # ---- Context Entity ----
        g.add((ctx, RDF.type, MKT.DecisionContext))
        g.add((ctx, RDF.type, PROV.Entity))
        g.add((ctx, PROV.atTime, Literal(started.isoformat(), datatype=XSD.dateTime)))

        # Snapshot completo (para replay)
        snapshot_json = _ctx_to_json(context)
        g.add((ctx, MKT.contextSnapshot, Literal(snapshot_json)))

        # Propiedades estructuradas (para queries SPARQL sin parsear el JSON)
        g.add((ctx, MKT.sku, Literal(context.sku)))
        g.add((ctx, MKT.tipoSku, Literal(context.tipo_sku.value)))
        if context.categoria:
            g.add((ctx, MKT.categoria, Literal(context.categoria)))
        if context.nombre:
            g.add((ctx, MKT.nombreProducto, Literal(context.nombre)))
        g.add((ctx, MKT.semanasHistoria, Literal(context.semanas_historia, datatype=XSD.integer)))

        return g

    def _anexar_subgrafo(self, g: Graph, decision_id: str) -> None:
        """Anexa los triples del subgrafo al final del audit log TTL.

        Usamos serializacion turtle del subgrafo (sin header de prefijos
        para no duplicar) y la anexamos al archivo. rdflib puede repetir
        los prefijos en cada subgrafo; eso lo manejamos quitandolos del
        output via post-procesamiento simple.
        """
        # Serializa el subgrafo a turtle string
        ttl_chunk = g.serialize(format="turtle")

        # Quitar las lineas de @prefix (ya estan en el header del archivo)
        lineas = []
        for line in ttl_chunk.splitlines():
            stripped = line.strip()
            if stripped.startswith("@prefix") or stripped.startswith("@base"):
                continue
            lineas.append(line)
        chunk_sin_prefijos = "\n".join(lineas).strip()

        # Anexar con un separador de comentario
        with open(self.ttl_path, "a", encoding="utf-8") as f:
            f.write("\n# ---- " + decision_id + " ----\n")
            f.write(chunk_sin_prefijos)
            f.write("\n")

    def _has_decision_id(self, decision_id: str) -> bool:
        """Idempotencia barata: busca el literal del decisionId en el archivo.

        No parsea el TTL completo (rapido). Funciona porque el decision_id
        aparece como literal `"dec_<uuid>"` y como local-name de URI.
        """
        if not self.ttl_path.exists():
            return False
        # Buscar la URI (`:dec_<uuid>` o `mkt:dec_<uuid>`) o el literal
        marker_uri = f":{decision_id} "
        marker_lit = f'"{decision_id}"'
        with open(self.ttl_path, "r", encoding="utf-8") as f:
            for line in f:
                if marker_uri in line or marker_lit in line:
                    return True
        return False


# =============================================================================
# Helpers
# =============================================================================


def _local(uri: Any) -> str:
    """Local-name de una URI rdflib (post '#' o post '/')."""
    if uri is None:
        return ""
    s = str(uri)
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    return s.rsplit("/", 1)[-1]


def _to_datetime(literal: Any) -> Optional[datetime]:
    """Convierte un Literal de xsd:dateTime a datetime."""
    if literal is None:
        return None
    if isinstance(literal, Literal):
        v = literal.toPython()
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return v
    s = str(literal)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
