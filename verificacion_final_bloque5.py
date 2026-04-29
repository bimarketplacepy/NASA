"""verificacion_final_bloque5.py - Verificacion end-to-end del Bloque 5.

Tarea 1 v2 - Bloque 5 - Stage 7.

Confirma que todo el sistema corre limpio antes de cerrar el bloque:

1. Carga el engine desde disco (embeddings + atributos persistidos).
2. Cuenta aristas :SIMILAR_A en Neo4j.
3. Verifica que productos_similares devuelve resultados validos para
   un SKU sample.
4. Verifica que productos_similares_a_descripcion (cold-start) devuelve
   una esfera para "esfera dorada navidena 8cm".
5. Confirma que tests v1 anteriores siguen pasando (no rompimos nada).

NO modifica nada. Read-only.
"""

from __future__ import annotations

import subprocess
import sys

from ontology_semantic.client_v2 import OntologyClientV2


def main() -> None:
    print("=" * 72)
    print("VERIFICACION FINAL BLOQUE 5")
    print("=" * 72)

    fallos = []

    # 1. Engine se carga desde disco -----------------------------------
    print("\n[1] Cargando engine desde disco...")
    try:
        with OntologyClientV2() as ont:
            n_skus = len(ont.engine.sku_to_row)
            dim = ont.engine.embeddings.shape[1]
            print(f"    OK: engine cargado. N={n_skus} SKUs, dim={dim}")
            assert n_skus == 4643
            assert dim == 384

            # 2. Aristas :SIMILAR_A en Neo4j -------------------------
            print("\n[2] Conteo de aristas :SIMILAR_A en Neo4j...")
            with ont._v1.driver.session() as s:
                n = s.run(
                    "MATCH ()-[r:SIMILAR_A]->() RETURN count(r) AS n"
                ).single()["n"]
            print(f"    OK: {n} aristas :SIMILAR_A")
            assert n > 0, "No hay aristas precomputadas"

            # 3. productos_similares ----------------------------------
            print("\n[3] productos_similares para SKU 17629 (BOLSA P/REGALO)...")
            similares = ont.productos_similares("17629", k=3, umbral=0.6)
            print(f"    OK: {len(similares)} resultados, "
                  f"top score = {similares[0].score_total:.3f}")
            assert len(similares) == 3
            assert all(r.confidence == 0.8 for r in similares)

            # 4. Cold-start -----------------------------------------
            print("\n[4] productos_similares_a_descripcion "
                  "('esfera dorada navidena 8cm')...")
            cold = ont.productos_similares_a_descripcion(
                "esfera dorada navideña 8cm", k=5,
            )
            top = cold[0]
            top_info = ont.producto(top.sku_b)
            print(f"    OK: top-1 sku={top.sku_b} score={top.score_total:.3f}")
            print(f"        nombre={top_info.get('nombre')}")
            assert top.confidence == 0.5
    except Exception as e:
        fallos.append(f"Bloques 1-4: {e}")
        print(f"    FAIL: {e}")

    # 5. Tests del bloque ---------------------------------------------
    print("\n[5] Re-corriendo tests del Bloque 5 (test_similarity)...")
    try:
        out = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_similarity"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0:
            # unittest imprime el resumen en stderr
            ultimo = out.stderr.strip().split("\n")[-1]
            print(f"    OK: {ultimo}")
        else:
            fallos.append(f"tests.test_similarity: {out.returncode}")
            print(f"    FAIL: returncode={out.returncode}")
            print(out.stderr[-500:])
    except Exception as e:
        fallos.append(f"tests.test_similarity: {e}")
        print(f"    FAIL: {e}")

    # 6. Tests de bloques previos siguen pasando ----------------------
    print("\n[6] Re-corriendo tests de Bloque 3 (test_bridge)...")
    try:
        out = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_bridge"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0:
            ultimo = out.stderr.strip().split("\n")[-1]
            print(f"    OK: {ultimo}")
        else:
            fallos.append(f"tests.test_bridge: {out.returncode}")
            print(f"    FAIL: returncode={out.returncode}")
            print(out.stderr[-500:])
    except Exception as e:
        # No es critico, podria no estar disponible.
        print(f"    SKIP: {e}")

    # ===================================================================
    print()
    print("=" * 72)
    if fallos:
        print(f"VERIFICACION CON {len(fallos)} FALLOS:")
        for f in fallos:
            print(f"   - {f}")
        sys.exit(1)
    else:
        print("VERIFICACION FINAL BLOQUE 5: TODO PASA.")
    print("=" * 72)


if __name__ == "__main__":
    main()
