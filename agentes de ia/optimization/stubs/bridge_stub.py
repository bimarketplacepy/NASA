"""Stub del bridge OWL/RDF de Abi."""

from __future__ import annotations
import json
from pathlib import Path


_STUB_DB_PATH = Path("optimization/stubs/_neo4j_simulado.json")


def importar_owl_a_neo4j(turtle_str: str) -> dict:
    """STUB: simula importacion de Turtle al grafo Neo4j. TODO: reemplazar por bridge de Abi.

    Acepta ruta a un archivo .ttl (como el bridge real) o el texto Turtle inline.
    """
    _STUB_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    payload = turtle_str
    p = Path(turtle_str)
    if p.exists() and p.is_file():
        payload = p.read_text(encoding="utf-8")

    if _STUB_DB_PATH.exists():
        with open(_STUB_DB_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
    else:
        db = {"importaciones": []}

    db["importaciones"].append({
        "tipo": "turtle_importado",
        "tamanio_bytes": len(payload),
        "preview": payload[:300],
    })

    with open(_STUB_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    return {
        "ok": True,
        "tripletas_importadas": payload.count("\n"),
        "mensaje": f"STUB: Turtle de {len(payload)} bytes simulado en Neo4j",
    }


if __name__ == "__main__":
    turtle_ejemplo = """@prefix : <http://marketplace.com.py/onto/v1#> .
:OpenLoopAlgorithm a :Algorithm ;
    :id "open_loop" ;
    :nombre "Open-Loop Baseline" ;
    :requiereSemanasMinimas 0 ."""
    resultado = importar_owl_a_neo4j(turtle_ejemplo)
    print(f"Resultado del stub: {resultado}")
