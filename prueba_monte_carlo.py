"""
prueba_monte_carlo.py
----------------------
Prueba end-to-end del MonteCarloSimulator con datos reales del grafo.

Construye una cartera de 3 SKUs navidenos, pide forecasts via
ForecastService y corre el Monte Carlo deontico con 3 restricciones
sinteticas (presupuesto + MOQ + perecedero).

Uso:
    cd C:\\AITinketers\\Tinketers
    venv\\Scripts\\activate
    python prueba_monte_carlo.py
"""

import asyncio

from ontology_semantic.client_v2 import OntologyClientV2
from forecast import (
    ForecastService,
    Item,
    MonteCarloSimulator,
    Restriccion,
)


# SKUs con historial confirmado (sacados de la query del browser):
SKUS_CARTERA = [
    {"sku": "118582", "nombre": "SERVILLETERO LINEA ESPECIAL",     "qty": 200},
    {"sku": "254647", "nombre": "INDIVIDUALES NAVIDENOS DORADO",   "qty": 100},
    {"sku": "254651", "nombre": "INDIVIDUALES NAVIDENOS AZUL",     "qty": 100},
]

HORIZONTE_SEMANAS = 8
N_SIMS = 10_000


async def main() -> None:
    print("=" * 70)
    print("PRUEBA MONTE CARLO DEONTICO - Tarea 3")
    print("=" * 70)

    ont = OntologyClientV2()
    forecast_svc = ForecastService(ont_client=ont)
    simulator = MonteCarloSimulator()

    # 1) Pedir forecasts de cada SKU.
    print(f"\n--- Forecasts (horizonte = {HORIZONTE_SEMANAS} semanas) ---")
    forecasts = {}
    items = []
    for sku_info in SKUS_CARTERA:
        sku = sku_info["sku"]
        fr = await forecast_svc.forecast(sku=sku, semanas_adelante=HORIZONTE_SEMANAS)
        forecasts[sku] = fr
        print(
            f"  {sku} ({sku_info['nombre'][:30]:<30}) "
            f"fuente={fr.fuente:<18} "
            f"sem_prop={fr.semanas_de_historia_propia:>3}  "
            f"conf={fr.confianza_global:.3f}  "
            f"media_total={sum(fr.media):>7.1f}"
        )

        # Buscar precios reales del grafo via OntologyClient.
        prod = ont.producto(sku) or {}
        precio_costo = float(prod.get("precio_costo") or 1000.0)
        precio_venta = float(prod.get("precio_venta_actual") or precio_costo * 2)

        items.append(Item(
            sku=sku,
            cantidad_comprada=sku_info["qty"],
            precio_costo_pyg=precio_costo,
            precio_venta_pyg=precio_venta,
            perecedero=bool(prod.get("perecedero", False)),
            dias_validez=None,  # productos navidenos no son perecederos
            cantidad_minima_proveedor=50,  # MOQ sintetico para probar
        ))

    # 2) Costo total para calibrar presupuesto.
    costo_total = sum(it.cantidad_comprada * it.precio_costo_pyg for it in items)
    print(f"\nCosto total cartera: {costo_total:>12,.0f} PYG")

    # 3) Tres escenarios de restricciones para ver el filtrado.
    escenarios = [
        ("SIN restricciones", []),
        ("Presupuesto holgado (1.5x costo)", [
            Restriccion(
                tipo="presupuesto_maximo_pyg",
                parametros={"presupuesto_pyg": costo_total * 1.5},
                fuente_norma_id="N-PRESU-001",
            ),
        ]),
        ("Presupuesto ajustado (0.5x costo)", [
            Restriccion(
                tipo="presupuesto_maximo_pyg",
                parametros={"presupuesto_pyg": costo_total * 0.5},
                fuente_norma_id="N-PRESU-001",
            ),
        ]),
        ("MOQ + presupuesto holgado", [
            Restriccion(
                tipo="cantidad_minima_proveedor",
                fuente_norma_id="N-MOQ-001",
            ),
            Restriccion(
                tipo="presupuesto_maximo_pyg",
                parametros={"presupuesto_pyg": costo_total * 2},
                fuente_norma_id="N-PRESU-001",
            ),
        ]),
    ]

    print(f"\n--- Corridas Monte Carlo (n_sims = {N_SIMS:,}) ---")
    for nombre, restr in escenarios:
        print(f"\n[{nombre}]")
        import time
        t0 = time.time()
        r = await simulator.simular(
            items=items, forecasts=forecasts, restricciones=restr, n_sims=N_SIMS,
        )
        elapsed_ms = (time.time() - t0) * 1000

        print(f"  Tiempo: {elapsed_ms:.0f} ms (limit spec: 5000 ms)")
        print(f"  Validos:    {r.n_validos:>6,} / {r.n_simulaciones:,}")
        print(f"  Descartados:{r.n_descartados:>6,}")
        print(f"  Violaciones por norma: {dict(r.violaciones_por_norma)}")
        print(f"  Costo cartera (fijo): {r.costo_total_pyg:>12,.0f} PYG")
        if r.n_validos > 0:
            print(
                f"  Ingresos (PYG):  "
                f"p5={r.ingresos_total_p5:>11,.0f}  "
                f"media={r.ingresos_total_media:>11,.0f}  "
                f"p95={r.ingresos_total_p95:>11,.0f}"
            )
            margen = r.ingresos_total_media - r.costo_total_pyg
            margen_pct = (margen / r.costo_total_pyg * 100) if r.costo_total_pyg > 0 else 0
            print(f"  Margen esperado: {margen:>12,.0f} PYG ({margen_pct:+.1f}%)")
        else:
            print("  No hay escenarios validos -> cartera bloqueada")

    ont.close()
    print("\n" + "=" * 70)
    print("Listo.")


if __name__ == "__main__":
    asyncio.run(main())
