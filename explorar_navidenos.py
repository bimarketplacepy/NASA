"""
explorar_navidenos.py
----------------------
Exploracion final del universo navideño antes de redisenar el esquema.
Tarea 1 - Bloque 5.5 (cierre).

Lo que averigua:
  1. Distribucion de los navideños por Categoria (con nombres) - granularidad real.
  2. Jerarquia completa Seccion > Sub_seccion > Categoria de los navideños.
  3. Proveedores que compraron navideños alguna vez (con pais y conteo).
  4. Cantidad total de relaciones distintas (producto, proveedor) historicas.
  5. Muestra de las 10 compras mas recientes de navideños con sus condiciones.

Todo se guarda en exploracion_navidenos.txt.
"""

import os
import warnings
from pathlib import Path
from datetime import datetime

import pyodbc
import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=UserWarning)

OUTPUT_FILE = Path(__file__).parent / "exploracion_navidenos.txt"


def conectar():
    return pyodbc.connect(
        f"DRIVER={{{os.getenv('SQLSERVER_DRIVER')}}};"
        f"SERVER={os.getenv('SQLSERVER_HOST')},{os.getenv('SQLSERVER_PORT')};"
        f"DATABASE={os.getenv('SQLSERVER_DATABASE')};"
        f"UID={os.getenv('SQLSERVER_USER')};"
        f"PWD={os.getenv('SQLSERVER_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )


def main():
    load_dotenv()
    print("Conectando a Pegasus...")
    conn = conectar()
    print("Conectado. Volcando exploracion en:", OUTPUT_FILE, "\n")

    salida = [f"# Exploracion universo navideño - {datetime.now().isoformat()}\n"]

    def escribir(s=""):
        salida.append(s)
        print(s)

    # 1) Categorias distintas entre navideños
    escribir("=" * 70)
    escribir("1) DISTRIBUCION DE NAVIDENOS POR CATEGORIA")
    escribir("=" * 70)
    escribir("Cuantos productos navideños distintos hay en cada Categoria:")
    df = pd.read_sql("""
        SELECT
            p.COD_CATEGORIA,
            COALESCE(c.DESCRIPCION_CATE, '(sin nombre)') AS categoria,
            COUNT(DISTINCT p.CODIGO) AS productos_distintos
        FROM PRODUCTOS p
        JOIN MOVIMIENTOS_DEPOSITOS md ON md.CODIGO = p.CODIGO
        LEFT JOIN CATEGORIAS c ON c.COD_CATEGORIA = p.COD_CATEGORIA
        WHERE p.cod_sub_seccion = 306 AND md.CANTIDAD >= 1
        GROUP BY p.COD_CATEGORIA, c.DESCRIPCION_CATE
        ORDER BY productos_distintos DESC
    """, conn)
    escribir(df.to_string(index=False))
    escribir(f"\nTotal de Categorias distintas con navideños en stock: {len(df)}")
    escribir()

    # 2) Jerarquia completa
    escribir("=" * 70)
    escribir("2) JERARQUIA COMPLETA: SECCION > SUB_SECCION > CATEGORIA")
    escribir("=" * 70)
    escribir("(Filtrando solo a la jerarquia que cae bajo Sub_seccion 306)")
    df = pd.read_sql("""
        SELECT
            s.Cod_seccion,
            s.Secciones AS seccion,
            ss.Cod_sub_seccion,
            ss.Sub_secciones AS sub_seccion,
            p.COD_CATEGORIA,
            COALESCE(c.DESCRIPCION_CATE, '(sin nombre)') AS categoria,
            COUNT(DISTINCT p.CODIGO) AS productos
        FROM PRODUCTOS p
        JOIN MOVIMIENTOS_DEPOSITOS md ON md.CODIGO = p.CODIGO
        LEFT JOIN Sub_seccion ss ON ss.Cod_sub_seccion = p.cod_sub_seccion
        LEFT JOIN Seccion s ON s.Cod_seccion = ss.cod_seccion
        LEFT JOIN CATEGORIAS c ON c.COD_CATEGORIA = p.COD_CATEGORIA
        WHERE p.cod_sub_seccion = 306 AND md.CANTIDAD >= 1
        GROUP BY s.Cod_seccion, s.Secciones, ss.Cod_sub_seccion, ss.Sub_secciones,
                 p.COD_CATEGORIA, c.DESCRIPCION_CATE
        ORDER BY productos DESC
    """, conn)
    escribir(df.to_string(index=False))
    escribir()

    # 3) Proveedores que compraron navideños
    escribir("=" * 70)
    escribir("3) PROVEEDORES QUE COMPRARON NAVIDENOS HISTORICAMENTE")
    escribir("=" * 70)
    escribir("Cada fila: un proveedor + cuantos productos navideños distintos le compramos.")
    df = pd.read_sql("""
        SELECT
            pr.COD_PROVEEDOR,
            pr.NOMBRE_PROVEEDOR,
            pr.PAIS,
            pr.CIUDAD,
            pr.PALZO_ENTREGA AS lead_time_dias,
            COUNT(DISTINCT cd.CODIGO) AS productos_navidenos_distintos,
            COUNT(*) AS lineas_compra,
            MAX(c.FECHA) AS ultima_compra
        FROM COMPRAS c
        JOIN COMPRAS_DET cd ON cd.NRO_REG = c.NRO_REG
        JOIN PRODUCTOS p ON p.CODIGO = cd.CODIGO
        JOIN PROVEEDORES pr ON pr.COD_PROVEEDOR = c.COD_PROVEEDOR
        WHERE p.cod_sub_seccion = 306
        GROUP BY pr.COD_PROVEEDOR, pr.NOMBRE_PROVEEDOR, pr.PAIS, pr.CIUDAD, pr.PALZO_ENTREGA
        ORDER BY productos_navidenos_distintos DESC
    """, conn)
    escribir(df.head(30).to_string(index=False))
    escribir(f"\nTotal proveedores que compraron navideños: {len(df)}")
    escribir()

    # 4) Cantidad total de relaciones (producto, proveedor)
    escribir("=" * 70)
    escribir("4) RELACIONES PRODUCTO-PROVEEDOR DISTINTAS")
    escribir("=" * 70)
    df = pd.read_sql("""
        SELECT COUNT(*) AS relaciones_distintas
        FROM (
            SELECT DISTINCT cd.CODIGO, c.COD_PROVEEDOR
            FROM COMPRAS c
            JOIN COMPRAS_DET cd ON cd.NRO_REG = c.NRO_REG
            JOIN PRODUCTOS p ON p.CODIGO = cd.CODIGO
            WHERE p.cod_sub_seccion = 306
        ) x
    """, conn)
    escribir(df.to_string(index=False))
    escribir()

    # 5) Muestra de compras recientes
    escribir("=" * 70)
    escribir("5) ULTIMAS 10 COMPRAS DE NAVIDENOS (RECIENTES)")
    escribir("=" * 70)
    df = pd.read_sql("""
        SELECT TOP 10
            CONVERT(date, c.FECHA) AS fecha,
            cd.CODIGO,
            p.descripcion_corta AS producto,
            pr.NOMBRE_PROVEEDOR AS proveedor,
            pr.PAIS,
            cd.CANTIDAD,
            cd.PRECIO
        FROM COMPRAS c
        JOIN COMPRAS_DET cd ON cd.NRO_REG = c.NRO_REG
        JOIN PRODUCTOS p ON p.CODIGO = cd.CODIGO
        JOIN PROVEEDORES pr ON pr.COD_PROVEEDOR = c.COD_PROVEEDOR
        WHERE p.cod_sub_seccion = 306
        ORDER BY c.FECHA DESC
    """, conn)
    escribir(df.to_string(index=False))
    escribir()

    # 6) Cuantos navideños tienen al menos un proveedor historico
    escribir("=" * 70)
    escribir("6) NAVIDENOS CON Y SIN HISTORIAL DE COMPRA")
    escribir("=" * 70)
    df = pd.read_sql("""
        SELECT
            (SELECT COUNT(DISTINCT p.CODIGO)
             FROM PRODUCTOS p
             JOIN MOVIMIENTOS_DEPOSITOS md ON md.CODIGO = p.CODIGO
             WHERE p.cod_sub_seccion = 306 AND md.CANTIDAD >= 1) AS total_navidenos_en_stock,
            (SELECT COUNT(DISTINCT p.CODIGO)
             FROM PRODUCTOS p
             JOIN MOVIMIENTOS_DEPOSITOS md ON md.CODIGO = p.CODIGO
             JOIN COMPRAS_DET cd ON cd.CODIGO = p.CODIGO
             WHERE p.cod_sub_seccion = 306 AND md.CANTIDAD >= 1) AS con_historial_compra
    """, conn)
    escribir(df.to_string(index=False))
    escribir()

    conn.close()

    OUTPUT_FILE.write_text("\n".join(str(s) for s in salida), encoding="utf-8")
    print(f"\nExploracion guardada en: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
