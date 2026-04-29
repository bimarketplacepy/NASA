"""
cargar_ventas_semanales.py
---------------------------
Carga :VentaSemanal al graph Neo4j desde data/ventas_semanales_navidad.csv.
Recalcula :Producto.velocidad y :Producto.tieneHistorial.

Marketplace SA Paraguay - Linea Navidad - Tarea 3 (Cris).

Idempotencia: el script se puede correr N veces sin duplicar nodos.
Usa MERGE sobre (sku, anio, semana) y un constraint de unicidad compuesto.

Modo: dev (lee CSV local). La ruta a Pegasus directa queda como TODO.

Variables de entorno requeridas (.env):
    NEO4J_URI       (ej: bolt://localhost:7687)
    NEO4J_USER      (ej: neo4j)
    NEO4J_PASSWORD  (ej: marketplace2026)

Uso:
    python cargar_ventas_semanales.py
"""

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Rutas y constantes
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CSV_VENTAS = DATA_DIR / "ventas_semanales_navidad.csv"
ENV_FILE = BASE_DIR / ".env"

BATCH_SIZE = 5000          # registros por UNWIND
VENTANA_VELOCIDAD = 12     # semanas para el promedio de velocidad
UMBRAL_HISTORIAL = 12      # min. semanas con ventas para tieneHistorial


# ---------------------------------------------------------------------------
# Lectura del CSV
# ---------------------------------------------------------------------------
def leer_ventas_csv() -> pd.DataFrame:
    """Lee y valida el CSV de ventas semanales.

    El CSV usa ';' como separador y tiene BOM UTF-8 (export desde SSMS).
    Castea sku a str y enteros a int para coincidir con el esquema Neo4j.
    """
    if not CSV_VENTAS.exists():
        raise FileNotFoundError(
            f"No se encuentra {CSV_VENTAS}. "
            "Esperado: data/ventas_semanales_navidad.csv"
        )

    # Nota: sku se lee como Int64 (no str) para coincidir con cómo Abi
    # carga :Producto.sku desde productos.csv (también int). Si en el
    # futuro aparecen SKUs alfanuméricos hay que renegociar el tipo
    # en :Producto con Abi.
    df = pd.read_csv(
        CSV_VENTAS,
        sep=";",
        encoding="utf-8-sig",       # absorbe el BOM
        dtype={
            "sku": "Int64",
            "anio": "Int64",
            "semana": "Int64",
            "unidades_vendidas": "Int64",
            "importe_total_pyg": "Int64",
        },
    )

    # Validacion estructural
    columnas_esperadas = {"sku", "anio", "semana", "unidades_vendidas", "importe_total_pyg"}
    faltantes = columnas_esperadas - set(df.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas en el CSV: {faltantes}")

    if df.empty:
        raise ValueError("CSV de ventas vacio")

    # Validacion semantica: nulos, rangos
    n_antes = len(df)
    df = df.dropna(subset=["sku", "anio", "semana", "unidades_vendidas"])
    if len(df) < n_antes:
        print(f"  AVISO: {n_antes - len(df)} filas con nulos descartadas")

    if not df["semana"].between(1, 53).all():
        bad = df[~df["semana"].between(1, 53)]
        print(f"  AVISO: {len(bad)} filas con semana fuera de rango ISO (1-53), descartadas")
        df = df[df["semana"].between(1, 53)]

    # Casteo final a tipos Python nativos para Neo4j
    df = df.astype({
        "sku": int,
        "anio": int,
        "semana": int,
        "unidades_vendidas": int,
        "importe_total_pyg": int,
    })

    return df


# ---------------------------------------------------------------------------
# Esquema: constraint compuesto sobre :VentaSemanal
# ---------------------------------------------------------------------------
def crear_constraint(session) -> None:
    """Crea constraint UNIQUE compuesto sobre (sku, anio, semana).

    Se ejecuta en runtime (decision Cris). Idempotente: IF NOT EXISTS.
    """
    session.run("""
        CREATE CONSTRAINT venta_semanal_sku_anio_semana_unique IF NOT EXISTS
        FOR (v:VentaSemanal)
        REQUIRE (v.sku, v.anio, v.semana) IS UNIQUE
    """)


# ---------------------------------------------------------------------------
# Carga de :VentaSemanal en batches
# ---------------------------------------------------------------------------
def cargar_ventas(session, df: pd.DataFrame) -> dict:
    """Carga :VentaSemanal en batches. Skip + reporte de SKUs huerfanos.

    Devuelve un dict con stats:
        - filas_csv:       filas en el CSV
        - filas_cargadas:  ventas efectivamente persistidas (con :Producto)
        - creadas:         nuevas (delta de count antes/despues)
        - actualizadas:    filas tocadas que ya existian
        - skus_huerfanos:  SKUs en el CSV que no tienen :Producto en el grafo
        - muestra_huerfanos: lista (max 10) para diagnostico
    """
    total = len(df)
    skus_csv = set(df["sku"].unique())

    # Conteo previo para calcular creadas vs actualizadas
    n_antes = session.run("MATCH (v:VentaSemanal) RETURN count(v) AS n").single()["n"]

    # Detectar SKUs huerfanos UNA sola vez (mas eficiente que por batch)
    huerfanos = session.run("""
        UNWIND $skus AS s
        OPTIONAL MATCH (p:Producto {sku: s})
        WITH s, p
        WHERE p IS NULL
        RETURN collect(s) AS huerfanos
    """, skus=list(skus_csv)).single()["huerfanos"]
    skus_huerfanos = set(huerfanos)

    # Filtrar el df: solo ventas cuyo sku tiene :Producto
    if skus_huerfanos:
        df_validos = df[~df["sku"].isin(skus_huerfanos)]
    else:
        df_validos = df

    print(f"  Filas en CSV:          {total:,}")
    print(f"  SKUs unicos en CSV:    {len(skus_csv):,}")
    print(f"  SKUs sin :Producto:    {len(skus_huerfanos):,}")
    print(f"  Filas a cargar:        {len(df_validos):,}")

    # Carga en batches
    cargadas = 0
    n_batches = (len(df_validos) + BATCH_SIZE - 1) // BATCH_SIZE

    for i, inicio in enumerate(range(0, len(df_validos), BATCH_SIZE), start=1):
        chunk = df_validos.iloc[inicio:inicio + BATCH_SIZE]
        records = chunk.to_dict("records")

        result = session.run("""
            UNWIND $records AS r
            MATCH (p:Producto {sku: r.sku})
            MERGE (v:VentaSemanal {sku: r.sku, anio: r.anio, semana: r.semana})
            SET v.unidades    = r.unidades_vendidas,
                v.importe_pyg = r.importe_total_pyg
            MERGE (p)-[:TIENE_VENTAS]->(v)
            RETURN count(v) AS n
        """, records=records).single()
        cargadas += result["n"]
        print(f"  Batch {i}/{n_batches}: {result['n']:,} filas")

    n_despues = session.run("MATCH (v:VentaSemanal) RETURN count(v) AS n").single()["n"]
    creadas = max(0, n_despues - n_antes)
    actualizadas = max(0, cargadas - creadas)

    return {
        "filas_csv": total,
        "filas_cargadas": cargadas,
        "creadas": creadas,
        "actualizadas": actualizadas,
        "skus_huerfanos": len(skus_huerfanos),
        "muestra_huerfanos": sorted(skus_huerfanos)[:10],
    }


# ---------------------------------------------------------------------------
# Recalculo de :Producto.velocidad
# ---------------------------------------------------------------------------
def semanas_iso_recientes(fecha_corte: date, n: int) -> list[dict]:
    """Devuelve las n semanas ISO mas recientes hasta fecha_corte.

    Cada elemento es {'anio': int, 'semana': int}.
    """
    semanas: list[dict] = []
    vistos: set[tuple[int, int]] = set()
    fecha = fecha_corte
    while len(semanas) < n:
        iso = fecha.isocalendar()
        clave = (iso.year, iso.week)
        if clave not in vistos:
            vistos.add(clave)
            semanas.append({"anio": iso.year, "semana": iso.week})
        fecha -= timedelta(days=7)
    return semanas


def recalcular_velocidad(session, fecha_corte: date) -> int:
    """Recalcula :Producto.velocidad = avg(unidades) en las ultimas
    VENTANA_VELOCIDAD semanas calendario hasta fecha_corte.

    Productos sin ventas en la ventana -> velocidad = 0.0.
    Devuelve cuantos productos quedaron con velocidad > 0.
    """
    semanas_target = semanas_iso_recientes(fecha_corte, VENTANA_VELOCIDAD)
    print(f"  Ventana de velocidad: {VENTANA_VELOCIDAD} semanas hasta {fecha_corte.isoformat()}")
    print(f"  Desde {semanas_target[-1]} hasta {semanas_target[0]}")

    # 1) Productos que tienen al menos una venta en la ventana
    result = session.run("""
        UNWIND $semanas AS sem
        MATCH (p:Producto)-[:TIENE_VENTAS]->(v:VentaSemanal {anio: sem.anio, semana: sem.semana})
        WITH p, avg(toFloat(v.unidades)) AS velocidad
        SET p.velocidad = velocidad
        RETURN count(p) AS productos_con_velocidad
    """, semanas=semanas_target).single()
    con_velocidad = result["productos_con_velocidad"]

    # 2) Productos sin ventas en la ventana -> velocidad = 0.0 (o quedan sin la prop)
    session.run("""
        MATCH (p:Producto)
        WHERE p.velocidad IS NULL
        SET p.velocidad = 0.0
    """)

    return con_velocidad


# ---------------------------------------------------------------------------
# Recalculo de :Producto.tieneHistorial
# ---------------------------------------------------------------------------
def recalcular_tiene_historial(session) -> dict:
    """tieneHistorial = (count(VentaSemanal) >= UMBRAL_HISTORIAL)."""
    result = session.run("""
        MATCH (p:Producto)
        OPTIONAL MATCH (p)-[:TIENE_VENTAS]->(v:VentaSemanal)
        WITH p, count(v) AS n_semanas
        SET p.tieneHistorial = (n_semanas >= $umbral)
        RETURN
            sum(CASE WHEN n_semanas >= $umbral THEN 1 ELSE 0 END) AS con_historial,
            count(p) AS total
    """, umbral=UMBRAL_HISTORIAL).single()
    return {"con_historial": result["con_historial"], "total": result["total"]}


# ---------------------------------------------------------------------------
# Reporte final
# ---------------------------------------------------------------------------
def imprimir_resumen(session, stats: dict, vel_count: int, hist: dict) -> None:
    print("\n=== Resumen de carga ===")
    print(f"  Filas en CSV:                    {stats['filas_csv']:,}")
    print(f"  Filas cargadas (con :Producto):  {stats['filas_cargadas']:,}")
    print(f"    -> creadas (nuevas):           {stats['creadas']:,}")
    print(f"    -> actualizadas (re-corrida):  {stats['actualizadas']:,}")
    print(f"  SKUs huerfanos (sin :Producto):  {stats['skus_huerfanos']:,}")
    if stats["muestra_huerfanos"]:
        print(f"    Muestra: {stats['muestra_huerfanos']}")

    total_vs = session.run("MATCH (v:VentaSemanal) RETURN count(v) AS n").single()["n"]
    total_prod = session.run("MATCH (p:Producto) RETURN count(p) AS n").single()["n"]
    rels = session.run("MATCH ()-[r:TIENE_VENTAS]->() RETURN count(r) AS n").single()["n"]

    print(f"\n  Totales en el grafo:")
    print(f"    :VentaSemanal:                 {total_vs:,}")
    print(f"    :Producto:                     {total_prod:,}")
    print(f"    Aristas TIENE_VENTAS:          {rels:,}")

    print(f"\n  Productos con velocidad>0:       {vel_count:,}")
    print(f"  Productos con tieneHistorial:    {hist['con_historial']:,}/{hist['total']:,}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    load_dotenv(ENV_FILE)
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not (uri and user and password):
        raise RuntimeError(
            "Falta NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD en .env"
        )

    print(f"Conectando a Neo4j en {uri}...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    print("Conectado.\n")

    print("Leyendo CSV de ventas...")
    df = leer_ventas_csv()
    print(f"  Filas:        {len(df):,}")
    print(f"  SKUs unicos:  {df['sku'].nunique():,}")
    print(f"  Anios:        {sorted(df['anio'].unique())}")
    print(f"  Rango semana: {df['semana'].min()} - {df['semana'].max()}")

    fecha_corte = date.today()

    with driver.session() as session:
        print("\nCreando constraint :VentaSemanal (idempotente)...")
        crear_constraint(session)

        print("\nCargando :VentaSemanal...")
        stats = cargar_ventas(session, df)

        print("\nRecalculando :Producto.velocidad...")
        vel = recalcular_velocidad(session, fecha_corte)

        print("\nRecalculando :Producto.tieneHistorial...")
        hist = recalcular_tiene_historial(session)

        imprimir_resumen(session, stats, vel, hist)

    driver.close()
    print("\nListo. Avisar a Abi: :VentaSemanal cargados al graph.")


if __name__ == "__main__":
    main()
