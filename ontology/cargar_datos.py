"""
cargar_datos.py
----------------
Carga los CSVs reales (exportados desde Pegasus) a la ontologia Neo4j.
Marketplace SA Paraguay - Linea Navidad - Tarea 1 - Bloque 5.8.

Orden de carga (respeta dependencias):
  1. Secciones        (no depende de nada)
  2. SubSecciones     (referencian Secciones)
  3. Categorias       (referencian SubSecciones)
  4. Productos        (referencian Categorias) + merge con precios_venta
  5. Proveedores      (independientes)
  6. Relaciones SUMINISTRADO_POR (referencian Productos y Proveedores)
  7. Eventos comerciales (independientes)

Toda la carga es idempotente (MERGE). Podes correrlo N veces sin duplicar.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase


DATA_DIR = Path(__file__).parent.parent / "data"


def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza NaN/NaT por None para que Neo4j los reciba como NULL."""
    return df.astype(object).where(pd.notnull(df), None)


def to_records(df: pd.DataFrame) -> list[dict]:
    """Convierte df a lista de dicts limpios."""
    return limpiar(df).to_dict("records")


def cargar_secciones(session):
    df = pd.read_csv(DATA_DIR / "secciones.csv")
    print(f"  Cargando {len(df)} secciones...")
    session.run("""
        UNWIND $records AS r
        MERGE (s:Seccion {id: r.id})
        SET s.nombre = r.nombre
    """, records=to_records(df))


def cargar_subsecciones(session):
    df = pd.read_csv(DATA_DIR / "subsecciones.csv")
    print(f"  Cargando {len(df)} subsecciones...")
    session.run("""
        UNWIND $records AS r
        MERGE (ss:SubSeccion {id: r.id})
        SET ss.nombre = r.nombre
        WITH ss, r
        MATCH (s:Seccion {id: r.seccion_id})
        MERGE (ss)-[:PERTENECE_A]->(s)
    """, records=to_records(df))


def cargar_grupos(session):
    df = pd.read_csv(DATA_DIR / "grupos.csv")
    print(f"  Cargando {len(df)} grupos...")
    session.run("""
        UNWIND $records AS r
        MERGE (g:Grupo {id: r.id})
        SET g.nombre = r.nombre
        WITH g, r
        MATCH (ss:SubSeccion {id: r.subseccion_id})
        MERGE (g)-[:PERTENECE_A]->(ss)
    """, records=to_records(df))


def cargar_categorias(session):
    df = pd.read_csv(DATA_DIR / "categorias.csv")
    print(f"  Cargando {len(df)} categorias...")
    # Categoria -> Grupo (no a SubSeccion directamente; ahora va via Grupo)
    # Si grupo_id es null, igual creamos la Categoria pero sin arista a Grupo.
    session.run("""
        UNWIND $records AS r
        MERGE (c:Categoria {id: r.id})
        SET c.nombre = r.nombre
        WITH c, r
        WHERE r.grupo_id IS NOT NULL
        MATCH (g:Grupo {id: r.grupo_id})
        MERGE (c)-[:PERTENECE_A]->(g)
    """, records=to_records(df))


def cargar_productos(session):
    productos = pd.read_csv(DATA_DIR / "productos.csv")
    precios = pd.read_csv(DATA_DIR / "precios_venta.csv")

    # Enriquecer cada producto con su ultima venta (left join: los que no
    # vendieron en los ultimos 2 anos quedan con NaN -> None -> NULL en Neo4j)
    df = productos.merge(precios, on="sku", how="left")
    print(f"  Cargando {len(df)} productos (con merge de precios)...")

    records = to_records(df)
    # Convertir 'true'/'false' string a bool de Python
    # y derivar en_stock a partir de cantidad_stock
    for r in records:
        r["perecedero"] = (str(r.get("perecedero", "")).lower() == "true")
        cant = r.get("cantidad_stock") or 0
        r["en_stock"] = (cant >= 1)

    session.run("""
        UNWIND $records AS r
        MERGE (p:Producto {sku: r.sku})
        SET p.codigo_barras   = r.codigo_barras,
            p.nombre          = r.nombre,
            p.nombre_corto    = r.nombre_corto,
            p.unidad          = r.unidad,
            p.pais_origen     = r.pais_origen,
            p.precio_costo    = r.precio_costo,
            p.perecedero      = r.perecedero,
            p.cantidad_stock  = r.cantidad_stock,
            p.en_stock        = r.en_stock,
            p.precio_venta_actual = r.precio_venta_actual,
            p.fecha_ultima_compra =
                CASE WHEN r.fecha_ultima_compra IS NULL THEN NULL
                     ELSE datetime(replace(r.fecha_ultima_compra, ' ', 'T')) END,
            p.fecha_ultima_venta =
                CASE WHEN r.fecha_ultima_venta IS NULL THEN NULL
                     ELSE datetime(replace(r.fecha_ultima_venta, ' ', 'T')) END,
            p.fecha_ultima_actualizacion =
                CASE WHEN r.fecha_ultima_actualizacion IS NULL THEN NULL
                     ELSE datetime(replace(r.fecha_ultima_actualizacion, ' ', 'T')) END,
            p.fecha_alta =
                CASE WHEN r.fecha_alta IS NULL THEN NULL
                     ELSE datetime(replace(r.fecha_alta, ' ', 'T')) END
        WITH p, r
        MATCH (c:Categoria {id: r.categoria_id})
        MERGE (p)-[:PERTENECE_A]->(c)
    """, records=records)


def cargar_proveedores(session):
    df = pd.read_csv(DATA_DIR / "proveedores.csv")
    print(f"  Cargando {len(df)} proveedores...")

    records = to_records(df)
    for r in records:
        r["proveedor_exterior"] = (str(r.get("proveedor_exterior", "")).lower() == "true")

    session.run("""
        UNWIND $records AS r
        MERGE (pr:Proveedor {id: r.id})
        SET pr.nombre             = r.nombre,
            pr.ruc                = r.ruc,
            pr.pais               = r.pais,
            pr.email              = r.email,
            pr.telefono           = r.telefono,
            pr.proveedor_exterior = r.proveedor_exterior
    """, records=records)


def cargar_relaciones(session):
    df = pd.read_csv(DATA_DIR / "relaciones_comerciales.csv")
    print(f"  Cargando {len(df)} aristas SUMINISTRADO_POR...")

    session.run("""
        UNWIND $records AS r
        MATCH (p:Producto {sku: r.sku})
        MATCH (pr:Proveedor {id: r.proveedor_id})
        MERGE (p)-[rel:SUMINISTRADO_POR]->(pr)
        SET rel.ultima_fecha_compra =
                CASE WHEN r.ultima_fecha_compra IS NULL THEN NULL
                     ELSE datetime(replace(r.ultima_fecha_compra, ' ', 'T')) END,
            rel.ultimo_precio_pyg        = r.ultimo_precio_pyg,
            rel.ultima_cantidad          = r.ultima_cantidad,
            rel.total_cantidad_historica = r.total_cantidad_historica,
            rel.total_lineas_compra      = r.total_lineas_compra
    """, records=to_records(df))


def cargar_eventos(session):
    df = pd.read_csv(DATA_DIR / "eventos_comerciales.csv")
    print(f"  Cargando {len(df)} eventos comerciales...")
    session.run("""
        UNWIND $records AS r
        MERGE (e:EventoComercial {id: r.id})
        SET e.nombre = r.nombre,
            e.fecha  = date(r.fecha),
            e.tipo   = r.tipo
    """, records=to_records(df))


def imprimir_resumen(session):
    print("\n=== Resumen de la ontologia ===")
    queries = [
        ("Secciones",                  "MATCH (s:Seccion) RETURN count(s) AS n"),
        ("SubSecciones",               "MATCH (ss:SubSeccion) RETURN count(ss) AS n"),
        ("Grupos",                     "MATCH (g:Grupo) RETURN count(g) AS n"),
        ("Categorias",                 "MATCH (c:Categoria) RETURN count(c) AS n"),
        ("Productos",                  "MATCH (p:Producto) RETURN count(p) AS n"),
        ("  -> en stock",              "MATCH (p:Producto {en_stock: true}) RETURN count(p) AS n"),
        ("  -> sin stock (restock)",   "MATCH (p:Producto {en_stock: false}) RETURN count(p) AS n"),
        ("  -> perecederos",           "MATCH (p:Producto {perecedero: true}) RETURN count(p) AS n"),
        ("  -> con precio de venta",   "MATCH (p:Producto) WHERE p.precio_venta_actual IS NOT NULL RETURN count(p) AS n"),
        ("Proveedores",                "MATCH (pr:Proveedor) RETURN count(pr) AS n"),
        ("  -> del exterior",          "MATCH (pr:Proveedor {proveedor_exterior: true}) RETURN count(pr) AS n"),
        ("Eventos comerciales",        "MATCH (e:EventoComercial) RETURN count(e) AS n"),
        ("Aristas PERTENECE_A",        "MATCH ()-[r:PERTENECE_A]->() RETURN count(r) AS n"),
        ("Aristas SUMINISTRADO_POR",   "MATCH ()-[r:SUMINISTRADO_POR]->() RETURN count(r) AS n"),
    ]
    for etiqueta, q in queries:
        n = session.run(q).single()["n"]
        print(f"  {etiqueta:32s} {n:,}")


def main():
    load_dotenv()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    print(f"Conectando a Neo4j en {uri}...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    print("Conectado.\n")

    print("Iniciando carga:")
    with driver.session() as session:
        cargar_secciones(session)
        cargar_subsecciones(session)
        cargar_grupos(session)         # nuevo: antes que categorias
        cargar_categorias(session)
        cargar_productos(session)
        cargar_proveedores(session)
        cargar_relaciones(session)
        cargar_eventos(session)
        imprimir_resumen(session)

    driver.close()
    print("\nCarga completa.")


if __name__ == "__main__":
    main()
