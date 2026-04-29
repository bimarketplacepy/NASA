"""
exportar_a_csv.py
------------------
Exporta los datos reales de Pegasus a CSVs en data/, con la estructura
acordada para alimentar al loader de Neo4j.
Tarea 1 - Bloque 5.7 (v2, post diagnostico).

Cambios respecto a v1:
  - Eliminadas columnas muertas (dias_validez, peso, volumen_cc, PERECEDERO,
    todas las PRECIO_VENTA, PALZO_*, PORCENTAJE_BONIF, ciudad).
  - perecedero se DERIVA de la categoria (no se lee de PRODUCTOS).
  - precio_venta se obtiene de VENTAS_DET.PRECIO_LISTA (ultima venta
    por SKU desde 2024-01-01), no de PRODUCTOS.
  - Filtro temporal de 2 anos en relaciones comerciales.

Filtros aplicados:
  * Solo cod_sub_seccion = 306 (NAVIDAD)
  * Solo productos con CANTIDAD >= 1 en MOVIMIENTOS_DEPOSITOS
  * Compras con CANTIDAD > 0 (excluye devoluciones)
  * Ventana temporal desde FECHA_DESDE (default 2024-01-01)
"""

import os
import time
import warnings
from pathlib import Path

import pyodbc
import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=UserWarning)

OUTPUT_DIR = Path(__file__).parent / "data"
COD_SUB_SECCION_NAVIDAD = 306
FECHA_DESDE = "2024-01-01"  # ajustar si querés otro horizonte

# Categorias cuyos productos son perecederos (derivado por nombre)
CATEGORIAS_PERECEDERAS = {
    "TURRONES", "CHOCOLATES", "ALFAJORES",
    "PAN DULCE", "GALLETITAS", "CARAMELOS",
}


def conectar():
    return pyodbc.connect(
        f"DRIVER={{{os.getenv('SQLSERVER_DRIVER')}}};"
        f"SERVER={os.getenv('SQLSERVER_HOST')},{os.getenv('SQLSERVER_PORT')};"
        f"DATABASE={os.getenv('SQLSERVER_DATABASE')};"
        f"UID={os.getenv('SQLSERVER_USER')};"
        f"PWD={os.getenv('SQLSERVER_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )


def exportar(conn, query: str, archivo: str, descripcion: str) -> pd.DataFrame:
    print(f"  Exportando {descripcion}...", end=" ", flush=True)
    t = time.time()
    df = pd.read_sql(query, conn)
    ruta = OUTPUT_DIR / archivo
    df.to_csv(ruta, index=False, encoding="utf-8")
    print(f"{len(df):,} filas -> {ruta.name}  ({time.time()-t:.1f}s)")
    return df


def main():
    load_dotenv()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Conectando a Pegasus en {os.getenv('SQLSERVER_HOST')}:{os.getenv('SQLSERVER_PORT')}...")
    conn = conectar()
    print(f"Conectado. Ventana temporal: desde {FECHA_DESDE}\n")

    print("Iniciando exportacion:")

    # 1) Secciones
    exportar(conn, f"""
        SELECT DISTINCT s.Cod_seccion AS id, LTRIM(RTRIM(s.Secciones)) AS nombre
        FROM Seccion s
        WHERE s.Cod_seccion IN (
            SELECT DISTINCT cod_seccion FROM Sub_seccion
            WHERE Cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
        )
    """, "secciones.csv", "secciones")

    # 2) SubSecciones
    exportar(conn, f"""
        SELECT Cod_sub_seccion AS id, LTRIM(RTRIM(Sub_secciones)) AS nombre,
               cod_seccion AS seccion_id
        FROM Sub_seccion WHERE Cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
    """, "subsecciones.csv", "subsecciones")

    # 3a) Grupos (nivel intermedio Sub_seccion -> Grupo -> Categoria)
    #    Solo grupos que tienen al menos una categoria de un navideño relevante.
    exportar(conn, f"""
        SELECT DISTINCT
            g.COD_GRUPO AS id,
            LTRIM(RTRIM(g.DESCRIPCION_GRUPO)) AS nombre,
            {COD_SUB_SECCION_NAVIDAD} AS subseccion_id
        FROM GRUPO g
        WHERE EXISTS (
            SELECT 1
            FROM CATEGORIAS c
            INNER JOIN PRODUCTOS p ON p.COD_CATEGORIA = c.COD_CATEGORIA
            WHERE c.cod_grupo = g.COD_GRUPO
              AND p.cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
              AND (
                     EXISTS (SELECT 1 FROM MOVIMIENTOS_DEPOSITOS md
                             WHERE md.CODIGO = p.CODIGO AND md.CANTIDAD >= 1)
                  OR EXISTS (SELECT 1 FROM VENTAS_DET vd
                             INNER JOIN VENTAS v ON v.NRO_REG = vd.NRO_REG
                             WHERE vd.CODIGO = p.CODIGO
                               AND v.FECHA >= '{FECHA_DESDE}'
                               AND vd.UNIDADES > 0)
                  OR EXISTS (SELECT 1 FROM COMPRAS_DET cd
                             INNER JOIN COMPRAS c2 ON c2.NRO_REG = cd.NRO_REG
                             WHERE cd.CODIGO = p.CODIGO
                               AND c2.FECHA >= '{FECHA_DESDE}'
                               AND cd.CANTIDAD > 0)
              )
        )
    """, "grupos.csv", "grupos")

    # 3b) Categorias - ahora con grupo_id (apunta al :Grupo padre, no al SubSeccion)
    df_cats = exportar(conn, f"""
        SELECT DISTINCT
            p.COD_CATEGORIA AS id,
            COALESCE(LTRIM(RTRIM(c.DESCRIPCION_CATE)), '(sin nombre)') AS nombre,
            c.cod_grupo AS grupo_id
        FROM PRODUCTOS p
        LEFT JOIN CATEGORIAS c ON c.COD_CATEGORIA = p.COD_CATEGORIA
        WHERE p.cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
          AND (
                 EXISTS (SELECT 1 FROM MOVIMIENTOS_DEPOSITOS md
                         WHERE md.CODIGO = p.CODIGO AND md.CANTIDAD >= 1)
              OR EXISTS (SELECT 1 FROM VENTAS_DET vd
                         INNER JOIN VENTAS v ON v.NRO_REG = vd.NRO_REG
                         WHERE vd.CODIGO = p.CODIGO
                           AND v.FECHA >= '{FECHA_DESDE}'
                           AND vd.UNIDADES > 0)
              OR EXISTS (SELECT 1 FROM COMPRAS_DET cd
                         INNER JOIN COMPRAS c2 ON c2.NRO_REG = cd.NRO_REG
                         WHERE cd.CODIGO = p.CODIGO
                           AND c2.FECHA >= '{FECHA_DESDE}'
                           AND cd.CANTIDAD > 0)
          )
    """, "categorias.csv", "categorias")

    # Mapa categoria_id -> nombre (para derivar perecedero en productos)
    cat_id_a_nombre = dict(zip(df_cats["id"], df_cats["nombre"]))

    # 4) Productos: navideños con cualquier actividad comercial reciente
    #    (stock actual O ventas desde FECHA_DESDE O compras desde FECHA_DESDE)
    #    Se incluye cantidad_stock como columna agregada (suma entre depositos).
    print(f"  Exportando productos...", end=" ", flush=True)
    t = time.time()
    df_prod = pd.read_sql(f"""
        SELECT
            LTRIM(RTRIM(p.CODIGO)) AS sku,
            LTRIM(RTRIM(p.CODIGO_BARRAS)) AS codigo_barras,
            LTRIM(RTRIM(p.DESCRIPCION_PRODUCTO)) AS nombre,
            LTRIM(RTRIM(p.descripcion_corta)) AS nombre_corto,
            LTRIM(RTRIM(p.UNIDAD)) AS unidad,
            LTRIM(RTRIM(p.pais_origen)) AS pais_origen,
            p.PRECIO_COSTO AS precio_costo,
            p.FECHA_ULT_COMPRA AS fecha_ultima_compra,
            p.ULTIMA_ACTUALIZACION AS fecha_ultima_actualizacion,
            p.fecha_alta,
            p.COD_CATEGORIA AS categoria_id,
            COALESCE(stock.cant_total, 0) AS cantidad_stock
        FROM PRODUCTOS p
        LEFT JOIN (
            -- Stock total por SKU agregando entre todos los depositos.
            -- Tratamos cantidades negativas como 0 para que no resten al total
            -- (los negativos pasan por errores de auditoria/devoluciones mal procesadas).
            SELECT CODIGO,
                   SUM(CASE WHEN CANTIDAD < 0 THEN 0 ELSE CANTIDAD END) AS cant_total
            FROM MOVIMIENTOS_DEPOSITOS
            GROUP BY CODIGO
        ) stock ON stock.CODIGO = p.CODIGO
        WHERE p.cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
          AND (
                 COALESCE(stock.cant_total, 0) >= 1
              OR EXISTS (
                    SELECT 1 FROM VENTAS_DET vd
                    INNER JOIN VENTAS v ON v.NRO_REG = vd.NRO_REG
                    WHERE vd.CODIGO = p.CODIGO
                      AND v.FECHA >= '{FECHA_DESDE}'
                      AND vd.UNIDADES > 0
                 )
              OR EXISTS (
                    SELECT 1 FROM COMPRAS_DET cd
                    INNER JOIN COMPRAS c ON c.NRO_REG = cd.NRO_REG
                    WHERE cd.CODIGO = p.CODIGO
                      AND c.FECHA >= '{FECHA_DESDE}'
                      AND cd.CANTIDAD > 0
                 )
          )
    """, conn)

    # Derivar perecedero a partir del nombre de la categoria
    def es_perecedero(cat_id):
        nombre = cat_id_a_nombre.get(cat_id, "")
        return "true" if nombre.upper() in CATEGORIAS_PERECEDERAS else "false"

    df_prod = df_prod.assign(perecedero=df_prod["categoria_id"].apply(es_perecedero))

    df_prod.to_csv(OUTPUT_DIR / "productos.csv", index=False, encoding="utf-8")
    print(f"{len(df_prod):,} filas -> productos.csv  ({time.time()-t:.1f}s)  "
          f"({(df_prod['perecedero']=='true').sum()} perecederos)")

    # 5) Ultimo precio de venta por SKU desde VENTAS_DET
    # Nota: el CTE NO puede llamarse 'ventas' porque colisiona con la tabla VENTAS
    # y SQL Server lo interpreta como CTE recursivo. Por eso se llama 'ultima_venta_sku'.
    exportar(conn, f"""
        WITH ultima_venta_sku AS (
            SELECT
                LTRIM(RTRIM(vd.CODIGO)) AS sku,
                v.FECHA,
                vd.PRECIO_LISTA,
                ROW_NUMBER() OVER (PARTITION BY vd.CODIGO ORDER BY v.FECHA DESC) AS rn
            FROM VENTAS_DET vd
            INNER JOIN VENTAS v ON v.NRO_REG = vd.NRO_REG
            INNER JOIN PRODUCTOS p ON p.CODIGO = vd.CODIGO
            WHERE p.cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
              AND v.FECHA >= '{FECHA_DESDE}'
              AND vd.UNIDADES > 0
        )
        SELECT sku, FECHA AS fecha_ultima_venta, PRECIO_LISTA AS precio_venta_actual
        FROM ultima_venta_sku WHERE rn = 1
    """, "precios_venta.csv", "precios de venta (ultima venta por SKU)")

    # 6) Proveedores (sin columnas muertas: ciudad, lead_time, plazo, bonif)
    # proveedor_exterior se DERIVA de la existencia de alguna compra con
    # TIPO_DOCUMEN=20 (importacion). La columna nativa pr.proveedor_exterior
    # es basura: solo NORITEX la tiene marcada de los 60+ proveedores reales.
    exportar(conn, f"""
        SELECT
            pr.COD_PROVEEDOR AS id,
            LTRIM(RTRIM(pr.NOMBRE_PROVEEDOR)) AS nombre,
            LTRIM(RTRIM(pr.RUC)) AS ruc,
            LTRIM(RTRIM(pr.PAIS)) AS pais,
            LTRIM(RTRIM(pr.EMAIL)) AS email,
            LTRIM(RTRIM(pr.TELEFONO_PROVEEDOR)) AS telefono,
            CASE WHEN EXISTS (
                SELECT 1 FROM COMPRAS c2
                WHERE c2.COD_PROVEEDOR = pr.COD_PROVEEDOR
                  AND c2.TIPO_DOCUMEN = 20
            ) THEN 'true' ELSE 'false' END AS proveedor_exterior
        FROM PROVEEDORES pr
        WHERE pr.COD_PROVEEDOR IN (
            SELECT DISTINCT c.COD_PROVEEDOR
            FROM COMPRAS c
            INNER JOIN COMPRAS_DET cd ON cd.NRO_REG = c.NRO_REG
            INNER JOIN PRODUCTOS p ON p.CODIGO = cd.CODIGO
            WHERE p.cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
              AND cd.CANTIDAD > 0
              AND c.FECHA >= '{FECHA_DESDE}'
        )
    """, "proveedores.csv", "proveedores activos")

    # 7) Relaciones comerciales (filtro temporal solamente)
    exportar(conn, f"""
        WITH detalles AS (
            SELECT
                LTRIM(RTRIM(cd.CODIGO)) AS sku,
                c.COD_PROVEEDOR AS proveedor_id,
                c.FECHA, cd.PRECIO, cd.CANTIDAD
            FROM COMPRAS c
            INNER JOIN COMPRAS_DET cd ON cd.NRO_REG = c.NRO_REG
            INNER JOIN PRODUCTOS p ON p.CODIGO = cd.CODIGO
            WHERE p.cod_sub_seccion = {COD_SUB_SECCION_NAVIDAD}
              AND cd.CANTIDAD > 0
              AND c.FECHA >= '{FECHA_DESDE}'
        ),
        ultima AS (
            SELECT sku, proveedor_id, FECHA, PRECIO, CANTIDAD,
                ROW_NUMBER() OVER (PARTITION BY sku, proveedor_id ORDER BY FECHA DESC) AS rn
            FROM detalles
        ),
        agregado AS (
            SELECT sku, proveedor_id,
                SUM(CANTIDAD) AS total_cantidad_historica,
                COUNT(*) AS total_lineas_compra
            FROM detalles GROUP BY sku, proveedor_id
        )
        SELECT
            u.sku, u.proveedor_id,
            u.FECHA AS ultima_fecha_compra,
            u.PRECIO AS ultimo_precio_pyg,
            u.CANTIDAD AS ultima_cantidad,
            a.total_cantidad_historica,
            a.total_lineas_compra
        FROM ultima u
        INNER JOIN agregado a ON a.sku = u.sku AND a.proveedor_id = u.proveedor_id
        WHERE u.rn = 1
    """, "relaciones_comerciales.csv",
         f"relaciones comerciales desde {FECHA_DESDE} (puede tardar 30-60s)")

    print("\nLos eventos comerciales se generan con generar_eventos.py (no salen de Pegasus).")
    conn.close()
    print("Export completo. CSVs en:", OUTPUT_DIR)


if __name__ == "__main__":
    main()
