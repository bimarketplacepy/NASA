"""Validador SHACL para TrendSignal alineado con la spec del ingeniero (v2).

Plain literals (sin datatype) para strings — RDF 1.1 los trata como xsd:string.
sh:in usa plain literals para compatibilidad con pyshacl en Python < 3.12.

Author: Proyecto NASA - Tarea 2 (Mateo)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from schemas.tendencias import TrendSignal


MKT_NS_URI = "http://marketplace.com.py/onto/v1#"
MKT = Namespace(MKT_NS_URI)


def trend_uri(trend_id: str) -> URIRef:
    return URIRef(f"{MKT_NS_URI}TrendSignal/{trend_id}")


_INLINE_SHAPES_TTL = """
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix mkt: <http://marketplace.com.py/onto/v1#> .

mkt:TrendSignal a rdfs:Class ; rdfs:label "Senal de Tendencia"@es .
mkt:descripcion a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:string .
mkt:fuente a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:string .
mkt:fechaDeteccion a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:dateTime .
mkt:velocidadCrecimiento a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:float .
mkt:confianzaExtraccion a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:float .
mkt:palabraClave a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:string .
mkt:similarA a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:string .
mkt:provisional a rdf:Property ; rdfs:domain mkt:TrendSignal ; rdfs:range xsd:boolean .

mkt:TrendSignalShape a sh:NodeShape ;
    sh:targetClass mkt:TrendSignal ;
    sh:property [
        sh:path mkt:descripcion ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:string ; sh:minLength 10 ; sh:maxLength 500 ;
        sh:message "descripcion debe tener entre 10 y 500 caracteres"@es ;
    ] , [
        sh:path mkt:fuente ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:in ( "TIKTOK" "INSTAGRAM" "PINTEREST" "GOOGLE_TRENDS" "OTHER" ) ;
        sh:message "fuente debe ser TIKTOK, INSTAGRAM, PINTEREST, GOOGLE_TRENDS u OTHER"@es ;
    ] , [
        sh:path mkt:fechaDeteccion ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:dateTime ;
        sh:message "fechaDeteccion debe estar presente y ser xsd:dateTime"@es ;
    ] , [
        sh:path mkt:velocidadCrecimiento ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:float ; sh:minInclusive 0.0 ; sh:maxInclusive 1000.0 ;
        sh:message "velocidadCrecimiento debe estar entre 0 y 1000"@es ;
    ] , [
        sh:path mkt:confianzaExtraccion ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:float ; sh:minInclusive 0.0 ; sh:maxInclusive 1.0 ;
        sh:message "confianzaExtraccion debe estar entre 0 y 1"@es ;
    ] , [
        sh:path mkt:provisional ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:boolean ;
        sh:message "provisional debe estar presente como xsd:boolean"@es ;
    ] .
"""

_shapes_cache: dict[str, Graph] = {}


def _load_shapes(shapes_path: str | Path | None) -> Graph:
    cache_key = str(shapes_path) if shapes_path else "__inline__"
    cached = _shapes_cache.get(cache_key)
    if cached is not None:
        return cached
    g = Graph()
    if shapes_path is not None:
        path_obj = Path(shapes_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"shapes.ttl no encontrado en {path_obj}")
        g.parse(path_obj, format="turtle")
        logger.info(f"Shapes SHACL cargados desde {path_obj}")
    else:
        g.parse(data=_INLINE_SHAPES_TTL, format="turtle")
        logger.debug("Shapes SHACL cargados desde inline default")
    _shapes_cache[cache_key] = g
    return g


def trend_a_rdf(ts: TrendSignal) -> Graph:
    """Convierte TrendSignal a RDF. Strings como plain literals (RDF 1.1 = xsd:string)."""
    g = Graph()
    g.bind("mkt", MKT)
    g.bind("xsd", XSD)
    uri = trend_uri(ts.trend_id)
    g.add((uri, RDF.type, MKT.TrendSignal))
    g.add((uri, MKT.descripcion, Literal(str(ts.descripcion))))
    g.add((uri, MKT.fuente, Literal(str(ts.fuente))))
    g.add((uri, MKT.fechaDeteccion, Literal(ts.fecha_deteccion, datatype=XSD.dateTime)))
    g.add((uri, MKT.velocidadCrecimiento, Literal(float(ts.velocidad_crecimiento), datatype=XSD.float)))
    g.add((uri, MKT.confianzaExtraccion, Literal(float(ts.confianza_extraccion), datatype=XSD.float)))
    g.add((uri, MKT.provisional, Literal(bool(ts.provisional), datatype=XSD.boolean)))
    for kw in ts.palabras_clave:
        if kw:
            g.add((uri, MKT.palabraClave, Literal(str(kw))))
    for ps in ts.productos_existentes_similares:
        g.add((uri, MKT.similarA, Literal(str(ps.sku))))
    return g


def validar_trend_con_shacl(
    ts: TrendSignal,
    shapes_path: str | Path | None = None,
) -> tuple[bool, list[str]]:
    """Valida TrendSignal contra shapes SHACL. Firma requerida por spec del ingeniero."""
    try:
        data_graph = trend_a_rdf(ts)
        shapes_graph = _load_shapes(shapes_path)
        conforms, _, results_text = validate(
            data_graph=data_graph,
            shacl_graph=shapes_graph,
            inference="rdfs",
            abort_on_first=False,
            meta_shacl=False,
            debug=False,
        )
        if conforms:
            logger.debug(f"TrendSignal {ts.trend_id} OK SHACL")
            return True, []
        violations = _parse_violations(results_text)
        logger.warning(f"TrendSignal {ts.trend_id} violacion SHACL: {len(violations)} reglas")
        return False, violations
    except Exception as exc:
        logger.error(f"Error en validacion SHACL: {exc}")
        return False, [f"Error interno de validacion: {exc}"]


def _parse_violations(results_text: str) -> list[str]:
    violations: list[str] = []
    for line in results_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Message:"):
            mensaje = stripped[len("Message:"):].strip()
            if mensaje and mensaje not in violations:
                violations.append(mensaje)
    if not violations:
        snippet = results_text.strip()
        if snippet:
            violations.append(snippet[:500])
    return violations


class SHACLValidator:
    """Adaptador legacy: valida desde dicts crudos del LLM/scraper.

    Expone validar_trend_json y validar_batch para compatibilidad.
    Args:
        shapes_path: Ruta al shapes.ttl externo de Abi. None = inline default.
    """

    def __init__(self, shapes_path: str | Path | None = None) -> None:
        self.shapes_path = shapes_path
        _load_shapes(shapes_path)

    def validar_trend_json(self, trend_dict: dict[str, Any]) -> tuple[bool, str]:
        try:
            ts = self._dict_a_trend_signal(trend_dict)
        except (ValueError, KeyError, TypeError) as exc:
            return False, f"No se pudo construir TrendSignal: {exc}"
        conforms, violations = validar_trend_con_shacl(ts, self.shapes_path)
        if conforms:
            return True, "OK"
        return False, "VIOLACIONES SHACL:\n" + "\n".join(f"  - {v}" for v in violations)

    def validar_batch(
        self,
        trends_list: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
        validas: list[dict[str, Any]] = []
        invalidas: list[tuple[dict[str, Any], str]] = []
        for trend in trends_list:
            ok, reporte = self.validar_trend_json(trend)
            if ok:
                validas.append(trend)
            else:
                invalidas.append((trend, reporte))
        logger.info(f"Validacion batch: {len(validas)} OK, {len(invalidas)} rechazadas")
        return validas, invalidas

    @staticmethod
    def _dict_a_trend_signal(trend_dict: dict[str, Any]) -> TrendSignal:
        from schemas.tendencias import ProductoSimilar

        ts_raw = trend_dict.get("timestamp") or trend_dict.get("fecha_deteccion")
        if isinstance(ts_raw, datetime):
            fecha_deteccion = ts_raw
        elif isinstance(ts_raw, str) and ts_raw.strip():
            fecha_deteccion = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            fecha_deteccion = datetime.utcnow()

        productos_raw = trend_dict.get("productos_existentes_similares", []) or []
        productos: list[ProductoSimilar] = []
        for item in productos_raw:
            if isinstance(item, ProductoSimilar):
                productos.append(item)
            elif isinstance(item, dict):
                productos.append(ProductoSimilar(**item))
            else:
                productos.append(ProductoSimilar(
                    sku=str(item), score=0.0, nombre=str(item),
                    categoria="DESCONOCIDA", precio_referencia=0.0,
                ))

        descripcion = str(trend_dict.get("descripcion", "")).strip()
        trend_id = trend_dict.get("trend_id") or f"trend_{int(fecha_deteccion.timestamp())}"

        return TrendSignal(
            trend_id=str(trend_id),
            descripcion=descripcion,
            palabras_clave=list(trend_dict.get("palabras_clave", []) or []),
            fuente=str(trend_dict.get("fuente", "")).strip(),
            fecha_deteccion=fecha_deteccion,
            metadata_fuente=dict(trend_dict.get("metadata_fuente", {}) or {}),
            velocidad_crecimiento=float(trend_dict.get("velocidad_crecimiento", 0.0)),
            confianza_extraccion=float(trend_dict.get("confianza_extraccion", 0.0)),
            productos_existentes_similares=productos,
            validado_shacl=False,
            provisional=True,
        )
