"""
Genera CSV en data/ontology_neo4j/ a partir del catalogo sintetico (data/*.csv)
para poder ejecutar ontology/cargar_datos.py sin el export Pegasus.

Ejecutar desde la raiz del proyecto NASA:
    python scripts/build_ontology_neo4j_csvs.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "ontology_neo4j"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    cat_ml = pd.read_csv(DATA / "categorias.csv")
    catalog = pd.read_csv(DATA / "catalogo_productos.csv")
    inv = pd.read_csv(DATA / "inventario_actual.csv")
    prov = pd.read_csv(DATA / "proveedores.csv")
    rel = pd.read_csv(DATA / "relacion_producto_proveedor.csv")
    evt = pd.read_csv(DATA / "eventos_comerciales.csv")

    pd.DataFrame(
        [{"id": "SEC_NAV", "nombre": "Navidad y temporada"}]
    ).to_csv(OUT / "secciones.csv", index=False)

    pd.DataFrame(
        [
            {
                "id": "SS_NAV_GEN",
                "nombre": "Linea general",
                "seccion_id": "SEC_NAV",
            }
        ]
    ).to_csv(OUT / "subsecciones.csv", index=False)

    grupos_rows = []
    for _, row in cat_ml.iterrows():
        cid = str(row["categoria_id"])
        grupos_rows.append(
            {
                "id": f"GRP_{cid}",
                "nombre": f"Grupo {row['nombre'][:60]}",
                "subseccion_id": "SS_NAV_GEN",
            }
        )
    pd.DataFrame(grupos_rows).to_csv(OUT / "grupos.csv", index=False)

    cat_onto = []
    for _, row in cat_ml.iterrows():
        cid = str(row["categoria_id"])
        cat_onto.append(
            {
                "id": cid,
                "nombre": str(row["nombre"]),
                "grupo_id": f"GRP_{cid}",
            }
        )
    pd.DataFrame(cat_onto).to_csv(OUT / "categorias.csv", index=False)

    catalog = catalog.merge(inv, on="sku", how="left")
    catalog["cantidad_stock"] = catalog["inventario_actual"].fillna(0).astype(int)
    catalog["perecedero"] = catalog["perecedero"].map(
        lambda x: "true" if str(x).lower() in ("1", "true", "yes") else "false"
    )

    productos = pd.DataFrame(
        {
            "sku": catalog["sku"],
            "codigo_barras": catalog["sku"],
            "nombre": catalog["nombre"],
            "nombre_corto": catalog["nombre"].str[:48],
            "unidad": "UN",
            "pais_origen": "Paraguay",
            "precio_costo": (catalog["precio_referencia"] * 0.65).round(2),
            "perecedero": catalog["perecedero"],
            "cantidad_stock": catalog["cantidad_stock"],
            "categoria_id": catalog["categoria_id"],
        }
    )
    productos.to_csv(OUT / "productos.csv", index=False)

    precios = pd.DataFrame(
        {
            "sku": catalog["sku"],
            "precio_venta_actual": catalog["precio_referencia"],
            "fecha_ultima_compra": "2025-06-01 10:00:00",
            "fecha_ultima_venta": "2025-11-15 12:00:00",
            "fecha_ultima_actualizacion": "2026-01-10 08:00:00",
            "fecha_alta": "2024-01-01 00:00:00",
        }
    )
    precios.to_csv(OUT / "precios_venta.csv", index=False)

    prov_out = pd.DataFrame(
        {
            "id": prov["proveedor_id"],
            "nombre": prov["nombre"],
            "ruc": "",
            "pais": prov["pais"],
            "email": prov["email"],
            "telefono": prov["telefono"],
            "proveedor_exterior": prov["pais"]
            .astype(str)
            .str.strip()
            .ne("Paraguay")
            .map(lambda x: "true" if x else "false"),
        }
    )
    prov_out.to_csv(OUT / "proveedores.csv", index=False)

    rel_out = pd.DataFrame(
        {
            "sku": rel["sku"],
            "proveedor_id": rel["proveedor_id"],
            "ultima_fecha_compra": "2025-10-01 09:00:00",
            "ultimo_precio_pyg": (rel["precio_unitario"].astype(float) * 7500).round(0),
            "ultima_cantidad": rel["moq"].clip(upper=500).astype(int),
            "total_cantidad_historica": (rel["moq"].astype(int) * 12).clip(upper=50000),
            "total_lineas_compra": 4,
        }
    )
    rel_out.to_csv(OUT / "relaciones_comerciales.csv", index=False)

    evt_out = pd.DataFrame(
        {
            "id": evt["evento_id"],
            "nombre": evt["nombre"],
            "fecha": "2026-11-28",
            "tipo": "promocion",
        }
    )
    evt_out.to_csv(OUT / "eventos_comerciales.csv", index=False)

    print(f"OK: CSV ontologia Neo4j en {OUT} ({len(list(OUT.glob('*.csv')))} archivos)")


if __name__ == "__main__":
    main()
