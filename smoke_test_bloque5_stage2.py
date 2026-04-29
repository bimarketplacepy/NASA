"""smoke_test_bloque5_stage2.py
==============================
Smoke test de las funciones puras del Stage 2 (embeddings precompute).

NO toca Neo4j. NO baja el modelo. Solo prueba:
- construir_texto: maneja Nones, campos vacios, y dedupe de espacios.
- hash_dataset: estabilidad bajo reordenamiento, sensibilidad a cambios.
- DATA_DIR / EMBEDDINGS_NPY / EMBEDDINGS_INDEX apuntan a la carpeta
  correcta del proyecto.

Para correr el precompute REAL (que si baja el modelo y conecta a Neo4j):

    python -m ontology_semantic.similarity.embeddings precompute

Uso:

    python smoke_test_bloque5_stage2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from ontology_semantic.similarity.config import load_config
from ontology_semantic.similarity.embeddings import (
    DATA_DIR,
    EMBEDDINGS_INDEX,
    EMBEDDINGS_NPY,
    construir_texto,
    hash_dataset,
)


def main() -> None:
    print("=" * 60)
    print("SMOKE TEST - Bloque 5 - Stage 2 (funciones puras)")
    print("=" * 60)

    cfg = load_config()
    template = cfg.text_template
    print(f"\n[1] Template del YAML: {template!r}")
    assert "{nombre}" in template
    assert "{categoria}" in template

    # --- 2. construir_texto: caso lleno ---------------------------------
    p_lleno = {
        "nombre": "ESFERA DECOR 10X10X10CM",
        "nombre_corto": "Esfera Decorativa",
        "categoria_nombre": "ESFERAS",
        "grupo_nombre": "ADORNOS",
        "pais_origen": "Panama",
    }
    t = construir_texto(template, p_lleno)
    print(f"\n[2] Texto lleno: {t!r}")
    assert "ESFERA DECOR" in t
    assert "ESFERAS" in t
    assert "ADORNOS" in t
    assert "Panama" in t
    assert "  " not in t, f"Hay doble espacio: {t!r}"

    # --- 3. construir_texto: caso con None y vacios --------------------
    p_parcial = {
        "nombre": "BOLA D/AGUA",
        "nombre_corto": None,
        "categoria_nombre": "ESFERAS",
        "grupo_nombre": "",
        "pais_origen": "Brasil",
    }
    t = construir_texto(template, p_parcial)
    print(f"[3] Texto con Nones/vacios: {t!r}")
    assert "BOLA D/AGUA" in t
    assert "ESFERAS" in t
    assert "Brasil" in t
    assert "  " not in t, f"Hay doble espacio: {t!r}"
    # No deberia quedar ". ." flotante
    assert ". ." not in t, f"Hay '. .' (campo vacio entre puntos): {t!r}"

    # --- 4. construir_texto: caso totalmente vacio ---------------------
    p_vacio = {
        "nombre": "",
        "nombre_corto": None,
        "categoria_nombre": None,
        "grupo_nombre": None,
        "pais_origen": "",
    }
    t = construir_texto(template, p_vacio)
    print(f"[4] Texto totalmente vacio: {t!r}")
    # Aceptable que quede algo como "Categoria: Grupo: Pais:" o vacio.
    assert "  " not in t

    # --- 4b. dedup nombre/nombre_corto identicos -----------------------
    p_dup = {
        "nombre": "BOLSA NAVIDEÑA 29570",
        "nombre_corto": "BOLSA NAVIDEÑA 29570",
        "categoria_nombre": "MEDIANO",
        "grupo_nombre": "BOLSAS DECORATIVAS",
        "pais_origen": "Paraguay",
    }
    t = construir_texto(template, p_dup)
    print(f"[4b] Dedup identicos: {t!r}")
    assert t.count("BOLSA NAVIDEÑA 29570") == 1, \
        f"Esperaba 1 ocurrencia, hubo {t.count('BOLSA NAVIDEÑA 29570')}: {t!r}"
    assert ".." not in t

    # --- 4c. dedup nombre_corto subset de nombre + trailing dots -----
    p_subset = {
        "nombre": "BOLSA P/ REGALO NAV. B01 8091",
        "nombre_corto": "BOLSA P/ REGALO NAV.",  # trailing dot + es prefijo
        "categoria_nombre": "BAZAR",
        "grupo_nombre": "BAZAR",
        "pais_origen": "Paraguay",
    }
    t = construir_texto(template, p_subset)
    print(f"[4c] Dedup subset + trailing dot: {t!r}")
    assert "BOLSA P/ REGALO NAV. B01 8091" in t
    # nombre_corto deberia haber sido descartado
    assert t.count("BOLSA P/ REGALO NAV") == 1, \
        f"Esperaba que el subset se descartara: {t!r}"
    assert ".." not in t, f"Hay '..': {t!r}"

    # --- 4d. promocion: nombre es subset de nombre_corto -------------
    p_promo = {
        "nombre": "BOLSA",
        "nombre_corto": "BOLSA NAVIDAD ROJA",
        "categoria_nombre": "BAZAR",
        "grupo_nombre": "BOLSAS",
        "pais_origen": "China",
    }
    t = construir_texto(template, p_promo)
    print(f"[4d] Promocion: {t!r}")
    assert "BOLSA NAVIDAD ROJA" in t

    # --- 5. hash_dataset: estabilidad bajo reordenamiento -------------
    productos = [
        {"sku": "111"}, {"sku": "222"}, {"sku": "333"},
    ]
    textos = ["t1", "t2", "t3"]
    h1 = hash_dataset(productos, textos)
    # Reordenamos a la mitad
    productos_rev = [productos[2], productos[0], productos[1]]
    textos_rev = [textos[2], textos[0], textos[1]]
    h2 = hash_dataset(productos_rev, textos_rev)
    print(f"\n[5] Hash original  : {h1[:16]}...")
    print(f"    Hash reordenado: {h2[:16]}...")
    assert h1 == h2, "El hash deberia ser estable bajo reordenamiento"

    # --- 6. hash_dataset: sensibilidad a cambios ----------------------
    textos_mod = ["t1_modificado", "t2", "t3"]
    h3 = hash_dataset(productos, textos_mod)
    print(f"    Hash con texto modificado: {h3[:16]}...")
    assert h1 != h3, "El hash deberia cambiar si cambia un texto"

    productos_mod = [
        {"sku": "111"}, {"sku": "222"}, {"sku": "444"},  # 333 -> 444
    ]
    h4 = hash_dataset(productos_mod, textos)
    assert h1 != h4, "El hash deberia cambiar si cambia un SKU"
    print(f"    Hash con SKU distinto    : {h4[:16]}...")

    # --- 7. Paths del proyecto ----------------------------------------
    print(f"\n[6] DATA_DIR        = {DATA_DIR}")
    print(f"    EMBEDDINGS_NPY  = {EMBEDDINGS_NPY}")
    print(f"    EMBEDDINGS_INDEX= {EMBEDDINGS_INDEX}")
    assert DATA_DIR.name == "data"
    assert DATA_DIR.exists(), f"data/ no existe en {DATA_DIR}"

    print()
    print("=" * 60)
    print("STAGE 2 (funciones puras): TODO PASA.")
    print("=" * 60)
    print()
    print("Siguiente paso: correr el precompute REAL (baja el modelo,")
    print("conecta a Neo4j, embeddea 4643 productos):")
    print()
    print("    python -m ontology_semantic.similarity.embeddings precompute")
    print()
    print("Es un proceso unico (~5-10 min CPU dependiendo de la maquina).")


if __name__ == "__main__":
    main()
