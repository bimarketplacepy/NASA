"""Demo end-to-end de la biblioteca de optimizacion.

Corre los 6 algoritmos sobre SKUs de muestra (con datos del stub de Cris) y
muestra las recomendaciones lado a lado. Sirve para validar que toda la
biblioteca funciona sin necesitar a Abi ni Cris.

Uso:
    python -m optimization.demo
    python -m optimization.demo SKU_001 SKU_004 SKU_NUEVO_999
"""

from __future__ import annotations

import sys

from optimization.algorithms import (
    ALGORITMOS_DISPONIBLES,
    crear_algoritmo,
)
from optimization.schemas import DecisionContext, ProveedorCandidato
from optimization.stubs.deontic_stub import DeonticResolverStub
from optimization.stubs.forecast_stub import obtener_forecast


def _proveedores_demo() -> list[ProveedorCandidato]:
    return [
        ProveedorCandidato(
            proveedor_id="PROV_NAC_01",
            nombre="Norte Festivo SA",
            precio_unitario=12.5,
            moq=100,
            lead_time_dias=7,
            confiabilidad=0.92,
            region="nacional",
        ),
        ProveedorCandidato(
            proveedor_id="PROV_NAC_02",
            nombre="Sur Importadora",
            precio_unitario=11.0,
            moq=50,
            lead_time_dias=10,
            confiabilidad=0.88,
            region="nacional",
        ),
        ProveedorCandidato(
            proveedor_id="PROV_ASIA_01",
            nombre="Shenzhen Bright Decor",
            precio_unitario=8.5,
            moq=500,
            lead_time_dias=45,
            confiabilidad=0.85,
            region="asia",
        ),
    ]


def _build_ctx(sku: str, presupuesto: float = 15000.0, donante: str | None = None) -> DecisionContext:
    forecast = obtener_forecast(sku, sku_donante=donante)
    return DecisionContext(
        sku=sku,
        forecast=forecast,
        proveedores_candidatos=_proveedores_demo(),
        presupuesto_disponible=presupuesto,
        sku_donante=donante,
    )


def _print_header(sku: str, ctx: DecisionContext) -> None:
    f = ctx.forecast
    c = f.caracteristicas_serie
    print()
    print("=" * 76)
    print(f"SKU: {sku}    |    presupuesto: USD {ctx.presupuesto_disponible:,.0f}")
    print("-" * 76)
    print(
        f"  forecast.fuente={f.fuente!r:<22}  donante={f.sku_donante!r}",
    )
    print(
        f"  semanas_efectivas={c.semanas_efectivas:<3}  "
        f"volatilidad={c.volatilidad:.2f}  "
        f"tendencia={c.tendencia_local:+.3f}  "
        f"confianza={f.confianza_global:.2f}",
    )
    print(
        f"  media_total={f.media_demanda:.0f}  p5={f.p5_demanda:.0f}  "
        f"p50={f.p50_demanda:.0f}  p95={f.p95_demanda:.0f}",
    )
    print("=" * 76)


def _print_rec(alg_id: str, ctx: DecisionContext, restricciones) -> None:
    alg = crear_algoritmo(alg_id)
    if not alg.precondiciones(ctx):
        print(f"  [{alg_id:<22}]  NO APLICA (precondiciones no cumplidas)")
        return
    rec = alg.run(ctx, restricciones)
    print(
        f"  [{alg_id:<22}]  cant={rec.cantidad_central:>5}  "
        f"(p5={rec.cantidad_p5:>5}, p95={rec.cantidad_p95:>5})  "
        f"prov={rec.proveedor_sugerido:<14}  "
        f"costo=USD {rec.costo_esperado:>9,.2f}  "
        f"VaR={rec.var_95:>7,.0f}  "
        f"conf={rec.confianza_resultado:.2f}",
    )


def correr_demo(skus: list[str], presupuestos: dict[str, float] | None = None) -> None:
    """Corre la demo sobre una lista de SKUs."""
    presupuestos = presupuestos or {}
    resolver = DeonticResolverStub()

    for sku in skus:
        donante = "SKU_001" if sku.startswith("SKU_NUEVO") else None
        ctx = _build_ctx(sku, presupuesto=presupuestos.get(sku, 15000.0), donante=donante)
        _print_header(sku, ctx)

        bloqueada, razon = resolver.accion_bloqueada(ctx)
        if bloqueada:
            print(f"  >> DECISION BLOQUEADA por la deontica: {razon}")
            continue

        restricciones = resolver.evaluar_restricciones(ctx)
        if restricciones:
            print(f"  Restricciones deonticas detectadas ({len(restricciones)}):")
            for r in restricciones:
                print(f"    - [{r.severidad:<11}] {r.tipo:<28} -> {r.parametros}")
            print()

        for alg_id in ALGORITMOS_DISPONIBLES:
            _print_rec(alg_id, ctx, restricciones)

    print()
    print("=" * 76)
    print(" Demo completada. La eleccion final del algoritmo la hace el dispatcher")
    print(" formal de Abi (con OWL/SHACL/HermiT) leyendo el catalogo OWL cargado.")
    print("=" * 76)


def main() -> None:
    skus_default = ["SKU_001", "SKU_004", "SKU_NUEVO_X1", "SKU_002"]
    presupuestos_default = {
        "SKU_002": 800.0,  # cash-tight para mostrar robust_satisficing
    }
    skus = sys.argv[1:] if len(sys.argv) > 1 else skus_default
    correr_demo(skus, presupuestos_default)


if __name__ == "__main__":
    main()
