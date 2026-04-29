"""inspeccion_manual_5skus.py - Reporte para inspeccion manual.

Tarea 1 v2 - Bloque 5 - Stage 6.

Selecciona 5 SKUs de distintas categorias y reporta sus top-3 similares
desde las aristas :SIMILAR_A precomputadas (Stage 4). Output formateado
para que la usuaria revise manualmente que los matches son sensatos.

Criterio del prompt: "Para 5 SKUs de muestra, los top-3 similares pasan
inspeccion manual."

Categorias representativas elegidas (cubren 5 grupos distintos):
- BAZAR (BOLSA P/REGALO)
- ESFERAS (ESFERA DECOR)
- FIGURAS (FIG SANTA)
- COLGANTE (GUIRNALDA)
- BAZAR (TAZA - segundo BAZAR para validar diversidad dentro)

Como interpretar el output:
- Si para una BOLSA (BAZAR) los top-3 son TAZAS (tambien BAZAR), la
  senal estructural domina pero hay diversidad lexica baja.
- Si para una ESFERA aparecen FIGURAS, el lexico no discrimina bien
  (sobreajuste a "Navideña" en pre-training del MiniLM).
- Si los scores son todos > 0.95, los productos son cuasi-duplicados
  (esperado en un catalogo navideño con muchas variantes).

Uso:
    python inspeccion_manual_5skus.py
"""

from __future__ import annotations

from ontology_semantic.client_v2 import OntologyClientV2


# 5 SKUs de muestra, uno por categoria distinta. Sacados de los samples
# vistos durante el desarrollo (Stages 2-5).
SKUS_MUESTRA = [
    ("17629",  "BOLSA P/REGALO        (BAZAR/BAZAR)"),
    ("247329", "ESFERA DECOR 10X10X10 (ESFERAS/ADORNOS)"),
    ("250541", "FIG SANTA 27CM ROJO   (FIGURAS/ADORNOS)"),
    ("43208",  "GUIRNALDA PY          (COLGANTE/ADORNOS)"),
    ("190886", "TAZA NAVIDEÑO 400ML   (otra BAZAR)"),
]


def main() -> None:
    print("=" * 72)
    print("INSPECCION MANUAL - 5 SKUs de muestra, top-3 similares")
    print("=" * 72)
    print()
    print("Mira si cada top-3 te parece razonable:")
    print(" - Para una BOLSA, ?aparecen otros productos navideños cercanos?")
    print(" - Para una ESFERA, ?aparecen otras esferas/bolas?")
    print(" - Para una FIGURA, ?aparecen otras figuras?")
    print(" - Si aparecen mezclas raras (esfera vs bolsa), lo discutimos.")
    print()
    print("score_total = composite ponderado lex+str (renormalizado).")
    print("score_lex   = cosine sobre embeddings de texto.")
    print("score_str   = Gower sobre {pais, perec, unidad, cat_id, grupo_id}.")
    print("conf=0.80   = constante en Bloque 5 (behavioral+trend desactivados).")
    print()

    with OntologyClientV2() as ont:
        for sku, descripcion in SKUS_MUESTRA:
            print("=" * 72)
            print(f"SKU {sku} - {descripcion}")
            print("-" * 72)

            info = ont.producto(sku)
            if info is None:
                print(f"  [SKU {sku} no existe en Neo4j - lo salteo]")
                print()
                continue

            print(f"  nombre        : {info.get('nombre', '?')}")
            cat = info.get("categoria") or {}
            grupo = info.get("grupo") or {}
            print(f"  categoria     : {cat.get('nombre', '?')} (id={cat.get('id', '?')})")
            print(f"  grupo         : {grupo.get('nombre', '?')}")
            print(f"  pais_origen   : {info.get('pais_origen', '?')}")
            print(f"  perecedero    : {info.get('perecedero', '?')}")
            print()

            # Top-3 con umbral 0 (no filtramos, queremos ver lo que hay)
            similares = ont.productos_similares(sku, k=3, umbral=0.0)
            if not similares:
                print("  [Sin similares precomputados - revisar si se corrio "
                      "precompute_top_k]")
                print()
                continue

            print(f"  Top-3 similares:")
            for i, r in enumerate(similares, 1):
                other = ont.producto(r.sku_b)
                if other is None:
                    nombre_other = f"(no encontrado en v1)"
                    cat_other = "?"
                else:
                    nombre_other = other.get("nombre", "?")
                    cat_obj = other.get("categoria") or {}
                    cat_other = cat_obj.get("nombre", "?")
                print(f"    {i}. sku={r.sku_b:<8}  total={r.score_total:.3f}  "
                      f"lex={r.score_lexical:.3f}  str={r.score_structural:.3f}  "
                      f"conf={r.confidence:.2f}")
                print(f"       {nombre_other}")
                print(f"       categoria: {cat_other}")
            print()

    print("=" * 72)
    print("Inspeccion completa.")
    print("=" * 72)
    print()
    print("Si los top-3 te parecen razonables para los 5 SKUs, el criterio")
    print("'top-3 pasa inspeccion manual' del prompt se considera cumplido.")
    print("Si hay sorpresas, las discutimos antes de cerrar el bloque.")


if __name__ == "__main__":
    main()
