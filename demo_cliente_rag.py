"""
demo_cliente_rag.py
--------------------
Demo de uso del RAGClient.
Tarea 1 - Bloque 8.

Corre algunas queries tipicas contra los catalogos PDF indexados,
para mostrar como el resto del equipo (Tarea 4, 5) usa el RAG.
"""

from rag import RAGClient


def imprimir_resultado(r: dict, ancho_texto: int = 250):
    """Helper para imprimir un resultado de forma legible."""
    print(f"  [score={r['score']:.4f}] {r['proveedor_nombre']} ({r['proveedor_id']})")
    print(f"  Fuente: {r['source']}, chunk #{r['chunk_index']}")
    texto = r["texto"].replace("\n", " ")
    if len(texto) > ancho_texto:
        texto = texto[:ancho_texto] + "..."
    print(f"  > {texto}")
    print()


def main():
    with RAGClient() as rag:

        # --- 0. Que catalogos estan indexados ---
        print("=== rag.proveedores_indexados() ===")
        for p in rag.proveedores_indexados():
            print(f"  - {p['proveedor_id']:8s} {p['proveedor_nombre']:30s}  "
                  f"chunks: {p['cantidad_chunks']}")
        print()

        # --- 1. Busqueda semantica abierta sin filtro ---
        print("=" * 70)
        print("=== rag.buscar('cual es el pedido minimo tipico desde China')  k=3 ===")
        print("=" * 70)
        for r in rag.buscar("cual es el pedido minimo tipico desde China", k=3):
            imprimir_resultado(r)

        # --- 2. Busqueda sobre condiciones de pago ---
        print("=" * 70)
        print("=== rag.buscar('condiciones de pago T/T deposit')  k=3 ===")
        print("=" * 70)
        for r in rag.buscar("condiciones de pago T/T deposit", k=3):
            imprimir_resultado(r)

        # --- 3. Busqueda filtrada a un proveedor especifico ---
        print("=" * 70)
        print("=== rag.buscar('lead time')  k=3  proveedor=SUP-01 (DALIAN_MIRO) ===")
        print("=" * 70)
        for r in rag.buscar("lead time", k=3, proveedor_id="SUP-01"):
            imprimir_resultado(r)

        # --- 4. Pregunta semantica creativa: el modelo entiende sinonimos ---
        print("=" * 70)
        print("=== rag.buscar('cuanto tarda el barco desde Asia')  k=3 ===")
        print("(query con sinonimos: 'cuanto tarda' ~ lead time, 'barco' ~ FOB/marítimo)")
        print("=" * 70)
        for r in rag.buscar("cuanto tarda el barco desde Asia", k=3):
            imprimir_resultado(r)

        # --- 5. Filtro por proveedor inexistente ---
        print("=" * 70)
        print("=== rag.buscar('precio')  k=5  proveedor=SUP-99 (no existe) ===")
        print("=" * 70)
        resultados = rag.buscar("precio", k=5, proveedor_id="SUP-99")
        if not resultados:
            print("  (no hay resultados - proveedor no indexado)")
        else:
            for r in resultados:
                imprimir_resultado(r)

    print("\nDemo completa.")


if __name__ == "__main__":
    main()
