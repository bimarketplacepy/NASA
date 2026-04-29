"""smoke_test_bloque5_stage5.py
==============================
Smoke test de OntologyClientV2 (Stage 5).

Cubre:
- A. Composicion + delegacion al v1: client_v2.producto() funciona como v1.
- B. productos_similares: top-K desde aristas :SIMILAR_A precomputadas.
- C. productos_similares_a_descripcion: cold-start con texto libre.
- D. Validaciones de input.

Pre-condiciones:
- Stage 2 completo (embeddings persistidos).
- Stage 4 completo (aristas :SIMILAR_A en Neo4j).

Uso:
    python smoke_test_bloque5_stage5.py
"""

from __future__ import annotations

import sys

from ontology_semantic.client_v2 import OntologyClientV2, QUERY_TEXT_SKU
from ontology_semantic.similarity.types import (
    BehavioralFlag,
    SimilarityResult,
)


def banner(s: str) -> None:
    print(f"\n{'=' * 60}\n{s}\n{'=' * 60}")


def main() -> None:
    banner("SMOKE TEST - Bloque 5 - Stage 5 OntologyClientV2")

    with OntologyClientV2() as ont:
        # =================================================================
        # A. Delegacion al v1
        # =================================================================
        banner("A. Delegacion al v1")
        info = ont.producto("17629")
        assert info is not None, "producto() del v1 no devolvio nada"
        print(f"[A.1] producto(17629) via v1:")
        print(f"    sku={info.get('sku')}  nombre={info.get('nombre')}")
        print(f"    categoria={info.get('categoria')}  pais_origen={info.get('pais_origen')}")
        assert "BOLSA" in str(info.get("nombre", "")).upper()

        eventos = ont.eventos_proximos(dias=365)
        print(f"\n[A.2] eventos_proximos(365) via v1: {len(eventos)} eventos")
        # No tenemos asserts fuertes de cantidad, solo que no rompa.

        # =================================================================
        # B. productos_similares (aristas :SIMILAR_A precomputadas)
        # =================================================================
        banner("B. productos_similares (Neo4j)")

        sku_test = "17629"  # BOLSA P/REGALO NAV
        similares = ont.productos_similares(sku_test, k=5, umbral=0.6)
        print(f"[B.1] Top-5 similares de SKU {sku_test} (umbral=0.6):")
        assert isinstance(similares, list)
        assert len(similares) > 0, f"No se encontraron similares de {sku_test}"
        for r in similares:
            assert isinstance(r, SimilarityResult)
            assert r.sku_a == sku_test
            assert r.sku_b != sku_test
            assert r.score_total >= 0.6
            assert r.confidence == 0.8  # uniforme en Bloque 5
            assert r.behavioral_flag == BehavioralFlag.UNAVAILABLE_GLOBAL
            # Recuperar nombre del similar para inspeccion manual
            other = ont.producto(r.sku_b)
            nombre = other.get("nombre") if other else "(?)"
            print(f"    sku_b={r.sku_b:<10} total={r.score_total:.3f} "
                  f"lex={r.score_lexical:.3f} str={r.score_structural:.3f} "
                  f"conf={r.confidence:.2f}  | {nombre}")

        # Verifica orden descendente
        scores = [r.score_total for r in similares]
        assert scores == sorted(scores, reverse=True), \
            f"Resultados desordenados: {scores}"
        print("    [OK] orden descendente por score_total")

        # B.2 - threshold mas alto debe filtrar
        similares_alto = ont.productos_similares(sku_test, k=10, umbral=0.95)
        print(f"\n[B.2] Misma SKU con umbral=0.95: {len(similares_alto)} resultados (subset estricto)")
        assert len(similares_alto) <= len(similares)
        for r in similares_alto:
            assert r.score_total >= 0.95

        # B.3 - SKU sin :SIMILAR_A devuelve []
        similares_inex = ont.productos_similares("INEXISTENTE_99999",
                                                  k=5, umbral=0.6)
        print(f"\n[B.3] SKU inexistente: {len(similares_inex)} resultados (esperado 0)")
        assert similares_inex == []

        # =================================================================
        # C. productos_similares_a_descripcion (cold-start)
        # =================================================================
        banner("C. productos_similares_a_descripcion (cold-start)")

        # Caso del prompt: "esfera dorada navideña 8cm" -> top-1 debe
        # ser una esfera real.
        query = "esfera dorada navideña 8cm"
        cold = ont.productos_similares_a_descripcion(query, k=5)
        print(f"[C.1] Top-5 para query '{query}':")
        assert isinstance(cold, list)
        assert len(cold) == 5
        for r in cold:
            assert r.sku_a == QUERY_TEXT_SKU
            assert r.confidence == 0.5  # solo lexical disponible
            assert "query_text" in r.flags
            other = ont.producto(r.sku_b)
            nombre = other.get("nombre", "(?)") if other else "(?)"
            categoria = (other.get("categoria") or {}).get("nombre", "") if other else ""
            print(f"    sku_b={r.sku_b:<10} total={r.score_total:.3f} "
                  f"conf={r.confidence:.2f}  | {nombre} ({categoria})")

        # Verifica orden desc
        cold_scores = [r.score_total for r in cold]
        assert cold_scores == sorted(cold_scores, reverse=True), \
            f"Cold-start resultados desordenados: {cold_scores}"

        # Validacion fundamental del prompt: top-1 debe ser una esfera real.
        # Buscamos ESFERA/BOLA en CUALQUIERA de los 3 campos textuales del
        # producto (nombre + nombre_corto + categoria). nombre_corto suele
        # ser el campo curado mas confiable - varios productos tienen
        # nombres genericos como "DECORACION NAVIDENA 14X6CM" pero su
        # nombre_corto los describe correctamente como "Esfera Navidena".
        top1 = cold[0]
        info_top1 = ont.producto(top1.sku_b)

        # Recuperar nombre_corto desde el index (no esta en la respuesta v1)
        # mejor dicho: lo tenemos en el texto del engine.
        idx_entry = next(
            (p for p in ont.engine.attrs_by_sku
             if p == top1.sku_b),
            None,
        )
        # Forma robusta: cargamos el texto del index del engine
        # (donde sku -> producto incluye texto completo).
        # Mas simple: leer el index JSON (ya cargado por el engine internamente
        # via from_disk - pero no expuso productos individualmente). Hacemos
        # una segunda pasada minima.
        import json
        from pathlib import Path
        idx_path = Path("data/embeddings_index.json")
        with idx_path.open("r", encoding="utf-8") as f:
            idx = json.load(f)
        sku_to_texto = {p["sku"]: p["texto"] for p in idx["productos"]}
        texto_top1 = sku_to_texto.get(top1.sku_b, "").upper()
        nombre_top1 = (info_top1.get("nombre") or "").upper()
        cat_top1 = ((info_top1.get("categoria") or {}).get("nombre") or "").upper()

        # Detection: cualquiera de ESFERA/BOLA en cualquiera de los 3 campos
        es_esfera = ("ESFERA" in texto_top1
                     or "BOLA" in texto_top1
                     or "ESFERA" in nombre_top1
                     or "ESFERA" in cat_top1
                     or "BOLA" in nombre_top1)
        print(f"\n    Top-1: nombre='{nombre_top1}' (cat='{cat_top1}')")
        print(f"    Texto en index: '{texto_top1}'")
        print(f"    es_esfera (busca en nombre + nombre_corto + categoria) = {es_esfera}")
        assert es_esfera, (
            f"FAIL criterio de aceptacion: top-1 no es esfera/bola. "
            f"sku={top1.sku_b}, nombre={nombre_top1}, cat={cat_top1}, "
            f"texto_index={texto_top1}"
        )
        print("    [OK] criterio de aceptacion del prompt: top-1 es ESFERA/BOLA")

        # C.2 - misma query, idempotencia / cache de embed_text
        cold2 = ont.productos_similares_a_descripcion(query, k=5)
        cold_skus = [r.sku_b for r in cold]
        cold2_skus = [r.sku_b for r in cold2]
        assert cold_skus == cold2_skus, "Resultado no determinista"
        print(f"\n[C.2] Misma query devuelve mismos resultados (cache OK)")

        # =================================================================
        # D. Validaciones de input
        # =================================================================
        banner("D. Validaciones de input")

        for caso, fn in [
            ("k=0", lambda: ont.productos_similares("17629", k=0)),
            ("umbral=1.5", lambda: ont.productos_similares("17629", umbral=1.5)),
            ("text vacio", lambda: ont.productos_similares_a_descripcion("", k=5)),
            ("text whitespace", lambda: ont.productos_similares_a_descripcion("   ", k=5)),
            ("k=-1 cold-start", lambda: ont.productos_similares_a_descripcion("test", k=-1)),
        ]:
            try:
                fn()
                print(f"    {caso}: FAIL (no rechazo input invalido)")
                sys.exit(1)
            except ValueError as e:
                print(f"    {caso}: OK -> ValueError: {e}")

    banner("STAGE 5 OntologyClientV2: TODO PASA.")
    print("\nSiguiente: Stage 6 - tests automatizados + 5 inspecciones manuales.")


if __name__ == "__main__":
    main()
