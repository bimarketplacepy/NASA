"""Debug avanzado: probar TBox sin todos los axiomas derivativos."""
import os
import subprocess
from pathlib import Path

import owlready2
import rdflib

OWL = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
NS = "http://marketplace.com.py/onto/v1#"


def _strip_eq(g, class_name):
    cls = rdflib.URIRef(NS + class_name)
    for s, p, o in list(g.triples((cls, OWL.equivalentClass, None))):
        g.remove((s, p, o))
        if isinstance(o, rdflib.BNode):
            for t in list(g.triples((o, None, None))):
                g.remove(t)


def _strip_all_eq(g):
    for cls_name in ["ProductoPerecedero", "ProductoAltaRotacion",
                     "ProductoCritico", "ProductoColdStart",
                     "ProveedorExterior", "ProveedorLocal"]:
        _strip_eq(g, cls_name)


def _strip_disjoint(g, a, b):
    g.remove((rdflib.URIRef(NS + a), OWL.disjointWith, rdflib.URIRef(NS + b)))


def _run_hermit(g, label):
    tmp = Path(f"data/_dbg2_{label}.nt")
    g.serialize(str(tmp), format="nt")
    hermit_dir = Path(owlready2.__file__).parent / "hermit"
    classpath = f"{hermit_dir}{os.pathsep}{hermit_dir}/HermiT.jar"
    cmd = ["java", "-Xmx2000M", "-cp", classpath,
           "org.semanticweb.HermiT.cli.CommandLine",
           "-c", "-I", tmp.resolve().as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True)
    inc = "Inconsistent" in (r.stderr or "")
    return "INCONSISTENT" if inc else "OK", r.stderr[-300:] if inc else ""


def main():
    tbox_full = rdflib.Graph()
    tbox_full.parse("ontology_semantic/marketplace.owl", format="nt")
    abox = rdflib.Graph()
    abox.parse("data/snapshot_subset10.ttl", format="turtle")

    tests = []

    # 1. TBox sin TODOS los equivalentClass del Bloque 4
    g = rdflib.Graph()
    for t in tbox_full: g.add(t)
    _strip_all_eq(g)
    for t in abox: g.add(t)
    tests.append(("sin_todos_los_eq", g))

    # 2. TBox sin TODAS las disjointness
    g = rdflib.Graph()
    for t in tbox_full: g.add(t)
    _strip_disjoint(g, "Producto", "Proveedor")
    _strip_disjoint(g, "Decision", "Algorithm")
    _strip_disjoint(g, "ProveedorLocal", "ProveedorExterior")
    for t in abox: g.add(t)
    tests.append(("sin_todas_disjointness", g))

    # 3. TBox sin equivalentClass + sin disjointness
    g = rdflib.Graph()
    for t in tbox_full: g.add(t)
    _strip_all_eq(g)
    _strip_disjoint(g, "Producto", "Proveedor")
    _strip_disjoint(g, "Decision", "Algorithm")
    _strip_disjoint(g, "ProveedorLocal", "ProveedorExterior")
    for t in abox: g.add(t)
    tests.append(("sin_eq_y_sin_disjoint", g))

    # 4. ABox sin TODAS las arisas (solo nodos con sus props literales)
    g = rdflib.Graph()
    for t in tbox_full: g.add(t)
    for s, p, o in abox:
        if isinstance(o, rdflib.URIRef) and str(p) != str(rdflib.RDF.type):
            continue
        g.add((s, p, o))
    tests.append(("abox_sin_aristas", g))

    # 5. ABox con SOLO :Producto rdf:type (nada mas)
    g = rdflib.Graph()
    for t in tbox_full: g.add(t)
    for s, p, o in abox:
        if str(p) == str(rdflib.RDF.type):
            g.add((s, p, o))
    tests.append(("abox_solo_rdf_type", g))

    print(f"{'Variante':35s} {'Resultado':20s}")
    print("-" * 60)
    for name, g in tests:
        status, msg = _run_hermit(g, name)
        print(f"{name:35s} {status}")
        if status == "INCONSISTENT" and msg:
            pass  # silencioso por ahora


if __name__ == "__main__":
    main()
