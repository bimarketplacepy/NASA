"""smoke_test_bloque5_stage1.py
==============================
Smoke test del scaffolding de Bloque 5 - Stage 1.

No toca Neo4j ni embeddings. Solo verifica:
- El paquete ``ontology_semantic.similarity`` importa.
- ``load_config`` parsea ``config/similarity_weights.yaml``.
- ``SimilarityEngine`` se instancia (sin datos derivados).
- Los stubs ``score_lexical/structural/behavioral/trend/composite_score``
  tiran ``NotImplementedError`` con mensaje claro.
- ``SimilarityResult`` se construye y serializa.

Uso:

    python smoke_test_bloque5_stage1.py

Pegame el output al chat.
"""

from __future__ import annotations

import sys


def main() -> None:
    print("=" * 60)
    print("SMOKE TEST - Bloque 5 - Stage 1 scaffolding")
    print("=" * 60)

    # --- 1. Imports ------------------------------------------------------
    from ontology_semantic.similarity import (
        BehavioralFlag,
        SimilarityConfig,
        SimilarityEngine,
        SimilarityResult,
        load_config,
    )
    print("[1] Imports OK")

    # --- 2. Cargar config ------------------------------------------------
    cfg: SimilarityConfig = load_config()
    print("[2] load_config OK")
    print(f"    model_name      : {cfg.embedding_model_name}")
    print(f"    embedding_dim   : {cfg.embedding_dim}")
    print(f"    top_k_default   : {cfg.top_k_default}")
    print(f"    threshold       : {cfg.threshold_default}")
    print(f"    weights         : {cfg.weights}")
    print(f"    text_template   : {cfg.text_template!r}")
    print(f"    structural attr : {[a.name for a in cfg.structural_attributes]}")
    print(f"    behavioral availab: {cfg.behavioral_available}")
    print(f"    trend availab   : {cfg.trend_available}")

    suma = sum(cfg.weights.values())
    assert abs(suma - 1.0) < 0.001, f"Pesos no suman 1.0: {suma}"
    print(f"    suma de pesos   : {suma} (OK)")

    # --- 3. Instanciar engine sin datos ---------------------------------
    eng = SimilarityEngine(cfg)
    print("[3] SimilarityEngine() instanciado sin datos derivados")

    # --- 4. Stubs deben tirar NotImplementedError -----------------------
    stubs = [
        ("score_lexical",    lambda: eng.score_lexical("a", "b")),
        ("score_structural", lambda: eng.score_structural("a", "b")),
        ("score_behavioral", lambda: eng.score_behavioral("a", "b")),
        ("score_trend",      lambda: eng.score_trend("a")),
        ("composite_score",  lambda: eng.composite_score("a", "b")),
    ]
    print("[4] Verificando stubs (deben tirar NotImplementedError):")
    for name, fn in stubs:
        try:
            fn()
            print(f"    {name}: FALLO (no tiro)")
            sys.exit(1)
        except NotImplementedError as e:
            print(f"    {name}: OK -> {e}")
        except Exception as e:
            print(f"    {name}: tiro {type(e).__name__} (esperabamos NotImplementedError): {e}")
            sys.exit(1)

    # --- 5. SimilarityResult construye + serializa ----------------------
    res = SimilarityResult(
        sku_a="111",
        sku_b="222",
        score_lexical=0.8,
        score_structural=0.6,
        score_behavioral=0.0,
        score_trend=0.0,
        score_total=0.7,
        confidence=0.8,
        behavioral_flag=BehavioralFlag.UNAVAILABLE_GLOBAL,
        flags=("trend_no_signal",),
    )
    d = res.to_dict()
    print("[5] SimilarityResult OK:")
    for k, v in d.items():
        print(f"    {k:<18} = {v!r}")

    assert d["sku_a"] == "111"
    assert d["score_lex"] == 0.8
    assert d["behavioral_flag"] == "unavailable_global"
    assert d["flags"] == ["trend_no_signal"]
    print("    serializacion verificada (OK)")

    # --- 6. Validacion de SimilarityResult fuera de rango --------------
    try:
        SimilarityResult(
            sku_a="x", sku_b="y",
            score_lexical=2.0, score_structural=0.5,
            score_behavioral=0.0, score_trend=0.0,
            score_total=0.5, confidence=0.5,
        )
        print("[6] FALLO: SimilarityResult acepto score=2.0")
        sys.exit(1)
    except ValueError as e:
        print(f"[6] Validacion de rango OK -> {e}")

    print()
    print("=" * 60)
    print("STAGE 1 SCAFFOLDING: TODO PASA.")
    print("=" * 60)


if __name__ == "__main__":
    main()
