"""Debug Bloque 4: identifica que axioma del TBox + datos reales rompe HermiT.

Para cada axioma sospechoso lo deshabilita temporalmente, corre HermiT directo,
y reporta si la ontologia pasa a ser consistent. La fila que diga 'OK' es el
axioma que dispara el conflicto.

Uso:
    python debug_axioms.py
"""
import os
import subprocess
from pathlib import Path

import owlready2
import rdflib

OWL = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
NS = "http://marketplace.com.py/onto/v1#"


def main() -> None:
    tbox_full = rdflib.Graph()
    tbox_full.parse("ontology_semantic/marketplace.owl", format="nt")
    abox = rdflib.Graph()
    abox.parse("data/snapshot_subset10.ttl", format="turtle")

    candidatos = [
        ("disjoint_localexterior",
         lambda g: g.remove((
             rdflib.URIRef(NS + "ProveedorLocal"),
             OWL.disjointWith,
             rdflib.URIRef(NS + "ProveedorExterior"),
         ))),
        ("disjoint_productoproveedor",
         lambda g: g.remove((
             rdflib.URIRef(NS + "Producto"),
             OWL.disjointWith,
             rdflib.URIRef(NS + "Proveedor"),
         ))),
        ("eq_ProductoColdStart",
         lambda g: _remove_eq(g, "ProductoColdStart")),
        ("eq_ProductoCritico",
         lambda g: _remove_eq(g, "ProductoCritico")),
        ("eq_ProductoPerecedero",
         lambda g: _remove_eq(g, "ProductoPerecedero")),
        ("eq_ProductoAltaRotacion",
         lambda g: _remove_eq(g, "ProductoAltaRotacion")),
        ("eq_ProveedorLocal",
         lambda g: _remove_eq(g, "ProveedorLocal")),
        ("eq_ProveedorExterior",
         lambda g: _remove_eq(g, "ProveedorExterior")),
    ]

    hermit_dir = Path(owlready2.__file__).parent / "hermit"
    classpath = f"{hermit_dir}{os.pathsep}{hermit_dir}/HermiT.jar"

    print(f"{'Axioma deshabilitado':35s} {'Resultado':20s}")
    print("-" * 60)
    for name, mod_fn in candidatos:
        g = rdflib.Graph()
        for t in tbox_full:
            g.add(t)
        mod_fn(g)
        for t in abox:
            g.add(t)
        tmp = Path(f"data/_dbg_{name}.nt")
        g.serialize(str(tmp), format="nt")
        cmd = [
            "java", "-Xmx2000M", "-cp", classpath,
            "org.semanticweb.HermiT.cli.CommandLine",
            "-c", "-I", tmp.resolve().as_uri(),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        inconsistent = "Inconsistent" in (r.stderr or "")
        status = "INCONSISTENT" if inconsistent else "OK (consistent)"
        print(f"{name:35s} {status}")


def _remove_eq(g: rdflib.Graph, class_name: str) -> None:
    """Remueve el equivalentClass triple de la clase + el blank-node tree."""
    cls_uri = rdflib.URIRef(NS + class_name)
    for s, p, o in list(g.triples((cls_uri, OWL.equivalentClass, None))):
        g.remove((s, p, o))
        # Tambien quitar los triples del BNode anonimo apuntado.
        if isinstance(o, rdflib.BNode):
            for t in list(g.triples((o, None, None))):
                g.remove(t)


if __name__ == "__main__":
    main()
