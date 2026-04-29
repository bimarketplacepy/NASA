"""smoke_test_bloque5_stage3.py
==============================
Smoke test del SimilarityEngine completo (Stage 3).

Cubre:
- A. Tests sinteticos con fixtures pequenas (sin Neo4j, sin modelo):
  * score_lexical: cosine entre vectores conocidos.
  * score_structural: Gower con atributos parciales y faltantes.
  * score_behavioral: missing-everywhere (estado actual).
  * composite_score: renormalizacion de pesos cuando hay missing.
  * Identidad: sku_a == sku_b -> score 1.0.

- B. Tests con datos reales (cargando los embeddings del Stage 2):
  * Carga via from_disk().
  * Score entre dos SKUs reales.
  * Comparativa: SKU 'BOLSA NAVIDEÑA' vs 'BOLSA P/REGALO' (deberian
    ser mas similares entre si que vs un 'RENO DORADO').

NO baja el modelo ni embeddea texto en runtime - eso pasa al correr
realmente score_trend con un signal o productos_similares_a_descripcion.

Uso:
    python smoke_test_bloque5_stage3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from ontology_semantic.similarity import (
    BehavioralFlag,
    SimilarityEngine,
    SimilarityResult,
    load_config,
)


def banner(s: str) -> None:
    print(f"\n{'=' * 60}\n{s}\n{'=' * 60}")


def main() -> None:
    banner("SMOKE TEST - Bloque 5 - Stage 3 SimilarityEngine")

    cfg = load_config()
    print(f"Pesos default: {cfg.weights}")
    print(f"behavioral_available: {cfg.behavioral_available}")
    print(f"trend_available     : {cfg.trend_available}")

    # =====================================================================
    # PARTE A: Fixtures sinteticas
    # =====================================================================
    banner("A. Tests sinteticos (sin Neo4j ni modelo)")

    # Fixture: 3 productos con embeddings sinteticos UNITARIOS y
    # atributos categoricos.
    fake_embs = np.array([
        [1.0, 0.0, 0.0, 0.0],   # row 0
        [0.9, np.sqrt(1 - 0.9**2), 0.0, 0.0],  # row 1, cos(0,1) = 0.9
        [0.0, 0.0, 1.0, 0.0],   # row 2, ortogonal a 0 y 1
    ], dtype=np.float32)
    # Verificamos normalizacion.
    for i in range(3):
        assert abs(np.linalg.norm(fake_embs[i]) - 1.0) < 1e-5

    # Truncamos cfg.embedding_dim para los tests (solo en runtime,
    # no tocamos YAML).
    fake_cfg = type(cfg)(
        weights=cfg.weights,
        threshold_default=cfg.threshold_default,
        top_k_default=cfg.top_k_default,
        embedding_model_name=cfg.embedding_model_name,
        embedding_dim=4,  # OVERRIDE para fixture
        text_template=cfg.text_template,
        structural_attributes=cfg.structural_attributes,
        behavioral_available=cfg.behavioral_available,
        trend_available=cfg.trend_available,
    )

    sku_to_row = {"A": 0, "B": 1, "C": 2}
    attrs = {
        "A": {"pais_origen": "Paraguay", "perecedero": False, "unidad": "Unid",
              "categoria_id": 100, "grupo_id": 10},
        "B": {"pais_origen": "Paraguay", "perecedero": False, "unidad": "Unid",
              "categoria_id": 100, "grupo_id": 10},  # identico a A
        "C": {"pais_origen": "China", "perecedero": True, "unidad": "Unid",
              "categoria_id": 200, "grupo_id": 20},  # opuesto
    }
    eng = SimilarityEngine(
        cfg=fake_cfg,
        embeddings=fake_embs,
        sku_to_row=sku_to_row,
        attrs_by_sku=attrs,
    )

    # --- A.1 score_lexical -----------------------------------------------
    print("\n[A.1] score_lexical")
    s_aa = eng.score_lexical("A", "A")
    s_ab = eng.score_lexical("A", "B")
    s_ac = eng.score_lexical("A", "C")
    print(f"    sim(A, A) = {s_aa:.4f} (esperado 1.0)")
    print(f"    sim(A, B) = {s_ab:.4f} (esperado ~0.9)")
    print(f"    sim(A, C) = {s_ac:.4f} (esperado 0.0)")
    assert s_aa == 1.0
    assert abs(s_ab - 0.9) < 0.001
    assert abs(s_ac - 0.0) < 0.001

    # KeyError para SKU desconocido
    try:
        eng.score_lexical("A", "DESCONOCIDO")
        print("    FAIL: deberia haber tirado KeyError")
        sys.exit(1)
    except KeyError as e:
        print(f"    KeyError OK: {e}")

    # --- A.2 score_structural -------------------------------------------
    print("\n[A.2] score_structural")
    s_aa = eng.score_structural("A", "A")
    s_ab = eng.score_structural("A", "B")
    s_ac = eng.score_structural("A", "C")
    print(f"    str(A, A) = {s_aa:.4f} (esperado 1.0, identidad)")
    print(f"    str(A, B) = {s_ab:.4f} (esperado 1.0, atributos identicos)")
    print(f"    str(A, C) = {s_ac:.4f} (esperado bajo, solo unidad coincide)")
    assert s_aa == 1.0
    assert s_ab == 1.0  # todos los atributos coinciden
    # A y C: solo "unidad" coincide. Pesos: pais=1, perec=1, unidad=0.5,
    # cat=1.5, grupo=1. Total=5. Match=0.5/5=0.1.
    assert abs(s_ac - 0.1) < 0.001

    # SKU sin atributos -> 0
    eng_sin_attrs = SimilarityEngine(
        cfg=fake_cfg, embeddings=fake_embs, sku_to_row=sku_to_row,
        attrs_by_sku={"A": attrs["A"]},  # solo A tiene attrs
    )
    s = eng_sin_attrs.score_structural("A", "B")
    print(f"    str(A, B) sin attrs en B = {s:.4f} (esperado 0.0)")
    assert s == 0.0

    # Atributos parciales (B tiene solo categoria, falta el resto)
    attrs_parcial = {
        "A": {"pais_origen": "Paraguay", "categoria_id": 100, "grupo_id": 10,
              "unidad": "Unid", "perecedero": False},
        "B": {"pais_origen": None, "categoria_id": 100, "grupo_id": None,
              "unidad": "", "perecedero": None},
    }
    eng_p = SimilarityEngine(cfg=fake_cfg, attrs_by_sku=attrs_parcial,
                             sku_to_row={"A": 0, "B": 1}, embeddings=fake_embs)
    s = eng_p.score_structural("A", "B")
    print(f"    str(A, B) atributos parciales = {s:.4f} (esperado 1.0, "
          f"solo categoria comparable y coincide)")
    assert s == 1.0  # solo categoria_id es comparable -> match 1

    # --- A.3 score_behavioral -------------------------------------------
    print("\n[A.3] score_behavioral (estado actual: UNAVAILABLE_GLOBAL)")
    s, flag = eng.score_behavioral("A", "B")
    print(f"    beh(A, B) = ({s:.4f}, {flag.value})")
    assert s == 0.0
    assert flag == BehavioralFlag.UNAVAILABLE_GLOBAL

    # --- A.4 composite_score: renormalizacion ---------------------------
    print("\n[A.4] composite_score con renormalizacion")
    res = eng.composite_score("A", "B")
    print(f"    SimilarityResult(A, B):")
    for k, v in res.to_dict().items():
        print(f"        {k:<18} = {v}")
    # Esperado:
    # - lex(A,B) = 0.9, str(A,B) = 1.0, beh = 0.0 (missing), trd = 0.0 (no signal)
    # - confidence = w_lex + w_str = 0.5 + 0.3 = 0.8
    # - eff_lex = 0.5/0.8 = 0.625, eff_str = 0.3/0.8 = 0.375
    # - score_total = 0.625*0.9 + 0.375*1.0 = 0.5625 + 0.375 = 0.9375
    assert abs(res.score_lexical - 0.9) < 0.001
    assert res.score_structural == 1.0
    assert res.score_behavioral == 0.0
    assert res.score_trend == 0.0
    assert abs(res.confidence - 0.8) < 0.001, f"confidence={res.confidence}"
    assert abs(res.score_total - 0.9375) < 0.001, \
        f"score_total={res.score_total}, esperaba 0.9375"
    assert res.behavioral_flag == BehavioralFlag.UNAVAILABLE_GLOBAL
    assert "behavioral_unavailable_global" in res.flags
    assert "trend_no_signal" in res.flags
    print("    [OK] confidence=0.8, score_total=0.9375 (renormalizacion correcta)")

    # --- A.5 Identidad ----------------------------------------------------
    print("\n[A.5] composite_score(X, X) -> identidad")
    res = eng.composite_score("A", "A")
    assert res.score_total == 1.0
    assert res.confidence == 1.0
    assert "identity" in res.flags
    print(f"    OK: score_total=1.0, confidence=1.0, flags={res.flags}")

    # --- A.6 weights_override -------------------------------------------
    print("\n[A.6] weights_override")
    res = eng.composite_score("A", "B", weights_override={"lexical": 1.0,
                                                          "structural": 0.0})
    # Forzando lex=1.0, str=0.0, behavioral disabled, trend disabled:
    # disponibles = {lex: 1.0, str: 0.0}, confidence = 1.0
    # eff_lex = 1.0, eff_str = 0.0 -> score_total = lex(A,B) = 0.9
    print(f"    score_total con override (solo lexical) = {res.score_total:.4f}")
    print(f"    confidence = {res.confidence:.4f}")
    assert abs(res.score_total - 0.9) < 0.001

    # weights_override invalido
    try:
        eng.composite_score("A", "B", weights_override={"inventado": 1.0})
        print("    FAIL: deberia rechazar key desconocida")
        sys.exit(1)
    except ValueError as e:
        print(f"    Rechaza key desconocida OK: {e}")

    # =====================================================================
    # PARTE B: Datos reales del Stage 2
    # =====================================================================
    banner("B. Tests con datos reales (embeddings del Stage 2)")

    npy = Path("data/embeddings_productos.npy")
    if not npy.exists():
        print(f"SKIP: {npy} no existe. Corre primero "
              f"`python -m ontology_semantic.similarity.embeddings precompute`.")
        sys.exit(0)

    eng_real = SimilarityEngine.from_disk()
    n_skus = len(eng_real.sku_to_row)
    dim = eng_real.embeddings.shape[1] if eng_real.embeddings is not None else 0
    print(f"Engine cargado: {n_skus} SKUs, dim={dim}")
    assert n_skus == 4643
    assert dim == 384

    # SKUs del show del Stage 2:
    # 17629 = BOLSA P/ REGALO NAV.
    # 17652 = BOLSA NAVIDEÑA 29570
    # 18703 = RENO DORADO MX24
    # 43208 = GUIRNALDA PY 08312
    # 48695 = CAMPANA DECOR 066-420660
    bolsa_a = "17629"
    bolsa_b = "17652"
    reno = "18703"
    guirnalda = "43208"

    print(f"\n[B.1] Comparaciones lexicas (las dos bolsas vs cosa distinta)")
    sim_bolsa_bolsa = eng_real.score_lexical(bolsa_a, bolsa_b)
    sim_bolsa_reno = eng_real.score_lexical(bolsa_a, reno)
    sim_bolsa_guirnalda = eng_real.score_lexical(bolsa_a, guirnalda)
    print(f"    sim_lex({bolsa_a} BOLSA P/REGALO, {bolsa_b} BOLSA NAVIDEÑA) = {sim_bolsa_bolsa:.4f}")
    print(f"    sim_lex({bolsa_a} BOLSA P/REGALO, {reno} RENO DORADO)        = {sim_bolsa_reno:.4f}")
    print(f"    sim_lex({bolsa_a} BOLSA P/REGALO, {guirnalda} GUIRNALDA)     = {sim_bolsa_guirnalda:.4f}")
    assert sim_bolsa_bolsa > sim_bolsa_reno, \
        "Esperaba que las dos BOLSAS sean mas similares entre si que BOLSA vs RENO"

    print(f"\n[B.2] Comparaciones estructurales")
    sim_str_bb = eng_real.score_structural(bolsa_a, bolsa_b)
    sim_str_br = eng_real.score_structural(bolsa_a, reno)
    print(f"    sim_str({bolsa_a}, {bolsa_b}) = {sim_str_bb:.4f}")
    print(f"    sim_str({bolsa_a}, {reno})    = {sim_str_br:.4f}")

    print(f"\n[B.3] Composite real (B vs B)")
    res = eng_real.composite_score(bolsa_a, bolsa_b)
    for k, v in res.to_dict().items():
        print(f"    {k:<18} = {v}")
    # confidence deberia ser 0.8 (lex+str disponibles, beh+trd no)
    assert abs(res.confidence - 0.8) < 0.001
    assert "behavioral_unavailable_global" in res.flags
    assert "trend_no_signal" in res.flags

    print(f"\n[B.4] Composite real (BOLSA vs RENO - distinto)")
    res2 = eng_real.composite_score(bolsa_a, reno)
    for k, v in res2.to_dict().items():
        print(f"    {k:<18} = {v}")

    assert res.score_total > res2.score_total, \
        f"Esperaba composite(BOLSA,BOLSA)={res.score_total:.3f} > " \
        f"composite(BOLSA,RENO)={res2.score_total:.3f}"

    banner("STAGE 3 SimilarityEngine: TODO PASA.")
    print("\nSiguiente: Stage 4 - precompute matriz top-K + persiste :SIMILAR_A en Neo4j.")


if __name__ == "__main__":
    main()
