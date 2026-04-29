"""Bisecciona qué propiedad literal especifica rompe HermiT.

Empieza con ABox solo rdf:type (sabemos que es CONSISTENT) y agrega una
propiedad a la vez. La que dispare INCONSISTENT al agregarla es la culpable.
"""
import os
import subprocess
from pathlib import Path

import owlready2
import rdflib

OWL = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
NS = "http://marketplace.com.py/onto/v1#"


def _run(g, label):
    tmp = Path(f"data/_dbgp_{label}.nt")
    g.serialize(str(tmp), format="nt")
    hermit_dir = Path(owlready2.__file__).parent / "hermit"
    classpath = f"{hermit_dir}{os.pathsep}{hermit_dir}/HermiT.jar"
    cmd = ["java", "-Xmx2000M", "-cp", classpath,
           "org.semanticweb.HermiT.cli.CommandLine",
           "-c", "-I", tmp.resolve().as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return "INCONSISTENT" if "Inconsistent" in (r.stderr or "") else "OK"


def main():
    tbox = rdflib.Graph()
    tbox.parse("ontology_semantic/marketplace.owl", format="nt")
    abox_full = rdflib.Graph()
    abox_full.parse("data/snapshot_subset10.ttl", format="turtle")

    # 1. Base: TBox + ABox solo rdf:type. Sabemos que es OK.
    base = rdflib.Graph()
    for t in tbox: base.add(t)
    for s, p, o in abox_full:
        if str(p) == str(rdflib.RDF.type):
            base.add((s, p, o))
    print(f"Base (solo rdf:type): {_run(base, 'base')}")

    # 2. Probar agregando UNA propiedad a la vez
    # Lista de propiedades literales declaradas en TBox + el .uri de migration
    properties = [
        "sku", "enStock", "cantidadStock", "perecedero", "altaRotacion",
        "velocidad", "tieneHistorial", "esExterior", "pais",
        "fechaUltimaCompra",
    ]
    # Tambien las URIs no declaradas
    extras = [
        "uri", "nombre", "nombre_corto", "codigo_barras", "precio_costo",
        "precio_venta_actual", "pais_origen", "unidad", "fecha_alta",
        "fecha_ultima_venta", "id", "ruc", "email", "telefono",
    ]

    print()
    print(f"{'Property agregada':30s} {'Resultado':15s}")
    print("-" * 50)
    for prop in properties + extras:
        g = rdflib.Graph()
        for t in base: g.add(t)
        prop_uri = rdflib.URIRef(NS + prop)
        for s, p, o in abox_full.triples((None, prop_uri, None)):
            g.add((s, p, o))
        status = _run(g, f"add_{prop}")
        marker = "<-- BUG" if status == "INCONSISTENT" else ""
        print(f"{prop:30s} {status:15s} {marker}")


if __name__ == "__main__":
    main()
