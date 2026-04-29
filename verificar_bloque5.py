"""verificar_bloque5.py
======================
Script READ-ONLY para verificar pre-condiciones del Bloque 5 (Motor de
Similaridad Multidimensional).

No modifica nada en Neo4j. Solo reporta el estado actual:
- Conteo de productos.
- Properties presentes en el label Producto (con cobertura % por property).
- Properties presentes en la relacion SUMINISTRADO_POR.
- Si ya existen aristas :SIMILAR_A (idempotencia).
- Existencia de campos clave para similitud: nombre, descripcion,
  pais_origen, color, material, categoria_id.

Uso desde la raiz del proyecto:

    python verificar_bloque5.py

Salida: tabla legible por consola. Pegamela al chat.
"""

from __future__ import annotations

import os
from collections import Counter

from dotenv import load_dotenv
from neo4j import GraphDatabase


def _conexion():
    load_dotenv()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        raise SystemExit(
            "Faltan NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD en .env"
        )
    return GraphDatabase.driver(uri, auth=(user, password))


def main() -> None:
    driver = _conexion()
    print("=" * 72)
    print("VERIFICACION BLOQUE 5 - read-only")
    print("=" * 72)

    with driver.session() as s:
        # --- 1. Conteo y existencia ---------------------------------------
        n_prod = s.run("MATCH (p:Producto) RETURN count(p) AS n").single()["n"]
        n_cat = s.run("MATCH (c:Categoria) RETURN count(c) AS n").single()["n"]
        n_grp = s.run("MATCH (g:Grupo) RETURN count(g) AS n").single()["n"]
        n_prov = s.run("MATCH (p:Proveedor) RETURN count(p) AS n").single()["n"]
        n_simil = s.run(
            "MATCH ()-[r:SIMILAR_A]->() RETURN count(r) AS n"
        ).single()["n"]
        print(f"\n[1] Conteos basicos:")
        print(f"    Producto         : {n_prod}")
        print(f"    Categoria        : {n_cat}")
        print(f"    Grupo            : {n_grp}")
        print(f"    Proveedor        : {n_prov}")
        print(f"    SIMILAR_A (existentes): {n_simil}")

        # --- 2. Properties en Producto con cobertura ----------------------
        # Sample de 200 productos para ver cobertura por property.
        # Nota: no usamos CALL db.schema.nodeTypeProperties() porque mezcla
        # tipos. Vamos directo a contar presencia por key.
        keys_query = """
        MATCH (p:Producto)
        WITH p LIMIT 1000
        UNWIND keys(p) AS k
        RETURN k AS key, count(*) AS cnt
        ORDER BY cnt DESC
        """
        print(f"\n[2] Properties en :Producto (sample 1000 productos):")
        print(f"    {'property':<35} {'cobertura':>10}")
        print(f"    {'-' * 35} {'-' * 10}")
        for r in s.run(keys_query):
            cov = r["cnt"] / 10.0  # /1000 * 100 = /10
            print(f"    {r['key']:<35} {cov:>9.1f}%")

        # --- 3. Verificar existencia de campos clave por nombre ----------
        clave = ["nombre", "nombre_corto", "descripcion", "pais_origen",
                 "color", "material", "categoria_id", "perecedero",
                 "unidad", "precio_costo"]
        print(f"\n[3] Existencia de campos clave para similitud:")
        for k in clave:
            r = s.run(
                f"MATCH (p:Producto) WHERE p.`{k}` IS NOT NULL "
                f"RETURN count(p) AS n LIMIT 1"
            ).single()
            estado = f"presente en {r['n']:>5} productos" if r["n"] else "AUSENTE"
            print(f"    {k:<20} -> {estado}")

        # --- 4. Properties en SUMINISTRADO_POR ---------------------------
        keys_rel_query = """
        MATCH ()-[r:SUMINISTRADO_POR]->()
        WITH r LIMIT 1000
        UNWIND keys(r) AS k
        RETURN k AS key, count(*) AS cnt
        ORDER BY cnt DESC
        """
        print(f"\n[4] Properties en :SUMINISTRADO_POR (sample 1000 aristas):")
        print(f"    {'property':<35} {'cobertura':>10}")
        print(f"    {'-' * 35} {'-' * 10}")
        for r in s.run(keys_rel_query):
            cov = r["cnt"] / 10.0
            print(f"    {r['key']:<35} {cov:>9.1f}%")

        # --- 5. Sample de 3 productos para ver estructura real ----------
        print(f"\n[5] Sample de 3 productos (todas las props):")
        sample = s.run(
            "MATCH (p:Producto) RETURN p AS prod LIMIT 3"
        )
        for i, rec in enumerate(sample, 1):
            d = dict(rec["prod"])
            print(f"\n    --- Producto sample #{i} ---")
            for k, v in d.items():
                v_short = str(v)[:80] + "..." if len(str(v)) > 80 else str(v)
                print(f"      {k:<35} = {v_short}")

        # --- 6. Texto disponible: longitudes -----------------------------
        print(f"\n[6] Longitud media de campos textuales:")
        for k in ["nombre", "nombre_corto", "descripcion"]:
            r = s.run(
                f"MATCH (p:Producto) WHERE p.`{k}` IS NOT NULL "
                f"RETURN avg(size(toString(p.`{k}`))) AS avg_len, "
                f"min(size(toString(p.`{k}`))) AS min_len, "
                f"max(size(toString(p.`{k}`))) AS max_len, "
                f"count(p) AS n"
            ).single()
            if r["n"]:
                print(f"    {k:<20}: n={r['n']:>5}, "
                      f"avg={r['avg_len']:.1f}, "
                      f"min={r['min_len']}, max={r['max_len']}")
            else:
                print(f"    {k:<20}: AUSENTE")

    driver.close()
    print("\n" + "=" * 72)
    print("Verificacion completa. Pegale la salida al chat.")
    print("=" * 72)


if __name__ == "__main__":
    main()
