"""diag_cold_start.py - diagnostico de la calidad del cold-start.

Investiga por que el top-1 para "esfera dorada navidena 8cm" no es
una esfera real. Reporta:
- Top-30 de la query con marker para esferas/bolas reales.
- Cuantas esferas/bolas hay en el catalogo (texto contiene ESFERA o BOLA).
- En que rank caen las primeras 10 esferas/bolas.
- Plantilla generada para una esfera vs una figura (para ver si la
  composicion del texto esta diluyendo la senal).

NO modifica nada. Solo lee.
"""

from __future__ import annotations

import json
from pathlib import Path

from ontology_semantic.client_v2 import OntologyClientV2

QUERY = "esfera dorada navideña 8cm"
INDEX_PATH = Path("data/embeddings_index.json")


def main() -> None:
    print("=" * 60)
    print(f"DIAGNOSTICO COLD-START: query='{QUERY}'")
    print("=" * 60)

    with INDEX_PATH.open("r", encoding="utf-8") as f:
        idx = json.load(f)
    textos_by_sku = {p["sku"]: p["texto"] for p in idx["productos"]}

    with OntologyClientV2() as ont:
        # Ranking completo
        cold_full = ont.productos_similares_a_descripcion(QUERY, k=4643)
        sku_to_rank = {r.sku_b: i + 1 for i, r in enumerate(cold_full)}
        sku_to_score = {r.sku_b: r.score_total for r in cold_full}

        # Marcar esferas/bolas reales
        def es_esfera_real(sku: str) -> bool:
            txt = textos_by_sku.get(sku, "").upper()
            return ("ESFERA" in txt or "BOLA" in txt)

        # Top-30 con marker
        print(f"\n[1] Top-30 de la query (marker ★ = esfera/bola real):")
        for i, r in enumerate(cold_full[:30], 1):
            txt = textos_by_sku.get(r.sku_b, "(?)")
            mark = "★" if es_esfera_real(r.sku_b) else " "
            print(f"    {i:>3}. {mark} {r.sku_b:<8} score={r.score_total:.3f} | "
                  f"{txt[:75]}")

        # Esferas en el catalogo
        esferas = [sku for sku in textos_by_sku if es_esfera_real(sku)]
        print(f"\n[2] Total esferas/bolas en catalogo: {len(esferas)}")

        # Rank de las 15 mejor ranked esferas
        print(f"\n[3] Las 15 esferas/bolas mejor rankeadas vs la query:")
        esferas_con_rank = sorted(
            esferas, key=lambda s: sku_to_rank[s]
        )
        for sku in esferas_con_rank[:15]:
            rank = sku_to_rank[sku]
            score = sku_to_score[sku]
            txt = textos_by_sku[sku]
            print(f"    rank={rank:>4}  score={score:.3f} | {sku} {txt[:70]}")

        # Comparar plantilla esfera vs figura
        print(f"\n[4] Plantilla embeddeada (que ve el modelo):")
        # Una esfera real
        if esferas:
            sku_esf = esferas_con_rank[0]
            print(f"    Esfera mejor rankeada (rank={sku_to_rank[sku_esf]}):")
            print(f"      sku={sku_esf}")
            print(f"      texto: {textos_by_sku[sku_esf]!r}")
        # El top-1 actual
        sku_top = cold_full[0].sku_b
        print(f"\n    Top-1 actual (rank=1):")
        print(f"      sku={sku_top}")
        print(f"      texto: {textos_by_sku[sku_top]!r}")

        # Adicional: cuantos productos contienen las palabras clave
        print(f"\n[5] Distribucion de palabras clave en catalogo:")
        for palabra in ["ESFERA", "BOLA", "DORADO", "DORADA", "NAVIDEÑO",
                        "NAVIDEÑA", "8CM", "10CM", "FIGURA", "TAZA"]:
            n = sum(1 for txt in textos_by_sku.values()
                    if palabra in txt.upper())
            print(f"    {palabra:<12} -> {n} productos")


if __name__ == "__main__":
    main()
