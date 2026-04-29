"""
test_conexion.py
-----------------
Primer script de la Tarea 1 - Ontologia y RAG.
Marketplace SA Paraguay - Linea Navidad.

Lo que hace este script:
  1. Lee las credenciales de Neo4j desde el archivo .env
  2. Se conecta a la base de datos de grafos
  3. Crea un primer nodo Producto (un arbol de Navidad)
  4. Lo busca y lo imprime en pantalla para confirmar
  5. Cierra la conexion

Si todo sale bien, vas a ver el producto impreso al final.
"""

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase


def main():
    # Paso 1: cargar las credenciales del archivo .env
    load_dotenv()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    print(f"Conectandome a Neo4j en {uri} con usuario '{user}'...")

    # Paso 2: abrir el driver (la 'puerta' de comunicacion con Neo4j)
    driver = GraphDatabase.driver(uri, auth=(user, password))

    # Paso 3: verificar que la conexion esta viva
    driver.verify_connectivity()
    print("Conexion exitosa con Neo4j.\n")

    # Paso 4: crear un primer producto navideno del catalogo de Marketplace SA
    # Usamos MERGE en vez de CREATE para que sea idempotente:
    # si corremos el script dos veces, no se duplica el nodo.
    query_crear = """
    MERGE (p:Producto {sku: $sku})
    SET p.nombre = $nombre,
        p.descripcion = $descripcion,
        p.perecedero = $perecedero
    RETURN p
    """

    producto_demo = {
        "sku": "NAV-ARB-001",
        "nombre": "Arbol de Navidad Premium 1.80m",
        "descripcion": "Arbol artificial verde con 800 ramas, base metalica incluida",
        "perecedero": False,
    }

    with driver.session() as session:
        session.run(query_crear, **producto_demo)
        print(f"Producto creado/actualizado: {producto_demo['sku']}")

        # Paso 5: buscar el producto recien creado para confirmar que quedo
        result = session.run(
            "MATCH (p:Producto {sku: $sku}) RETURN p.sku AS sku, p.nombre AS nombre, p.perecedero AS perecedero",
            sku=producto_demo["sku"],
        )
        record = result.single()

        print("\nProducto encontrado en la ontologia:")
        print(f"  SKU:        {record['sku']}")
        print(f"  Nombre:     {record['nombre']}")
        print(f"  Perecedero: {record['perecedero']}")

    # Paso 6: cerrar la conexion limpiamente
    driver.close()
    print("\nConexion cerrada. Todo OK.")


if __name__ == "__main__":
    main()
