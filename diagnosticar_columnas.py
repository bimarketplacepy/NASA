"""
diagnosticar_columnas.py
-------------------------
Diagnostica las columnas de PRODUCTOS y PROVEEDORES que estamos pensando
mapear a la ontologia, para saber cuales son confiables y cuales son dead.
Tarea 1 - Bloque 5.7 (validacion).

Para cada columna muestra:
  - Cuantos valores distintos tiene.
  - Top 5 valores mas frecuentes con su porcentaje.
  - Porcentaje de 0 / null / cadena vacia.

Solo lee del subset navideno (cod_sub_seccion=306) para no mezclar con el resto.
Output a diagnostico_columnas.txt.
"""

import os
import warnings
from pathlib import Path
from datetime import datetime

import pyodbc
import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=UserWarning)

OUTPUT = Path(__file__).parent / "diagnostico_columnas.txt"


def conectar():
    return pyodbc.connect(
        f"DRIVER={{{os.getenv('SQLSERVER_DRIVER')}}};"
        f"SERVER={os.getenv('SQLSERVER_HOST')},{os.getenv('SQLSERVER_PORT')};"
        f"DATABASE={os.getenv('SQLSERVER_DATABASE')};"
        f"UID={os.getenv('SQLSERVER_USER')};"
        f"PWD={os.getenv('SQLSERVER_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )


def diagnosticar(df: pd.DataFrame, columna: str) -> str:
    """Devuelve un string con el diagnostico de una columna."""
    s = df[columna]
    total = len(s)
    distintos = s.nunique(dropna=True)
    nulos = s.isna().sum()
    if s.dtype == object:
        vacios = (s.fillna("").astype(str).str.strip() == "").sum()
    else:
        vacios = 0

    # Para columnas numericas tambien queremos saber cuantos son cero
    ceros = 0
    if pd.api.types.is_numeric_dtype(s):
        ceros = (s.fillna(0) == 0).sum()

    top = s.value_counts(dropna=False).head(5)

    lineas = []
    lineas.append(f"--- {columna} ---")
    lineas.append(f"  total: {total:,}  distintos: {distintos:,}  "
                  f"nulos: {nulos:,} ({nulos/total*100:.1f}%)  "
                  f"vacios: {vacios:,} ({vacios/total*100:.1f}%)  "
                  f"ceros: {ceros:,} ({ceros/total*100:.1f}%)")
    lineas.append("  Top 5 valores:")
    for valor, cnt in top.items():
        lineas.append(f"    {repr(valor):40s} -> {cnt:,} ({cnt/total*100:.1f}%)")
    return "\n".join(lineas)


def main():
    load_dotenv()
    conn = conectar()
    print("Conectado. Diagnosticando columnas...\n")

    salida = [f"# Diagnostico de columnas - {datetime.now().isoformat()}\n"]

    def w(s=""):
        salida.append(s)
        print(s)

    # ----------- PRODUCTOS (subset navideños) -----------
    w("=" * 70)
    w("PRODUCTOS (subset navideños cod_sub_seccion=306 con stock)")
    w("=" * 70)

    cols_prod = [
        "pais_origen",
        "UNIDAD",
        "PERECEDERO",
        "dias_validez",
        "PRECIO_COMPRA",
        "PRECIO_COSTO",
        "PRECIO_COSTO_NETO",
        "PRECIO_COSTO_ANT",
        "PRECIO_COMPRA_CIF",
        "PRECIO_VENTA_A",
        "PRECIO_VENTA_B",
        "PRECIO_VENTA_C",
        "peso",
        "Volumen_cc",
        "DESACTIVADO",
        "nuevo",
        "oferta",
    ]

    df_prod = pd.read_sql(f"""
        SELECT DISTINCT
            p.CODIGO,
            p.pais_origen, p.UNIDAD, p.PERECEDERO, p.dias_validez,
            p.PRECIO_COMPRA, p.PRECIO_COSTO, p.PRECIO_COSTO_NETO,
            p.PRECIO_COSTO_ANT, p.PRECIO_COMPRA_CIF,
            p.PRECIO_VENTA_A, p.PRECIO_VENTA_B, p.PRECIO_VENTA_C,
            p.peso, p.Volumen_cc,
            p.DESACTIVADO, p.nuevo, p.oferta
        FROM PRODUCTOS p
        INNER JOIN MOVIMIENTOS_DEPOSITOS md ON md.CODIGO = p.CODIGO
        WHERE p.cod_sub_seccion = 306 AND md.CANTIDAD >= 1
    """, conn)
    w(f"Productos analizados: {len(df_prod):,}\n")

    for c in cols_prod:
        w(diagnosticar(df_prod, c))
        w()

    # ----------- PROVEEDORES (subset que compraron navideños) -----------
    w("=" * 70)
    w("PROVEEDORES (subset que compraron navideños alguna vez)")
    w("=" * 70)

    cols_prov = [
        "PAIS",
        "CIUDAD",
        "EMAIL",
        "TELEFONO_PROVEEDOR",
        "PALZO_ENTREGA",
        "PALZO_PAGO",
        "PORCENTAJE_BONIF",
        "porc_bonif_venta",
        "proveedor_exterior",
        "ACTIVO",
        "dias_estadistica_pedidos",
        "dias_a_reponer_pedidos",
    ]

    df_prov = pd.read_sql("""
        SELECT
            pr.COD_PROVEEDOR,
            pr.PAIS, pr.CIUDAD, pr.EMAIL, pr.TELEFONO_PROVEEDOR,
            pr.PALZO_ENTREGA, pr.PALZO_PAGO,
            pr.PORCENTAJE_BONIF, pr.porc_bonif_venta,
            pr.proveedor_exterior, pr.ACTIVO,
            pr.dias_estadistica_pedidos, pr.dias_a_reponer_pedidos
        FROM PROVEEDORES pr
        WHERE pr.COD_PROVEEDOR IN (
            SELECT DISTINCT c.COD_PROVEEDOR
            FROM COMPRAS c
            INNER JOIN COMPRAS_DET cd ON cd.NRO_REG = c.NRO_REG
            INNER JOIN PRODUCTOS p ON p.CODIGO = cd.CODIGO
            WHERE p.cod_sub_seccion = 306 AND cd.CANTIDAD > 0
        )
    """, conn)
    w(f"Proveedores analizados: {len(df_prov):,}\n")

    for c in cols_prov:
        w(diagnosticar(df_prov, c))
        w()

    conn.close()

    OUTPUT.write_text("\n".join(str(s) for s in salida), encoding="utf-8")
    print(f"\nDiagnostico guardado en: {OUTPUT}")


if __name__ == "__main__":
    main()
