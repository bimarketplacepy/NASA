"""
explorar_pegasus.py
--------------------
Exploracion enfocada del esquema de Pegasus (Marketplace SA).
Tarea 1 - Bloque 5.5.

Objetivos:
  1. Validar la query de navideños (cod_sub_seccion=306 con stock>=1).
  2. Inspeccionar columnas de las tablas core que ya conocemos:
     PRODUCTOS, MOVIMIENTOS_DEPOSITOS, VENTAS, VENTAS_DET.
  3. Descubrir tablas relacionadas que necesitamos para la ontologia:
     proveedores, secciones/sub_secciones, depositos, marcas.
  4. Guardar todo en un archivo de texto para compartir.

Es 100% solo lectura (SELECT) y los samples usan TOP para no saturar
la base.
"""

import os
import warnings
from pathlib import Path
from datetime import datetime

import pyodbc
import pandas as pd
from dotenv import load_dotenv

# Silenciar el warning de pandas sobre conexiones que no son SQLAlchemy
warnings.filterwarnings("ignore", category=UserWarning)

# Tablas core que sabemos que importan
TABLAS_OBJETIVO = [
    "PRODUCTOS",
    "MOVIMIENTOS_DEPOSITOS",
    "VENTAS",
    "VENTAS_DET",
]

# Patrones para descubrir tablas relacionadas
PATRONES_BUSQUEDA = [
    "PROVEEDOR", "SUPLIDOR",
    "SECCION", "SUB_SECCION", "CATEGORIA", "RUBRO", "FAMILIA", "LINEA",
    "DEPOSITO", "ALMACEN",
    "SUCURSAL", "TIENDA",
    "MARCA",
    "COMPRA", "ORDEN_COMPRA",
]

OUTPUT_FILE = Path(__file__).parent / "exploracion_pegasus.txt"


def conectar():
    driver = os.getenv("SQLSERVER_DRIVER")
    host = os.getenv("SQLSERVER_HOST")
    port = os.getenv("SQLSERVER_PORT")
    database = os.getenv("SQLSERVER_DATABASE")
    user = os.getenv("SQLSERVER_USER")
    password = os.getenv("SQLSERVER_PASSWORD")

    cadena = (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(cadena)


def main():
    load_dotenv()
    print(f"Conectando a SQL Server (Pegasus)...")
    conn = conectar()
    print(f"Conectado. Volcando exploracion en: {OUTPUT_FILE}\n")

    salida = []

    def escribir(linea: str = ""):
        salida.append(linea)
        print(linea)

    escribir(f"# Exploracion Pegasus - {datetime.now().isoformat()}")
    escribir()

    # 1. Validacion de la query de navideños
    escribir("=" * 70)
    escribir("1) VALIDACION DE QUERY DE NAVIDENOS")
    escribir("=" * 70)
    try:
        df_count = pd.read_sql("""
            SELECT COUNT(DISTINCT p.CODIGO) AS productos_distintos_en_stock
            FROM PRODUCTOS p
            JOIN MOVIMIENTOS_DEPOSITOS md ON md.CODIGO = p.CODIGO
            WHERE p.cod_sub_seccion = '306'
              AND md.CANTIDAD >= 1
        """, conn)
        escribir(df_count.to_string(index=False))
    except Exception as e:
        escribir(f"ERROR: {e}")
    escribir()

    # 2. Cuantos productos navidenos hay en TOTAL (con o sin stock)
    escribir("=" * 70)
    escribir("2) NAVIDENOS TOTALES (con o sin stock)")
    escribir("=" * 70)
    try:
        df_total = pd.read_sql("""
            SELECT COUNT(*) AS total_navidenos
            FROM PRODUCTOS
            WHERE cod_sub_seccion = '306'
        """, conn)
        escribir(df_total.to_string(index=False))
    except Exception as e:
        escribir(f"ERROR: {e}")
    escribir()

    # 3. Columnas + muestra de las 4 tablas core
    for tabla in TABLAS_OBJETIVO:
        escribir("=" * 70)
        escribir(f"3) ESTRUCTURA DE TABLA: {tabla}")
        escribir("=" * 70)

        # Columnas
        try:
            cols = pd.read_sql(f"""
                SELECT COLUMN_NAME AS columna, DATA_TYPE AS tipo,
                       CHARACTER_MAXIMUM_LENGTH AS largo, IS_NULLABLE AS nullable
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = '{tabla}'
                ORDER BY ORDINAL_POSITION
            """, conn)
            escribir(f"Columnas ({len(cols)}):")
            escribir(cols.to_string(index=False))
        except Exception as e:
            escribir(f"  ERROR leyendo columnas: {e}")
        escribir()

        # Muestra
        try:
            sample = pd.read_sql(f"SELECT TOP 3 * FROM {tabla}", conn)
            escribir(f"Muestra de 3 filas de {tabla}:")
            escribir(sample.to_string(index=False, max_colwidth=40))
        except Exception as e:
            escribir(f"  ERROR leyendo muestra: {e}")
        escribir()

    # 4. Muestra DE NAVIDENOS especificamente
    escribir("=" * 70)
    escribir("4) MUESTRA DE 5 PRODUCTOS NAVIDENOS")
    escribir("=" * 70)
    try:
        df_nav = pd.read_sql("""
            SELECT TOP 5 *
            FROM PRODUCTOS
            WHERE cod_sub_seccion = '306'
        """, conn)
        escribir(df_nav.to_string(index=False, max_colwidth=40))
    except Exception as e:
        escribir(f"ERROR: {e}")
    escribir()

    # 5. Buscar tablas relacionadas (proveedor, seccion, etc)
    escribir("=" * 70)
    escribir("5) BUSQUEDA DE TABLAS RELACIONADAS")
    escribir("=" * 70)
    try:
        condiciones = " OR ".join([f"TABLE_NAME LIKE '%{p}%'" for p in PATRONES_BUSQUEDA])
        df_tablas = pd.read_sql(f"""
            SELECT TABLE_SCHEMA AS esquema, TABLE_NAME AS tabla
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE' AND ({condiciones})
            ORDER BY TABLE_NAME
        """, conn)
        escribir(f"Tablas que matchean patrones (proveedor/seccion/deposito/etc):")
        escribir(df_tablas.to_string(index=False))
    except Exception as e:
        escribir(f"ERROR: {e}")
    escribir()

    # 6. Para cada tabla relacionada, mostrar columnas y muestra de 3
    escribir("=" * 70)
    escribir("6) ESTRUCTURA DE TABLAS RELACIONADAS")
    escribir("=" * 70)
    try:
        for _, row in df_tablas.iterrows():
            esquema, tabla = row["esquema"], row["tabla"]
            escribir(f"\n--- [{esquema}].[{tabla}] ---")

            try:
                cnt = pd.read_sql(f"SELECT COUNT_BIG(*) AS n FROM [{esquema}].[{tabla}]", conn)
                escribir(f"Filas: {cnt.iloc[0]['n']:,}")
            except Exception as e:
                escribir(f"  No se pudo contar: {e}")

            try:
                cols = pd.read_sql(f"""
                    SELECT COLUMN_NAME AS columna, DATA_TYPE AS tipo,
                           CHARACTER_MAXIMUM_LENGTH AS largo
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = '{esquema}' AND TABLE_NAME = '{tabla}'
                    ORDER BY ORDINAL_POSITION
                """, conn)
                escribir(f"Columnas ({len(cols)}):")
                escribir(cols.to_string(index=False))
            except Exception as e:
                escribir(f"  ERROR columnas: {e}")

            try:
                sample = pd.read_sql(f"SELECT TOP 3 * FROM [{esquema}].[{tabla}]", conn)
                escribir(f"Muestra de 3 filas:")
                escribir(sample.to_string(index=False, max_colwidth=40))
            except Exception as e:
                escribir(f"  ERROR muestra: {e}")
    except Exception:
        pass
    escribir()

    conn.close()

    # Guardar a archivo
    OUTPUT_FILE.write_text("\n".join(salida), encoding="utf-8")
    print(f"\n\nExploracion guardada en: {OUTPUT_FILE}")
    print("Compartime ese archivo (o pegame su contenido) para diseñar el mapeo.")


if __name__ == "__main__":
    main()
