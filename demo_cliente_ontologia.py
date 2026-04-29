"""
demo_cliente_ontologia.py
--------------------------
Demo de uso del OntologyClient.
Tarea 1 - Bloque 6.

Corre los metodos publicos del cliente contra la ontologia real cargada,
asi cualquiera del equipo (o vos misma para verificar) ve como se usa.
"""

from ontology import OntologyClient


def imprimir_dict(d, indent=2):
    """Imprime un dict con identacion legible."""
    if d is None:
        print(" " * indent + "(None)")
        return
    for k, v in d.items():
        print(" " * indent + f"{k}: {v}")


def main():
    with OntologyClient() as ont:

        # Elegir un SKU dinamicamente para que la demo siempre funcione
        # (independiente del estado actual de la ontologia). Tomamos el
        # primero de la categoria ESFERAS (6253), que sabemos que existe.
        muestra = ont.productos_en_categoria(6253, limit=1)
        if not muestra:
            print("No hay productos en la ontologia. Cargaste los datos?")
            return
        SKU_DEMO = muestra[0]["sku"]
        print(f"(SKU usado para la demo: {SKU_DEMO} - elegido dinamicamente)\n")

        # --- 1. Ficha completa del producto ---
        print(f"\n=== ont.producto({SKU_DEMO!r}) ===")
        imprimir_dict(ont.producto(SKU_DEMO))

        # --- 2. Categoria del SKU + agregados (cold-start) ---
        print(f"\n=== ont.categoria_de_sku({SKU_DEMO!r}) ===")
        imprimir_dict(ont.categoria_de_sku(SKU_DEMO))

        # --- 3. Proveedores que suministran ese SKU ---
        print(f"\n=== ont.proveedores_de_sku({SKU_DEMO!r}) ===")
        proveedores = ont.proveedores_de_sku(SKU_DEMO)
        print(f"  Total: {len(proveedores)} proveedor(es)")
        for prov in proveedores[:3]:
            print(f"\n  - {prov.get('nombre')} ({prov.get('pais')})")
            print(f"    Ultima compra: {prov.get('ultima_fecha_compra')}")
            print(f"    Ultimo precio: {prov.get('ultimo_precio_pyg'):,} PYG"
                  if prov.get('ultimo_precio_pyg') else "    Ultimo precio: -")
            print(f"    Total historico: {prov.get('total_cantidad_historica')} unidades en "
                  f"{prov.get('total_lineas_compra')} lineas de compra")

        # --- 4. Productos a reponer (sin stock pero activos) ---
        print(f"\n=== ont.productos_a_reponer(limit=5) ===")
        for p in ont.productos_a_reponer(limit=5):
            print(f"  - {p.get('sku')} | {p.get('nombre')} | "
                  f"categoria: {p.get('categoria')} | "
                  f"ultima venta: {p.get('fecha_ultima_venta')}")

        # --- 5. Top categorias ---
        print(f"\n=== ont.categorias() (top 10) ===")
        for c in ont.categorias()[:10]:
            print(f"  - [{c['id']}] {c['nombre']:25s}  "
                  f"productos: {c['cantidad_productos']:4d}  "
                  f"en stock: {c['cantidad_en_stock']:4d}")

        # --- 6. Productos en una categoria ---
        print(f"\n=== ont.productos_en_categoria(6253, limit=5)  # ESFERAS ===")
        for p in ont.productos_en_categoria(6253, limit=5):
            print(f"  - {p['sku']} | {p['nombre']:40s} | "
                  f"stock: {p['cantidad_stock']:5.0f}  | "
                  f"precio venta: {p.get('precio_venta_actual')}")

        # --- 7. Proveedores similares (alternativos) ---
        # NOTA: cambiar por un proveedor que sepas que existe
        PROV_ID_DEMO = 364  # NORITEX
        print(f"\n=== ont.proveedores_similares({PROV_ID_DEMO}, limit=5)  # NORITEX ===")
        for prov in ont.proveedores_similares(PROV_ID_DEMO, limit=5):
            print(f"  - [{prov['id']}] {prov['nombre']:35s}  "
                  f"({prov['pais']})  "
                  f"categorias compartidas: {prov['categorias_en_comun']}")

        # --- 8. Eventos proximos ---
        print(f"\n=== ont.eventos_proximos(dias=365) ===")
        for e in ont.eventos_proximos(dias=365):
            print(f"  - {e['fecha']}  {e['nombre']:30s}  "
                  f"(en {e['dias_hasta_evento']} dias)")

        # --- 9. Sustitutos (placeholder por ahora) ---
        print(f"\n=== ont.sustitutos_de_sku({SKU_DEMO!r}) ===")
        print(f"  -> {ont.sustitutos_de_sku(SKU_DEMO)} (todavia no se llena, ver docstring)")

    print("\nDemo completa.")


if __name__ == "__main__":
    main()
