// =============================================================================
// schema.cypher v3 - Modelo refinado post diagnostico de columnas
// Marketplace SA Paraguay - Linea Navidad
// Tarea 1: Ontologia y RAG
// =============================================================================
// Cambios respecto a v2:
//   - Removidas propiedades muertas (dias_validez, peso, volumen_cc del producto;
//     ciudad, lead_time_dias, plazo_pago_dias, porc_bonificacion del proveedor).
//   - perecedero ahora se calcula en el loader desde el nombre de la categoria.
//   - precio_venta se cargara desde la ultima venta real (VENTAS_DET.PRECIO_LISTA).
// =============================================================================


// CONSTRAINTS DE UNICIDAD ----------------------------------------------------

CREATE CONSTRAINT seccion_id_unique IF NOT EXISTS
FOR (s:Seccion) REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT subseccion_id_unique IF NOT EXISTS
FOR (ss:SubSeccion) REQUIRE ss.id IS UNIQUE;

// Grupo: nivel intermedio entre SubSeccion y Categoria (de tabla GRUPO en Pegasus)
CREATE CONSTRAINT grupo_id_unique IF NOT EXISTS
FOR (g:Grupo) REQUIRE g.id IS UNIQUE;

CREATE CONSTRAINT categoria_id_unique IF NOT EXISTS
FOR (c:Categoria) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT producto_sku_unique IF NOT EXISTS
FOR (p:Producto) REQUIRE p.sku IS UNIQUE;

CREATE CONSTRAINT proveedor_id_unique IF NOT EXISTS
FOR (pr:Proveedor) REQUIRE pr.id IS UNIQUE;

CREATE CONSTRAINT evento_id_unique IF NOT EXISTS
FOR (e:EventoComercial) REQUIRE e.id IS UNIQUE;


// INDICES --------------------------------------------------------------------

CREATE INDEX producto_nombre IF NOT EXISTS
FOR (p:Producto) ON (p.nombre);

CREATE INDEX proveedor_nombre IF NOT EXISTS
FOR (pr:Proveedor) ON (pr.nombre);

CREATE INDEX producto_pais_origen IF NOT EXISTS
FOR (p:Producto) ON (p.pais_origen);

CREATE INDEX proveedor_pais IF NOT EXISTS
FOR (pr:Proveedor) ON (pr.pais);

CREATE INDEX evento_fecha IF NOT EXISTS
FOR (e:EventoComercial) ON (e.fecha);


// =============================================================================
// MODELO LOGICO (documentacion - no Cypher ejecutable)
// =============================================================================
// :Seccion         { id, nombre }
// :SubSeccion      { id, nombre }
// :Grupo           { id, nombre }   <- nivel intermedio Pegasus (tabla GRUPO)
// :Categoria       { id, nombre }
// :Producto        { sku, codigo_barras, nombre, nombre_corto, unidad,
//                    pais_origen, perecedero (derivado), precio_costo,
//                    precio_venta_actual (de VENTAS_DET, opcional),
//                    cantidad_stock (suma de MOVIMIENTOS_DEPOSITOS),
//                    en_stock (bool, true si cantidad_stock >= 1),
//                    fecha_ultima_compra, fecha_ultima_venta,
//                    fecha_ultima_actualizacion, fecha_alta }
//
// Universo de productos cargados: navideños (cod_sub_seccion=306) que
// tengan stock actual O ventas/compras desde 2024-01-01. Esto permite
// que el optimizador (Tarea 4) sugiera REPOSICION de SKUs sin stock
// que vendieron bien recientemente.
// :Proveedor       { id, nombre, ruc, pais, email, telefono,
//                    proveedor_exterior }
// :EventoComercial { id, nombre, fecha, tipo }
//
// Relaciones (jerarquia 4 niveles):
//   (:SubSeccion)-[:PERTENECE_A]->(:Seccion)
//   (:Grupo)-[:PERTENECE_A]->(:SubSeccion)
//   (:Categoria)-[:PERTENECE_A]->(:Grupo)
//   (:Producto)-[:PERTENECE_A]->(:Categoria)
//   (:Producto)-[:SUMINISTRADO_POR
//                {ultima_fecha_compra, ultimo_precio_pyg,
//                 ultima_cantidad, total_cantidad_historica,
//                 total_lineas_compra}
//              ]->(:Proveedor)
//
// Propiedades NO incluidas (columnas dead en Pegasus):
//   - producto.peso, producto.volumen_cc, producto.dias_validez
//   - proveedor.ciudad (siempre Asuncion, dato del importador)
//   - proveedor.lead_time_dias (PALZO_ENTREGA = 0 para todos)
//   - proveedor.plazo_pago_dias (PALZO_PAGO = 0 para todos)
//   - proveedor.porc_bonificacion (PORCENTAJE_BONIF = 0 para todos)
// Estas propiedades vendran del agente de web research (Tarea 2) o de la
// extraccion del RAG sobre catalogos (Tarea 1 - parte 2).
