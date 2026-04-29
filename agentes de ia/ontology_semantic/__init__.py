"""ontology_semantic — Capa semantica decisional (Tarea 1 v2).

Contiene:
- marketplace.ttl: TBox en Turtle (single source of truth humano).
- marketplace.owl: TBox en RDF/XML (build artifact, generado por build.py).
- build.py: convierte .ttl -> .owl con rdflib.
- load_check.py: valida la carga con owlready2 e imprime un resumen.
- marketplace.owl.md: justificacion de cada clase y axiomas.
- bridge.py: API Neo4j <-> RDF (Bloque 3).
- reasoner.py: razonador HermiT + persistencia inferencias (Bloque 4).
- similarity/: motor de similaridad multidimensional (Bloque 5).
- client_v2.py: OntologyClientV2 con productos_similares (Bloque 5).

Esta carpeta NO toca ontology/ (v1 con Neo4j cliente). Es una capa nueva
encima de la v1.
"""

from ontology_semantic.client_v2 import OntologyClientV2, QUERY_TEXT_SKU

__all__ = ["OntologyClientV2", "QUERY_TEXT_SKU"]
