"""
ontology/client.py
-------------------
OntologyClient: cliente Python de alto nivel para la ontologia Neo4j de
Marketplace SA Paraguay - Linea Navidad.

Tarea 1 - Bloque 6.

Este es el PRODUCTO FINAL de la primera mitad de la Tarea 1: un wrapper
limpio que el resto del equipo (Tarea 3, 4, 5) va a importar para consultar
la ontologia sin tener que aprender Cypher ni preocuparse por la estructura
del knowledge graph.

Uso basico:

    from ontology import OntologyClient

    with OntologyClient() as ont:
        info = ont.producto("114142")
        proveedores = ont.proveedores_de_sku("114142")
        cat = ont.categoria_de_sku("114142")
        a_reponer = ont.productos_a_reponer(limit=20)
        eventos = ont.eventos_proximos(dias=90)

Las credenciales de Neo4j se leen automaticamente del .env del proyecto.
Tambien se pueden pasar explicitas: OntologyClient(uri=..., user=..., password=...).

Todos los metodos retornan estructuras Python serializables (dicts/listas
con tipos primitivos), no objetos crudos del driver Neo4j. Las fechas se
devuelven como strings ISO 8601.
"""

import os
from typing import Optional
from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver


class OntologyClient:
    """
    Cliente de alto nivel para la ontologia Neo4j (Marketplace SA - Navidad).

    Todos los metodos publicos devuelven dicts/listas con tipos primitivos
    (str, int, float, bool, None) o estructuras anidadas de los mismos.
    Las fechas vuelven como strings ISO 8601 ("2026-04-28T08:00:00").

    Es seguro reutilizar la misma instancia durante toda una sesion. La
    conexion a Neo4j se crea de forma diferida (lazy) en el primer uso.
    Llamar a close() cuando termines, o usarlo como context manager.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        load_dotenv()
        self.uri = uri or os.getenv("NEO4J_URI")
        self.user = user or os.getenv("NEO4J_USER")
        self.password = password or os.getenv("NEO4J_PASSWORD")
        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self._driver.verify_connectivity()
        return self._driver

    def close(self) -> None:
        """Cierra el driver de Neo4j y libera la conexion."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # =========================================================================
    # PRODUCTOS
    # =========================================================================

    def producto(self, sku: str) -> Optional[dict]:
        """
        Devuelve toda la informacion conocida sobre un producto navideño dado,
        incluyendo la JERARQUIA COMPLETA de su clasificacion (categoria, grupo,
        subseccion, seccion).

        Esta es la consulta basica de "ficha de producto". Trae todo lo que el
        operador / agentes necesitan saber sobre un SKU sin tener que hacer
        multiples llamadas: datos comerciales (precio_costo, precio_venta_actual),
        estado de stock (cantidad_stock, en_stock), flag perecedero, fechas y
        toda la jerarquia hasta la seccion raiz.

        Args:
            sku: codigo del producto (CODIGO de Pegasus, ej: "219814").

        Returns:
            Dict con propiedades del producto + dicts hermanos (categoria,
            grupo, subseccion, seccion) cada uno con {id, nombre}.
            None si el SKU no existe en la ontologia.

        Ejemplo:
            >>> ont.producto("219814")
            {'sku': '219814', 'nombre': 'BOLA RAYADA SETX6', 'en_stock': False,
             'precio_costo': 74247.0, 'pais_origen': 'Brasil', ...,
             'categoria':  {'id': 6253, 'nombre': 'ESFERAS'},
             'grupo':      {'id': 1919, 'nombre': 'ADORNOS'},
             'subseccion': {'id': 306,  'nombre': 'NAVIDAD'},
             'seccion':    {'id': 55,   'nombre': 'FESTIVIDADES'}}
        """
        # OPTIONAL MATCH encadenados (no en un solo path) para que si falta
        # algun nivel intermedio no se pierdan los niveles ya encontrados.
        query = """
        MATCH (p:Producto {sku: $sku})
        OPTIONAL MATCH (p)-[:PERTENECE_A]->(c:Categoria)
        OPTIONAL MATCH (c)-[:PERTENECE_A]->(g:Grupo)
        OPTIONAL MATCH (g)-[:PERTENECE_A]->(ss:SubSeccion)
        OPTIONAL MATCH (ss)-[:PERTENECE_A]->(s:Seccion)
        RETURN p AS producto,
               c AS categoria, g AS grupo,
               ss AS subseccion, s AS seccion
        """
        with self.driver.session() as session:
            record = session.run(query, sku=sku).single()
            if record is None:
                return None
            data = dict(record["producto"])
            # Adjuntar la jerarquia completa como dicts hermanos del producto
            for key in ("categoria", "grupo", "subseccion", "seccion"):
                node = record[key]
                data[key] = (
                    {"id": node["id"], "nombre": node["nombre"]}
                    if node else None
                )
            return _serialize(data)

    def productos_en_categoria(self, categoria_id: int, limit: int = 100) -> list[dict]:
        """
        Lista los productos navideños que pertenecen a una categoria dada.

        Args:
            categoria_id: COD_CATEGORIA de Pegasus (ej: 6253 para ESFERAS,
                          6285 para LUCES, 7370 para RAMA).
            limit: maximo de productos a devolver. Default 100.

        Returns:
            Lista de dicts con los campos basicos del producto:
            sku, nombre, cantidad_stock, en_stock, precio_costo,
            precio_venta_actual, perecedero. Ordenado por nombre.
        """
        query = """
        MATCH (p:Producto)-[:PERTENECE_A]->(c:Categoria {id: $cat_id})
        RETURN p.sku AS sku, p.nombre AS nombre,
               p.cantidad_stock AS cantidad_stock,
               p.en_stock AS en_stock,
               p.precio_costo AS precio_costo,
               p.precio_venta_actual AS precio_venta_actual,
               p.perecedero AS perecedero
        ORDER BY p.nombre
        LIMIT $limit
        """
        with self.driver.session() as session:
            return [_serialize(dict(r)) for r in session.run(query, cat_id=categoria_id, limit=limit)]

    def productos_a_reponer(self, limit: int = 50) -> list[dict]:
        """
        Lista los productos navideños SIN stock actual (en_stock=false) que
        tuvieron actividad reciente. Estos son CANDIDATOS A REPOSICION:
        SKUs que vendiste pero ya no tenes en deposito.

        Es la consulta clave para que el optimizador (Tarea 4) y el
        ForecastAgent (Tarea 5) sepan sobre que SKUs sugerir compras.

        Args:
            limit: maximo de productos a devolver. Default 50.

        Returns:
            Lista de dicts con sku, nombre, categoria, precio_costo,
            precio_venta_actual, fecha_ultima_venta, fecha_ultima_compra.
            Ordenado por fecha_ultima_venta descendente (los vendidos
            mas recientemente primero, son los mas urgentes a reponer).
        """
        # Cypher por default pone NULLs al principio en DESC. Forzamos el
        # contrario con un orden compuesto: primero los que tienen fecha
        # (NOT NULL primero), despues por fecha desc. Asi los SKUs con
        # ventas recientes aparecen primero (los mas urgentes a reponer).
        query = """
        MATCH (p:Producto {en_stock: false})
        OPTIONAL MATCH (p)-[:PERTENECE_A]->(c:Categoria)
        RETURN p.sku AS sku, p.nombre AS nombre,
               c.nombre AS categoria,
               p.precio_costo AS precio_costo,
               p.precio_venta_actual AS precio_venta_actual,
               p.fecha_ultima_venta AS fecha_ultima_venta,
               p.fecha_ultima_compra AS fecha_ultima_compra
        ORDER BY p.fecha_ultima_venta IS NULL,  // FALSE (con fecha) antes que TRUE (null)
                 p.fecha_ultima_venta DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return [_serialize(dict(r)) for r in session.run(query, limit=limit)]

    # =========================================================================
    # PROVEEDORES
    # =========================================================================

    def proveedor(self, proveedor_id: int) -> Optional[dict]:
        """
        Devuelve la informacion completa de un proveedor.

        Args:
            proveedor_id: COD_PROVEEDOR de Pegasus (ej: 364 para NORITEX).

        Returns:
            Dict con propiedades del proveedor (id, nombre, ruc, pais,
            email, telefono, proveedor_exterior). None si no existe.
        """
        query = "MATCH (pr:Proveedor {id: $id}) RETURN pr AS proveedor"
        with self.driver.session() as session:
            record = session.run(query, id=proveedor_id).single()
            if record is None:
                return None
            return _serialize(dict(record["proveedor"]))

    def proveedores_de_sku(self, sku: str) -> list[dict]:
        """
        Devuelve los proveedores que historicamente suministraron un SKU
        dado, junto con las CONDICIONES COMERCIALES agregadas de cada
        relacion (ultima fecha de compra, ultimo precio en PYG, ultima
        cantidad pedida, total de cantidad historica, total de lineas
        de compra).

        Esta es la consulta MAS USADA por la Tarea 4 (optimizador) y
        Tarea 5 (SupplierAgent): cuando hay que decidir a quien comprarle,
        este metodo devuelve la lista de candidatos con su track record.

        Args:
            sku: codigo del producto.

        Returns:
            Lista de dicts. Cada uno fusiona los datos del proveedor con
            las propiedades de la arista SUMINISTRADO_POR. Ordenado por
            ultima_fecha_compra descendente. Vacio si el SKU no tiene
            proveedores registrados (cold-start de proveedor).
        """
        query = """
        MATCH (p:Producto {sku: $sku})-[r:SUMINISTRADO_POR]->(pr:Proveedor)
        RETURN pr AS proveedor,
               r.ultima_fecha_compra        AS ultima_fecha_compra,
               r.ultimo_precio_pyg          AS ultimo_precio_pyg,
               r.ultima_cantidad            AS ultima_cantidad,
               r.total_cantidad_historica   AS total_cantidad_historica,
               r.total_lineas_compra        AS total_lineas_compra
        ORDER BY r.ultima_fecha_compra DESC
        """
        with self.driver.session() as session:
            out = []
            for r in session.run(query, sku=sku):
                d = dict(r["proveedor"])
                d["ultima_fecha_compra"]      = r["ultima_fecha_compra"]
                d["ultimo_precio_pyg"]        = r["ultimo_precio_pyg"]
                d["ultima_cantidad"]          = r["ultima_cantidad"]
                d["total_cantidad_historica"] = r["total_cantidad_historica"]
                d["total_lineas_compra"]      = r["total_lineas_compra"]
                out.append(_serialize(d))
            return out

    def proveedores_similares(self, proveedor_id: int, limit: int = 10) -> list[dict]:
        """
        Devuelve proveedores similares a uno dado, definidos como aquellos
        que abastecen al menos UNA categoria en comun con el proveedor de
        referencia.

        Util para el agente critico adversarial (Tarea 5) y el motor
        contrafactual (Tarea 4): cuando el operador pregunta "que pasa si
        el proveedor X quiebra?", este metodo devuelve los candidatos
        plausibles para sustituirlo.

        Args:
            proveedor_id: COD_PROVEEDOR del proveedor de referencia.
            limit: maximo de proveedores similares a devolver. Default 10.

        Returns:
            Lista de dicts con datos del proveedor candidato + cantidad
            de categorias que tiene en comun con el referencia. Ordenado
            por categorias_en_comun descendente (mas afines primero).
        """
        query = """
        MATCH (orig:Proveedor {id: $id})
              <-[:SUMINISTRADO_POR]-(p1:Producto)-[:PERTENECE_A]->(c:Categoria)
              <-[:PERTENECE_A]-(p2:Producto)-[:SUMINISTRADO_POR]->(otros:Proveedor)
        WHERE otros.id <> orig.id
        WITH otros, count(DISTINCT c) AS categorias_en_comun
        RETURN otros AS proveedor, categorias_en_comun
        ORDER BY categorias_en_comun DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            out = []
            for r in session.run(query, id=proveedor_id, limit=limit):
                d = dict(r["proveedor"])
                d["categorias_en_comun"] = r["categorias_en_comun"]
                out.append(_serialize(d))
            return out

    # =========================================================================
    # JERARQUIA DE CATEGORIAS
    # =========================================================================

    def categoria_de_sku(self, sku: str) -> Optional[dict]:
        """
        Devuelve la categoria de un SKU junto con la JERARQUIA COMPLETA
        (Categoria -> Grupo -> SubSeccion -> Seccion) y atributos
        agregados a nivel categoria.

        La jerarquia completa es lo que da contexto util: una categoria
        llamada 'GRANDE' por si sola es ambigua, pero saber que pertenece
        al Grupo 'BANDEJAS' la situa correctamente.

        Estos agregados son lo que la Tarea 3 (forecasting) va a usar
        para resolver COLD-START: cuando un SKU no tiene historia propia
        suficiente, hereda el patron estacional de su categoria/grupo.

        Args:
            sku: codigo del producto.

        Returns:
            Dict con:
              - id, nombre: la categoria
              - grupo: dict con id/nombre del grupo padre
              - subseccion: dict con id/nombre de la subseccion abuela
              - seccion: dict con id/nombre de la seccion bisabuela
              - cantidad_productos: total de SKUs en la categoria
              - cantidad_en_stock: cuantos estan actualmente en stock
              - cantidad_perecederos: cuantos son perecederos
            None si el SKU no existe o no tiene categoria asignada.
        """
        query = """
        MATCH (p:Producto {sku: $sku})-[:PERTENECE_A]->(c:Categoria)
              -[:PERTENECE_A]->(g:Grupo)
              -[:PERTENECE_A]->(ss:SubSeccion)-[:PERTENECE_A]->(s:Seccion)
        WITH c, g, ss, s
        OPTIONAL MATCH (otros:Producto)-[:PERTENECE_A]->(c)
        RETURN c.id AS cat_id, c.nombre AS cat_nombre,
               g.id AS g_id, g.nombre AS g_nombre,
               ss.id AS ss_id, ss.nombre AS ss_nombre,
               s.id  AS s_id,  s.nombre  AS s_nombre,
               count(otros) AS cantidad_productos,
               sum(CASE WHEN otros.en_stock THEN 1 ELSE 0 END) AS cantidad_en_stock,
               sum(CASE WHEN otros.perecedero THEN 1 ELSE 0 END) AS cantidad_perecederos
        """
        with self.driver.session() as session:
            r = session.run(query, sku=sku).single()
            if r is None:
                return None
            return {
                "id":     r["cat_id"],
                "nombre": r["cat_nombre"],
                "grupo":      {"id": r["g_id"],  "nombre": r["g_nombre"]},
                "subseccion": {"id": r["ss_id"], "nombre": r["ss_nombre"]},
                "seccion":    {"id": r["s_id"],  "nombre": r["s_nombre"]},
                "cantidad_productos":   r["cantidad_productos"],
                "cantidad_en_stock":    r["cantidad_en_stock"],
                "cantidad_perecederos": r["cantidad_perecederos"],
            }

    def categorias(self) -> list[dict]:
        """
        Lista todas las categorias del catalogo navideño con sus conteos
        agregados. Util para dashboards / overviews.

        Returns:
            Lista de dicts con id, nombre, cantidad_productos,
            cantidad_en_stock. Ordenado por cantidad_productos descendente.
        """
        query = """
        MATCH (c:Categoria)<-[:PERTENECE_A]-(p:Producto)
        RETURN c.id AS id, c.nombre AS nombre,
               count(p) AS cantidad_productos,
               sum(CASE WHEN p.en_stock THEN 1 ELSE 0 END) AS cantidad_en_stock
        ORDER BY cantidad_productos DESC
        """
        with self.driver.session() as session:
            return [dict(r) for r in session.run(query)]

    # =========================================================================
    # SUSTITUTOS
    # =========================================================================

    def sustitutos_de_sku(self, sku: str) -> list[dict]:
        """
        Devuelve productos sustitutos de un SKU dado.

        IMPORTANTE: la arista [:SUSTITUYE_A] todavia NO se carga
        automaticamente en la ontologia (no hay senal ya disponible para
        inferirla). Este metodo existe como parte del contrato de la API,
        pero por ahora devuelve []. En una iteracion futura se va a
        poblar mediante: (a) similaridad de descripcion via embeddings,
        o (b) reglas manuales (mismo nombre/categoria distinto SKU).

        Returns:
            Por ahora []. Eventualmente: lista de dicts {sku, nombre,
            score_similaridad}.
        """
        return []

    # =========================================================================
    # EVENTOS COMERCIALES
    # =========================================================================

    def eventos_proximos(self, dias: int = 60) -> list[dict]:
        """
        Devuelve los eventos comerciales que caen dentro de los proximos
        N dias contados desde hoy.

        Util para que el optimizador (Tarea 4) y el chatbot (Tarea 5)
        sepan cuanto tiempo queda hasta el proximo hito comercial
        (Black Friday, Navidad, etc.) y ajusten el lead time aceptable.

        Args:
            dias: cantidad de dias hacia adelante a considerar. Default 60.

        Returns:
            Lista de dicts con id, nombre, fecha (string ISO), tipo y
            dias_hasta_evento. Ordenado cronologicamente.
        """
        # NOTA: usamos duration.inDays(...).days en vez de duration.between(...).days
        # porque .between separa la duracion en (años, meses, dias) y .days te
        # devuelve solo el residuo de dias dentro del ultimo mes, no el total.
        query = """
        MATCH (e:EventoComercial)
        WHERE e.fecha >= date() AND e.fecha <= date() + duration({days: $dias})
        RETURN e.id AS id, e.nombre AS nombre,
               toString(e.fecha) AS fecha, e.tipo AS tipo,
               duration.inDays(date(), e.fecha).days AS dias_hasta_evento
        ORDER BY e.fecha
        """
        with self.driver.session() as session:
            return [dict(r) for r in session.run(query, dias=dias)]


# =============================================================================
# Helpers privados
# =============================================================================

def _serialize(obj):
    """
    Convierte tipos Neo4j (Date, DateTime, Time) a strings ISO para que
    los resultados sean JSON-serializables y faciles de interoperar.
    Estructuras anidadas (dict/list) se procesan recursivamente.
    """
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if hasattr(obj, "iso_format"):  # neo4j.time.Date / DateTime
        return obj.iso_format()
    return obj
