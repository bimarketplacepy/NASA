"""
aplicar_esquema.py
-------------------
Aplica el esquema declarado en schema.cypher contra la base Neo4j.
Marketplace SA Paraguay - Linea Navidad - Tarea 1.

Lo que hace:
  1. Lee el archivo schema.cypher (que vive en la misma carpeta).
  2. Lo divide en sentencias individuales (cada una termina en ';').
  3. Ejecuta cada sentencia contra Neo4j.
  4. Despues consulta la lista de constraints e indices y los imprime
     para que se vea claramente que quedaron aplicados.

Es seguro correrlo varias veces: el schema usa IF NOT EXISTS.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase


def leer_sentencias(ruta_archivo: Path) -> list[str]:
    """Lee el archivo .cypher y lo divide en sentencias individuales."""
    contenido = ruta_archivo.read_text(encoding="utf-8")

    # Remover comentarios de linea (//) preservando la estructura
    lineas_limpias = []
    for linea in contenido.split("\n"):
        # Cortar la linea en el primer "//" que no este dentro de un string
        if "//" in linea:
            linea = linea.split("//")[0]
        lineas_limpias.append(linea)

    contenido_limpio = "\n".join(lineas_limpias)

    # Separar por ';' y limpiar espacios; descartar fragmentos vacios.
    sentencias = [s.strip() for s in contenido_limpio.split(";") if s.strip()]
    return sentencias


def main():
    load_dotenv()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    ruta_schema = Path(__file__).parent / "schema.cypher"
    print(f"Leyendo esquema desde: {ruta_schema}")

    sentencias = leer_sentencias(ruta_schema)
    print(f"Sentencias a ejecutar: {len(sentencias)}\n")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()

    with driver.session() as session:
        for i, sentencia in enumerate(sentencias, start=1):
            # Mostramos solo las primeras 80 caracteres de la sentencia para no inundar
            preview = sentencia.replace("\n", " ").strip()[:80]
            print(f"[{i}/{len(sentencias)}] Ejecutando: {preview}...")
            session.run(sentencia)

        print("\nEsquema aplicado correctamente.\n")

        # Verificacion: listar todos los constraints existentes
        print("=== Constraints actuales en la base ===")
        result = session.run("SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties")
        for record in result:
            print(f"  - {record['name']} ({record['type']}) sobre {record['labelsOrTypes']}.{record['properties']}")

        # Verificacion: listar todos los indices existentes
        print("\n=== Indices actuales en la base ===")
        result = session.run("SHOW INDEXES YIELD name, type, labelsOrTypes, properties")
        for record in result:
            print(f"  - {record['name']} ({record['type']}) sobre {record['labelsOrTypes']}.{record['properties']}")

    driver.close()
    print("\nListo.")


if __name__ == "__main__":
    main()
