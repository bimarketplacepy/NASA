"""
explorar_sqlserver.py
----------------------
Script de exploracion del schema real de Marketplace SA en SQL Server.
Tarea 1 - Bloque 5.5.

Lo que hace (todo de SOLO LECTURA, no modifica nada):
  1. Se conecta a SQL Server con las credenciales del .env
  2. Lista todas las tablas de la base
  3. Para cada tabla, muestra columnas, tipos de datos y cantidad de filas
  4. Muestra una muestra de 3 filas de tablas con nombre que sugiera ser
     relevantes para la ontologia (productos, proveedores, categorias, etc)

El objetivo es entender que datos hay disponibles para diseñar
el mapeo correcto entre la base real y la ontologia Neo4j.
"""

import os
from dotenv import load_dotenv
import pyodbc
import pandas as pd


# Palabras clave que sugieren tablas relevantes para la ontologia.
# Si tu base usa otras convenciones, agregalas aca.
PALABRAS_RELEVANTES = [
    "producto", "product", "articulo", "item",
    "proveedor", "supplier", "vendor",
    "categoria", "category", "rubro", "linea", "familia",
    "marca", "brand",
    "precio", "price",
    "stock", "inventario", "inventory",
    "venta", "sale", "factura", "invoice",
    "compra", "purchase", "orden",
]


def conectar():
    """Crea conexion a SQL Server usando credenciales del .env."""
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
    print(f"Conectando a SQL Server: {host}:{port}, base '{database}'...")
    conn = pyodbc.connect(cadena)
    print("Conectado.\n")
    return conn


def listar_tablas(conn) -> pd.DataFrame:
    """Devuelve un DataFrame con todas las tablas de usuario."""
    query = """
    SELECT TABLE_SCHEMA AS esquema, TABLE_NAME AS tabla
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    return pd.read_sql(query, conn)


def columnas_de(conn, esquema: str, tabla: str) -> pd.DataFrame:
    """Devuelve columnas, tipos y nullabilidad de una tabla."""
    query = """
    SELECT COLUMN_NAME AS columna, DATA_TYPE AS tipo,
           CHARACTER_MAXIMUM_LENGTH AS largo, IS_NULLABLE AS nullable
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
    ORDER BY ORDINAL_POSITION
    """
    return pd.read_sql(query, conn, params=[esquema, tabla])


def contar_filas(conn, esquema: str, tabla: str) -> int:
    """Cuenta filas de una tabla. Usa COUNT_BIG para tablas grandes."""
    query = f"SELECT COUNT_BIG(*) AS n FROM [{esquema}].[{tabla}]"
    cur = conn.cursor()
    cur.execute(query)
    return cur.fetchone()[0]


def muestra_filas(conn, esquema: str, tabla: str, n: int = 3) -> pd.DataFrame:
    """Trae las primeras n filas de una tabla."""
    query = f"SELECT TOP {n} * FROM [{esquema}].[{tabla}]"
    return pd.read_sql(query, conn)


def es_relevante(nombre_tabla: str) -> bool:
    n = nombre_tabla.lower()
    return any(palabra in n for palabra in PALABRAS_RELEVANTES)


def main():
    load_dotenv()
    conn = conectar()

    # 1. Listar todas las tablas
    tablas = listar_tablas(conn)
    print(f"=== {len(tablas)} tablas encontradas en la base ===\n")
    for _, row in tablas.iterrows():
        marca = " ***" if es_relevante(row["tabla"]) else ""
        print(f"  [{row['esquema']}].[{row['tabla']}]{marca}")
    print("\n(Las marcadas con *** parecen relevantes para la ontologia)\n")

    # 2. Para tablas relevantes, mostrar columnas y muestra
    print("=" * 70)
    print("DETALLE DE TABLAS RELEVANTES")
    print("=" * 70)
    for _, row in tablas.iterrows():
        if not es_relevante(row["tabla"]):
            continue

        esquema, tabla = row["esquema"], row["tabla"]
        print(f"\n--- [{esquema}].[{tabla}] ---")

        try:
            cnt = contar_filas(conn, esquema, tabla)
            print(f"Filas: {cnt:,}")
        except Exception as e:
            print(f"  No se pudo contar filas: {e}")

        try:
            cols = columnas_de(conn, esquema, tabla)
            print("Columnas:")
            for _, c in cols.iterrows():
                largo = f"({c['largo']})" if pd.notna(c['largo']) else ""
                print(f"  - {c['columna']:30s} {c['tipo']}{largo}  nullable={c['nullable']}")
        except Exception as e:
            print(f"  No se pudieron leer columnas: {e}")

        try:
            sample = muestra_filas(conn, esquema, tabla, n=3)
            print("Muestra (3 filas):")
            print(sample.to_string(index=False, max_cols=10, max_colwidth=30))
        except Exception as e:
            print(f"  No se pudo obtener muestra: {e}")

    conn.close()
    print("\n\nExploracion completa. Compartime la salida para diseñar el mapeo.")


if __name__ == "__main__":
    main()
