"""diag_sku_type.py - diagnostico del tipo del campo sku en Neo4j.

NO modifica nada. Lee tres samples y reporta:
- Tipo Python que devuelve el driver para p.sku.
- Si MATCH ... {sku: $sku} con sku string funciona.
- Si MATCH ... {sku: $sku} con sku int funciona.

Nos dice definitivamente que tipo esta guardado y por que la v1
producto("17629") devuelve None.
"""

from __future__ import annotations

from ontology import OntologyClient


def main() -> None:
    print("=" * 60)
    print("DIAGNOSTICO TIPO DE sku EN NEO4J")
    print("=" * 60)

    with OntologyClient() as ont:
        with ont.driver.session() as s:
            # 1. Ver el tipo Python que devuelve el driver
            print("\n[1] Tipos de p.sku en los primeros 5 productos:")
            r = s.run("MATCH (p:Producto) RETURN p.sku AS sku LIMIT 5")
            for rec in r:
                v = rec["sku"]
                print(f"    valor={v!r:<15} type={type(v).__name__}")

            # 2. Ver el SKU 17629 directo
            print("\n[2] SKU 17629 con varias estrategias de match:")

            # 2a. Como string literal en Cypher
            r = s.run("MATCH (p:Producto) WHERE p.sku = '17629' RETURN p.sku LIMIT 1").single()
            print(f"    p.sku = '17629'      -> {r}")

            # 2b. Como int literal en Cypher
            r = s.run("MATCH (p:Producto) WHERE p.sku = 17629 RETURN p.sku LIMIT 1").single()
            print(f"    p.sku = 17629        -> {r}")

            # 2c. Con toString
            r = s.run("MATCH (p:Producto) WHERE toString(p.sku) = '17629' RETURN p.sku LIMIT 1").single()
            print(f"    toString(p.sku)='17629' -> {r}")

            # 2d. Pattern con parametro string
            r = s.run("MATCH (p:Producto {sku: $sku}) RETURN p.sku LIMIT 1",
                      sku="17629").single()
            print(f"    {{sku: $sku}}, $sku='17629'  -> {r}")

            # 2e. Pattern con parametro int
            r = s.run("MATCH (p:Producto {sku: $sku}) RETURN p.sku LIMIT 1",
                      sku=17629).single()
            print(f"    {{sku: $sku}}, $sku=17629    -> {r}")

            # 3. Distribucion de tipos en todo el catalogo
            print("\n[3] Distribucion de tipos de sku en los 4643 productos:")
            # Con APOC seria limpio pero podemos hacerlo manual.
            r = s.run("""
                MATCH (p:Producto)
                WITH apoc.meta.cypher.type(p.sku) AS t, count(*) AS n
                RETURN t, n ORDER BY n DESC
            """).data() if False else None
            # APOC podria no estar siempre. Mejor sample manual:
            tipos = {}
            r = s.run("MATCH (p:Producto) RETURN p.sku AS sku")
            for rec in r:
                t = type(rec["sku"]).__name__
                tipos[t] = tipos.get(t, 0) + 1
            for t, n in sorted(tipos.items(), key=lambda x: -x[1]):
                print(f"    {t}: {n}")


if __name__ == "__main__":
    main()
