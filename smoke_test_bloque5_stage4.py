"""smoke_test_bloque5_stage4.py
==============================
Smoke test de las funciones puras del Stage 4 (matrices + top-K + dedup).

NO toca Neo4j. NO baja el modelo. Tests sinteticos:
- compute_lexical_matrix: resultado simetrico y diagonal=1.
- compute_structural_matrix: igual condiciones + maneja None.
- compute_composite_matrix: combinacion lineal correcta + confidence.
- extract_top_k_edges: cantidades correctas.
- dedupe_pairs: simetrias, identidades, SKUs alfanumericos.

Para correr el pipeline real (persiste en Neo4j), ver al final.
"""

from __future__ import annotations

import sys

import numpy as np

from ontology_semantic.similarity.config import load_config
from ontology_semantic.similarity.precompute_top_k import (
    compute_composite_matrix,
    compute_lexical_matrix,
    compute_structural_matrix,
    dedupe_pairs,
    extract_top_k_edges,
)


def banner(s: str) -> None:
    print(f"\n{'=' * 60}\n{s}\n{'=' * 60}")


def main() -> None:
    banner("SMOKE TEST - Bloque 5 - Stage 4 (matrices + top-K + dedup)")

    cfg = load_config()

    # --- 1. compute_lexical_matrix ---------------------------------------
    embs = np.array([
        [1.0, 0.0, 0.0],
        [0.6, 0.8, 0.0],   # cos vs row 0 = 0.6
        [0.0, 1.0, 0.0],   # cos vs row 0 = 0.0, vs row 1 = 0.8
    ], dtype=np.float32)
    # Normalizar (fila 1 ya esta, fila 0 y 2 tambien son unitarias).
    for i in range(3):
        n = np.linalg.norm(embs[i])
        embs[i] /= n
    lex = compute_lexical_matrix(embs)
    print(f"\n[1] Lexical matrix:")
    print(lex)
    # Diagonal = 1.0
    assert np.allclose(np.diag(lex), 1.0), f"Diagonal != 1: {np.diag(lex)}"
    # Simetrica
    assert np.allclose(lex, lex.T), "No simetrica"
    # Valores conocidos
    assert abs(lex[0, 1] - 0.6) < 0.001, f"lex[0,1]={lex[0,1]}"
    assert abs(lex[0, 2] - 0.0) < 0.001
    assert abs(lex[1, 2] - 0.8) < 0.001

    # --- 2. compute_structural_matrix -----------------------------------
    productos = [
        {"sku": "A", "row": 0, "texto": "...",
         "attrs": {"pais_origen": "Paraguay", "perecedero": False,
                   "unidad": "Unid", "categoria_id": 100, "grupo_id": 10}},
        {"sku": "B", "row": 1, "texto": "...",
         "attrs": {"pais_origen": "Paraguay", "perecedero": False,
                   "unidad": "Unid", "categoria_id": 100, "grupo_id": 10}},
        {"sku": "C", "row": 2, "texto": "...",
         "attrs": {"pais_origen": "China", "perecedero": True,
                   "unidad": "Unid", "categoria_id": 200, "grupo_id": 20}},
    ]
    struct = compute_structural_matrix(productos, cfg)
    print(f"\n[2] Structural matrix:")
    print(struct)
    assert np.allclose(np.diag(struct), 1.0)
    assert np.allclose(struct, struct.T)
    # A y B son identicos -> 1.0
    assert struct[0, 1] == 1.0, f"struct[A,B]={struct[0,1]} != 1.0"
    # A y C: solo unidad coincide. Pesos pais=1 perec=1 unidad=0.5 cat=1.5 grupo=1.
    # Total=5, match=0.5/5=0.1.
    assert abs(struct[0, 2] - 0.1) < 0.001, f"struct[A,C]={struct[0,2]}"

    # --- 2b. structural con Nones ---------------------------------------
    productos_nones = [
        {"sku": "X", "row": 0, "texto": "...",
         "attrs": {"pais_origen": "Paraguay", "perecedero": False,
                   "unidad": "Unid", "categoria_id": 100, "grupo_id": 10}},
        {"sku": "Y", "row": 1, "texto": "...",
         "attrs": {"pais_origen": None, "perecedero": None,
                   "unidad": "Unid", "categoria_id": 100, "grupo_id": None}},
    ]
    struct2 = compute_structural_matrix(productos_nones, cfg)
    print(f"\n[2b] Structural con Nones:")
    print(struct2)
    # Solo unidad y categoria_id son comparables.
    # Match = (unidad=1)*0.5 + (categoria=1)*1.5 = 2.0
    # Disponible = 0.5 + 1.5 = 2.0
    # Score = 1.0
    assert struct2[0, 1] == 1.0

    # --- 3. compute_composite_matrix ------------------------------------
    composite, confidence = compute_composite_matrix(lex, struct, cfg)
    print(f"\n[3] Composite matrix (confidence={confidence}):")
    print(composite)
    # confidence = w_lex + w_str = 0.5 + 0.3 = 0.8
    assert abs(confidence - 0.8) < 0.001, f"confidence={confidence}"
    # diagonal = 1.0
    assert np.allclose(np.diag(composite), 1.0)
    # composite[0,1] = (0.5/0.8) * lex[0,1] + (0.3/0.8) * struct[0,1]
    #                = 0.625 * 0.6 + 0.375 * 1.0 = 0.375 + 0.375 = 0.75
    expected = 0.625 * lex[0, 1] + 0.375 * struct[0, 1]
    assert abs(composite[0, 1] - expected) < 0.001, \
        f"composite[0,1]={composite[0,1]}, esperado={expected}"
    print(f"    composite[0,1]={composite[0,1]:.4f} (esperado {expected:.4f})")

    # --- 4. extract_top_k_edges -----------------------------------------
    skus = ["A", "B", "C"]
    edges = extract_top_k_edges(
        composite=composite, lex=lex, struct=struct,
        skus=skus, confidence=confidence, k=2, threshold=None,
    )
    print(f"\n[4] Top-2 por SKU (3 SKUs * 2 = 6 dirigidas):")
    for e in edges:
        print(f"    {e['sku_a']} -> {e['sku_b']}: total={e['score_total']:.3f} "
              f"lex={e['score_lex']:.3f} str={e['score_str']:.3f}")
    # 3 SKUs, top-2 cada uno = 6 aristas dirigidas (porque excluye self,
    # y N-1=2 vecinos posibles cada uno).
    assert len(edges) == 6, f"len={len(edges)}"
    # Ningun edge tiene sku_a == sku_b
    assert all(e["sku_a"] != e["sku_b"] for e in edges)

    # --- 5. dedupe_pairs ------------------------------------------------
    deduped = dedupe_pairs(edges)
    print(f"\n[5] Deduped: {len(edges)} -> {len(deduped)} aristas:")
    for e in deduped:
        print(f"    {e['sku_a']} -- {e['sku_b']}: total={e['score_total']:.3f}")
    # 3 pares unicos: (A,B), (A,C), (B,C).
    assert len(deduped) == 3
    # Todos con sku_a < sku_b lexicograficamente.
    for e in deduped:
        assert e["sku_a"] < e["sku_b"], f"Mal ordenado: {e}"
    # Set de pares.
    pares = {(e["sku_a"], e["sku_b"]) for e in deduped}
    assert pares == {("A", "B"), ("A", "C"), ("B", "C")}, f"pares={pares}"

    # --- 6. dedupe con duplicados explicitos ---------------------------
    edges_dup = [
        {"sku_a": "X", "sku_b": "Y", "score_lex": 0.9, "score_str": 1.0,
         "score_total": 0.92, "confidence": 0.8},
        {"sku_a": "Y", "sku_b": "X", "score_lex": 0.9, "score_str": 1.0,
         "score_total": 0.92, "confidence": 0.8},  # duplicado simetrico
        {"sku_a": "X", "sku_b": "X", "score_lex": 1.0, "score_str": 1.0,
         "score_total": 1.0, "confidence": 0.8},  # self-loop
    ]
    deduped = dedupe_pairs(edges_dup)
    print(f"\n[6] Dedup explicito: {len(edges_dup)} -> {len(deduped)}")
    assert len(deduped) == 1
    assert deduped[0]["sku_a"] == "X" and deduped[0]["sku_b"] == "Y"

    # --- 7. extract con threshold --------------------------------------
    edges_thr = extract_top_k_edges(
        composite=composite, lex=lex, struct=struct,
        skus=skus, confidence=confidence, k=2, threshold=0.7,
    )
    print(f"\n[7] Top-2 con threshold=0.7: {len(edges_thr)} aristas")
    for e in edges_thr:
        assert e["score_total"] >= 0.7

    banner("STAGE 4 (funciones puras): TODO PASA.")
    print("\nSiguiente: correr el pipeline real con Neo4j:")
    print("    python -m ontology_semantic.similarity.precompute_top_k stats")
    print("        (calcula y muestra distribucion, NO escribe en Neo4j)")
    print("    python -m ontology_semantic.similarity.precompute_top_k run")
    print("        (calcula + persiste :SIMILAR_A con MERGE idempotente)")
    print("    python -m ontology_semantic.similarity.precompute_top_k run --force")
    print("        (borra :SIMILAR_A previas antes de insertar)")


if __name__ == "__main__":
    main()
