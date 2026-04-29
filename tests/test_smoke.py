"""
tests/test_smoke.py
--------------------
Tests de smoke / sanidad de la Tarea 1.
Corre los dos clientes (OntologyClient + RAGClient) contra la data real y
verifica que las respuestas tengan la estructura esperada.

NO hace tests exhaustivos de logica - es un "se prendio bien?" para que
cualquiera del equipo verifique en 10 segundos que el modulo esta sano
en su entorno.

Como correrlo:
    python tests\test_smoke.py

Si todo pasa, vas a ver "OK" al final. Si algo falla, vas a ver el assert
que rompio con detalles.

Pre-requisitos:
  - Neo4j corriendo (docker start neo4j-marketplace)
  - Datos cargados (python ontology\\cargar_datos.py)
  - Catalogos indexados (python rag\\ingesta.py)
"""

import sys
from pathlib import Path

# Permitir imports desde la raiz del proyecto cuando el script se corre
# directamente desde tests/
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from ontology import OntologyClient
from rag import RAGClient


def test_ontology_smoke():
    print("\n--- TEST: OntologyClient ---")
    with OntologyClient() as ont:

        # 1. Hay categorias y productos
        cats = ont.categorias()
        assert len(cats) > 0, "No hay categorias cargadas"
        print(f"  OK  {len(cats)} categorias en ontologia")

        # 2. Tomar un sku de muestra y verificar estructura
        muestra = ont.productos_en_categoria(cats[0]["id"], limit=1)
        assert muestra, f"Categoria {cats[0]['id']} sin productos"
        sku = muestra[0]["sku"]

        # 3. producto() devuelve la jerarquia completa
        p = ont.producto(sku)
        assert p is not None, f"producto({sku!r}) devolvio None"
        for campo in ["sku", "nombre", "categoria", "grupo", "subseccion", "seccion",
                      "en_stock", "cantidad_stock", "precio_costo"]:
            assert campo in p, f"producto() sin campo '{campo}'"
        assert p["categoria"] is not None, "producto sin categoria"
        assert p["grupo"] is not None, "producto sin grupo"
        print(f"  OK  producto({sku!r}) trae jerarquia completa "
              f"({p['categoria']['nombre']} -> {p['grupo']['nombre']})")

        # 4. categoria_de_sku() coincide con producto()
        c = ont.categoria_de_sku(sku)
        assert c is not None
        assert c["id"] == p["categoria"]["id"], "categoria_de_sku no coincide con producto"
        assert c["cantidad_productos"] > 0, "categoria sin productos"
        print(f"  OK  categoria_de_sku coincidente, "
              f"{c['cantidad_productos']} productos en la categoria")

        # 5. proveedores_de_sku() devuelve estructura coherente
        provs = ont.proveedores_de_sku(sku)
        # OK que haya 0 (cold-start) o muchos
        if provs:
            for campo in ["id", "nombre", "ultima_fecha_compra", "ultimo_precio_pyg"]:
                assert campo in provs[0], f"proveedor sin campo '{campo}'"
            print(f"  OK  proveedores_de_sku({sku!r}) -> {len(provs)} proveedor(es)")
        else:
            print(f"  OK  proveedores_de_sku({sku!r}) -> 0 (cold-start, valido)")

        # 6. productos_a_reponer() devuelve productos sin stock
        a_reponer = ont.productos_a_reponer(limit=3)
        if a_reponer:
            print(f"  OK  productos_a_reponer -> {len(a_reponer)} candidato(s)")
        else:
            print(f"  OK  productos_a_reponer -> 0 (no hay candidatos a restock)")

        # 7. eventos_proximos() funciona
        eventos = ont.eventos_proximos(dias=400)
        assert len(eventos) > 0, "No hay eventos en 400 dias"
        for e in eventos:
            assert e["dias_hasta_evento"] >= 0, "evento con dias negativos"
        print(f"  OK  eventos_proximos -> {len(eventos)} eventos en proximos 400 dias")


def test_rag_smoke():
    print("\n--- TEST: RAGClient ---")
    with RAGClient() as rag:

        # 1. Hay catalogos indexados
        provs = rag.proveedores_indexados()
        assert len(provs) > 0, "No hay catalogos indexados en ChromaDB"
        total_chunks = sum(p["cantidad_chunks"] for p in provs)
        print(f"  OK  {len(provs)} catalogo(s) indexado(s), {total_chunks} chunks totales")

        # 2. buscar() devuelve resultados con estructura coherente
        resultados = rag.buscar("MOQ pedido minimo", k=3)
        assert resultados, "buscar() devolvio lista vacia"
        for r in resultados:
            for campo in ["texto", "score", "proveedor_id", "proveedor_nombre", "source"]:
                assert campo in r, f"resultado sin campo '{campo}'"
            assert 0 <= r["score"] <= 1, f"score fuera de [0,1]: {r['score']}"
        print(f"  OK  buscar('MOQ') -> {len(resultados)} resultados, "
              f"score top = {resultados[0]['score']:.3f}")

        # 3. Filtro por proveedor existente devuelve solo de ese proveedor
        algun_id = provs[0]["proveedor_id"]
        filtrados = rag.buscar("precio", k=5, proveedor_id=algun_id)
        for r in filtrados:
            assert r["proveedor_id"] == algun_id, f"filtro no respetado: {r['proveedor_id']}"
        print(f"  OK  filtro por {algun_id} respetado en {len(filtrados)} resultados")

        # 4. Filtro por proveedor inexistente devuelve []
        vacio = rag.buscar("precio", k=5, proveedor_id="SUP-NUNCA-EXISTIO")
        assert vacio == [], "filtro por proveedor inexistente no devolvio []"
        print(f"  OK  proveedor inexistente -> [] correctamente")

        # 5. Resultados ordenados por score descendente
        resultados = rag.buscar("lead time", k=5)
        scores = [r["score"] for r in resultados]
        assert scores == sorted(scores, reverse=True), "resultados no estan ordenados"
        print(f"  OK  resultados ordenados por score descendente")


def main():
    print("=" * 60)
    print("Tests de smoke - Tarea 1 (Ontologia + RAG)")
    print("=" * 60)
    try:
        test_ontology_smoke()
        test_rag_smoke()
    except AssertionError as e:
        print(f"\n!!! TEST FALLO: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n!!! ERROR INESPERADO: {type(e).__name__}: {e}")
        sys.exit(1)
    print("\n" + "=" * 60)
    print("TODOS LOS TESTS OK")
    print("=" * 60)


if __name__ == "__main__":
    main()
