# PROYECTO NASA — DOCUMENTO DE DISEÑO TÉCNICO BACKEND
# Versión: 1.0 | Owner: Mateo + Iván | Cobertura: Tareas 2, 4, 5

================================================================
SECCIÓN 0 — META-CONTEXTO Y PERSONA
================================================================

Sos un Senior Staff Engineer con 15 años de experiencia construyendo:
- Sistemas de decisión empresarial bajo incertidumbre
- Optimización matemática (programación lineal, MILP, programación 
  estocástica, chance-constrained programming)
- Orquestación de LLMs en producción (LangGraph, LangChain, 
  function calling con Gemini/OpenAI)
- Sistemas de retrieval (RAG con vector stores, ontologías en grafo)
- Backend distribuido (FastAPI, async, observabilidad)

Tu mentalidad:
1. Contratos antes que implementación
2. Mocks honestos que se reemplazan sin romper nada
3. Trazabilidad completa de cada decisión
4. Defaults seguros: si algo falla, degradás funcionalidad, no rompés
5. Cada decisión técnica se justifica por valor en el demo o por 
   robustez del sistema

================================================================
SECCIÓN 1 — DOMINIO DEL PROBLEMA
================================================================

PROBLEMA DE NEGOCIO:
Un retail de productos navideños debe decidir semanalmente:
- QUÉ SKUs comprar para abastecerse antes de eventos comerciales 
  (Black Friday, Navidad, Reyes)
- CUÁNTO comprar de cada uno
- A QUÉ proveedor (con distintos lead times, MOQs, precios, 
  descuentos por volumen, confiabilidad)
- BAJO QUÉ INCERTIDUMBRE de demanda (productos estacionales, 
  modas virales, eventos macro)

DIFICULTADES INHERENTES:
- Demanda altamente estacional con varianza alta
- Productos perecederos con ventana de venta limitada
- Lead times largos de proveedores asiáticos vs precios bajos
- MOQs que crean discontinuidades (compro 0 o compro 1000)
- Productos virales emergentes que no aparecen en histórico
- Restricciones presupuestarias y de capital de trabajo

NATURALEZA DE LA SOLUCIÓN:
Sistema de soporte a decisiones (NO autónomo) que:
- Sugiere y explica
- Cuantifica incertidumbre (no recomienda valores puntuales)
- Ataca sus propias propuestas (red-teaming)
- Permite simular escenarios alternativos
- Aprende del operador específico que lo usa

================================================================
SECCIÓN 2 — ACTORES Y PERSPECTIVAS
================================================================

ACTOR 1: OPERADOR DE COMPRAS (USUARIO PRIMARIO)
- Persona no técnica, conoce el negocio
- Toma decisiones bajo presión semanal
- Necesita: confianza calibrada, justificación visual, 
  capacidad de simular escenarios, control final
- Interactúa con: dashboard, vista de recomendaciones, 
  chat conversacional, panel de notificaciones

ACTOR 2: DUEÑO DEL NEGOCIO (STAKEHOLDER)
- Mide el sistema por: capital inmovilizado, ventas perdidas, 
  ROI de inventario, valor en riesgo (VaR)
- No interactúa día a día, recibe reportes ejecutivos

ACTOR 3: PROVEEDOR (USUARIO INDIRECTO)
- Recibe los borradores de negociación generados por el sistema
- No ve el sistema, solo los emails

ACTOR 4: EQUIPO DE DESARROLLO
- Abi: ontología y RAG (consume tu API y entrega clientes Python)
- Mauri/Mati: agentes (no van a llegar — vos cubrís)
- Franky: frontend APEX (consume tus endpoints HTTP)
- Iván: tu compañero de backend (puede tomar componentes)

ACTOR 5: VOS COMO ARQUITECTO
- Optimizás: tiempo de implementación × valor en demo × robustez
- Si algo no se ve en el pitch, va al final de la cola

================================================================
SECCIÓN 3 — ARQUITECTURA EN CAPAS
================================================================

CAPA 7 — INTERFAZ HTTP (FastAPI Routers)
   ↓
CAPA 6 — ORQUESTACIÓN (Multi-Agent Orchestrator)
   ↓
CAPA 5 — AGENTES ESPECIALIZADOS (Supplier, Forecast, Optimizer, 
         Critic, Negotiator, Researcher, TrendDetector)
   ↓
CAPA 4 — SERVICIOS DE DOMINIO (Forecast, MonteCarlo, Optimizer 
         estocástico, Contrafactual, PreferenceLearner)
   ↓
CAPA 3 — CLIENTES DE DATOS (Ontología, RAG, DataLoader, 
         WebFetcher con Playwright)
   ↓
CAPA 2 — CONTRATOS (Pydantic Schemas) — INMUTABLES UNA VEZ DEFINIDOS
   ↓
CAPA 1 — DATOS (CSVs sintéticos, JSON de perfil, grafo provisional, 
         documentos PDF ficticios)

REGLA: cada capa solo conoce la inmediatamente inferior.
EXCEPCIÓN: la capa 7 puede acceder a la 4 directamente para 
endpoints utilitarios (debugging, healthcheck).

================================================================
SECCIÓN 4 — ESTRUCTURA DE DIRECTORIOS COMPLETA
================================================================

proyecto-nasa-backend/
├── main.py
├── config.py                          # settings con pydantic-settings
├── requirements.txt
├── .env.example
├── README.md
├── DESIGN.md                          # este documento
├── docker-compose.yml                 # opcional
│
├── schemas/                           # CAPA 2
│   ├── __init__.py
│   ├── productos.py
│   ├── proveedores.py
│   ├── eventos.py
│   ├── recomendaciones.py
│   ├── simulacion.py
│   ├── contrafactual.py
│   ├── agentes.py
│   ├── tendencias.py
│   ├── grafo_causal.py
│   ├── preferencias.py
│   ├── chat.py
│   └── errores.py
│
├── data/                              # CAPA 1
│   ├── catalogo_productos.csv
│   ├── proveedores.csv
│   ├── relacion_producto_proveedor.csv
│   ├── ventas_historicas.csv
│   ├── inventario_actual.csv
│   ├── eventos_comerciales.csv
│   ├── catalogos_proveedor/           # PDFs ficticios para RAG
│   │   ├── proveedor_001_catalogo.pdf
│   │   └── ...
│   ├── recomendaciones/               # cache de recomendaciones generadas
│   ├── perfiles/
│   │   └── perfil_operador.json
│   ├── grafo_provisional.json         # mock de ontología
│   ├── feedback_log.jsonl             # append-only de FeedbackSignals
│   └── tendencias_cache.json
│
├── data_generator/
│   ├── __init__.py
│   ├── generate_csvs.py
│   ├── generate_pdfs.py               # PDFs ficticios para RAG
│   ├── generate_social_posts.py       # textos simulados de redes
│   └── seed.py                        # entrypoint
│
├── clients/                           # CAPA 3
│   ├── __init__.py
│   ├── ontologia_client.py            # MOCK reemplazable por Neo4j
│   ├── rag_client.py                  # MOCK reemplazable por vector store
│   ├── data_loader.py                 # carga y cachea CSVs
│   ├── web_fetcher.py                 # Playwright async
│   ├── llm_client.py                  # wrapper sobre Gemini con retry/fallback
│   └── cache.py                       # cache TTL en memoria
│
├── services/                          # CAPA 4
│   ├── __init__.py
│   ├── forecast/
│   │   ├── __init__.py
│   │   ├── seasonal_decompose.py
│   │   ├── ets_model.py               # exponential smoothing
│   │   ├── prophet_model.py           # opcional
│   │   ├── cold_start.py              # forecast desde categoría
│   │   └── forecast_service.py        # interfaz unificada
│   ├── monte_carlo/
│   │   ├── __init__.py
│   │   ├── distributions.py           # samplers
│   │   ├── simulator.py               # motor principal
│   │   ├── correlations.py            # correlaciones entre SKUs
│   │   └── risk_metrics.py            # VaR, CVaR, percentiles
│   ├── optimizer/
│   │   ├── __init__.py
│   │   ├── milp_solver.py             # PuLP base
│   │   ├── chance_constraints.py      # SAA (Sample Average Approx)
│   │   ├── two_stage_stochastic.py    # programa estocástico de 2 etapas
│   │   ├── benders_decomposition.py   # opcional para escalabilidad
│   │   ├── heuristic_fallback.py      # greedy si solver no converge
│   │   └── optimizer_service.py       # interfaz unificada
│   ├── contrafactual/
│   │   ├── __init__.py
│   │   ├── perturbations.py           # catálogo de perturbaciones
│   │   ├── nl_parser.py               # parsea NL del operador a Perturbacion
│   │   ├── reoptimizer.py             # re-corre solver con perturbación
│   │   └── diff_engine.py             # calcula diff entre planes
│   ├── web_research/
│   │   ├── __init__.py
│   │   ├── source_registry.py         # registro de fuentes confiables
│   │   ├── extractor.py               # Playwright + LLM
│   │   ├── cross_validator.py         # valida coherencia entre fuentes
│   │   ├── confidence_scorer.py       # scoring por fuente y consistencia
│   │   └── research_service.py
│   ├── trends/
│   │   ├── __init__.py
│   │   ├── signal_collector.py        # mock o scraping real
│   │   ├── virality_detector.py       # análisis de menciones + crecimiento
│   │   ├── cross_platform_aggregator.py
│   │   └── trends_service.py
│   ├── critic/
│   │   ├── __init__.py
│   │   ├── attack_strategies.py       # cada estrategia de red-teaming
│   │   ├── scenario_generator.py
│   │   ├── vulnerability_scorer.py
│   │   └── critic_service.py
│   ├── negotiator/
│   │   ├── __init__.py
│   │   ├── tone_adapter.py            # adapta tono según historial
│   │   ├── volume_calculator.py       # calcula volumen acumulado
│   │   ├── discount_justifier.py      # genera justificación cuantitativa
│   │   └── negotiator_service.py
│   ├── preference_learning/
│   │   ├── __init__.py
│   │   ├── profile_model.py           # estructura del perfil
│   │   ├── update_rules.py            # reglas incrementales
│   │   ├── bayesian_updater.py        # opcional: update bayesiano
│   │   ├── inverse_rl.py              # opcional: IRL desde feedback
│   │   └── preference_service.py
│   └── causal_graph/
│       ├── __init__.py
│       ├── graph_builder.py           # construye grafo desde recomendación
│       ├── influence_calculator.py    # shadow prices, sensibilidad
│       └── graph_service.py
│
├── agents/                            # CAPA 5 + 6
│   ├── __init__.py
│   ├── base_agent.py                  # clase abstracta
│   ├── tools.py                       # registro de tools con docstrings
│   ├── state.py                       # SharedAgentState
│   ├── orchestrator.py                # router de intención + state machine
│   ├── intent_classifier.py
│   ├── supplier_agent.py
│   ├── forecast_agent.py
│   ├── optimizer_agent.py
│   ├── critic_agent.py
│   ├── negotiator_agent.py
│   ├── researcher_agent.py
│   ├── trends_agent.py
│   └── memory.py                      # memoria de conversación
│
├── routers/                           # CAPA 7
│   ├── __init__.py
│   ├── health.py
│   ├── productos.py
│   ├── proveedores.py
│   ├── inventario.py
│   ├── recomendaciones.py
│   ├── simulacion.py
│   ├── contrafactual.py
│   ├── chat.py
│   ├── agentes.py
│   ├── negociacion.py
│   ├── feedback.py
│   ├── grafo.py
│   ├── perfil.py
│   └── tendencias.py
│
├── middleware/
│   ├── __init__.py
│   ├── logging_middleware.py
│   ├── error_handler.py
│   └── request_id.py
│
├── observability/
│   ├── __init__.py
│   ├── logger.py                      # loguru config
│   ├── metrics.py                     # contadores in-memory
│   └── tracing.py                     # spans de cada request
│
└── tests/
    ├── __init__.py
    ├── smoke_test.py                  # flujo end-to-end del demo
    ├── test_optimizer.py
    ├── test_monte_carlo.py
    └── test_contrafactual.py

================================================================
SECCIÓN 5 — CONTRATOS DE DATOS (PYDANTIC v2)
================================================================

[Para cada schema, definir: clase, campos, validators, ejemplos]

# schemas/productos.py
class Producto(BaseModel):
    sku: str                            # identificador único
    nombre: str
    categoria_id: str
    perecedero: bool
    vida_util_dias: int | None
    precio_referencia: float            # precio de venta sugerido
    margen_objetivo: float              # margen % esperado
    descripcion: str
    tags: list[str]                     # luces, exterior, premium, etc.

class Categoria(BaseModel):
    categoria_id: str
    nombre: str
    patron_estacional: list[float]      # 52 floats normalizados
    elasticidad_precio: float           # opcional, para análisis avanzado

# schemas/proveedores.py
class TramoDescuento(BaseModel):
    cantidad_minima: int
    descuento_porcentaje: float

class Proveedor(BaseModel):
    proveedor_id: str
    nombre: str
    pais: str
    region: Literal["nacional", "regional", "asia", "europa", "otros"]
    lead_time_dias_min: int
    lead_time_dias_max: int
    confiabilidad: float                # 0-1, históricamente entregaron a tiempo
    reputacion_score: float             # 0-1, calidad/comunicación
    moneda: str                         # USD, EUR, ARS, CNY
    permite_negociacion_volumen: bool
    contacto: dict                      # email, telefono, idioma_preferido

class RelacionComercial(BaseModel):
    proveedor_id: str
    sku: str
    precio_unitario: float
    moq: int
    descuentos_volumen: list[TramoDescuento]
    moneda: str
    activo: bool

# schemas/eventos.py
class EventoComercial(BaseModel):
    evento_id: str
    nombre: str                         # "Black Friday 2026"
    fecha_objetivo: date
    semanas_pico: list[int]             # qué semanas del año son pico
    boost_demanda: float                # multiplicador de demanda esperado

# schemas/simulacion.py
class ForecastResult(BaseModel):
    sku: str
    semana_objetivo: int
    media: float
    std: float
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    metodo: Literal["ets", "prophet", "categoria_cold_start", "tendencia"]
    intervalo_confianza_calibrado: bool
    samples: list[float] | None         # opcional, si querés pasarlos directo

class MetricasRiesgo(BaseModel):
    stock_muerto_esperado: float
    stock_muerto_p95: float
    ventas_perdidas_esperadas: float
    ventas_perdidas_p95: float
    costo_total: float
    retorno_esperado: float
    retorno_p5: float
    retorno_p95: float
    var_95: float                       # Value at Risk 95%
    cvar_95: float                      # Conditional VaR (expected shortfall)
    probabilidad_perdida: float         # P(retorno < 0)
    sharpe_ratio: float | None

class ResultadoMonteCarlo(BaseModel):
    n_simulaciones: int
    metricas: MetricasRiesgo
    distribucion_retorno: list[float]   # samples para histograma
    distribucion_stock_muerto: list[float]
    distribucion_ventas_perdidas: list[float]
    seed: int                           # para reproducibilidad

# schemas/recomendaciones.py
class ItemCompra(BaseModel):
    sku: str
    proveedor_id: str
    cantidad: int
    costo_unitario: float
    descuento_aplicado: float
    costo_total: float
    fecha_pedido_estimada: date
    fecha_arribo_estimada: date
    semanas_buffer_pre_evento: float    # cuánto antes del evento llega

class Vulnerabilidad(BaseModel):
    tipo: Literal["RETRASO_ADUANERO", "CAIDA_DEMANDA", 
                  "QUIEBRE_PROVEEDOR", "OBSOLESCENCIA_POST_EVENTO",
                  "TIPO_CAMBIO_ADVERSO", "COMPETIDOR_DESCUENTO",
                  "FALLA_CALIDAD"]
    descripcion: str
    probabilidad_estimada: float
    impacto_usd_esperado: float
    impacto_usd_p95: float
    severidad: Literal["BAJA", "MEDIA", "ALTA", "CRITICA"]
    items_afectados: list[str]          # SKUs afectados
    mitigacion_sugerida: str | None

class Recomendacion(BaseModel):
    recomendacion_id: str
    timestamp: datetime
    operador_id: str
    evento_objetivo_id: str
    items: list[ItemCompra]
    metricas: MetricasRiesgo
    vulnerabilidades: list[Vulnerabilidad]
    grafo_causal_id: str                # FK a GrafoCausal cacheado
    justificacion_texto: str
    nivel_confianza_global: float
    perfil_operador_aplicado: str       # snapshot del perfil usado
    estado: Literal["BORRADOR", "PRESENTADA", "APROBADA", 
                    "MODIFICADA", "RECHAZADA"]
    presupuesto_consumido: float
    presupuesto_total: float | None

# schemas/contrafactual.py
class Perturbacion(BaseModel):
    tipo: Literal["QUIEBRE_PROVEEDOR", "CAMBIO_DEMANDA",
                  "ADELANTO_EVENTO", "ATRASO_EVENTO",
                  "CAMBIO_PRESUPUESTO", "TIPO_CAMBIO",
                  "MOQ_CAMBIA", "LEAD_TIME_CAMBIA",
                  "NUEVO_COMPETIDOR", "CUSTOM"]
    parametros: dict
    descripcion_natural: str            # cómo lo escribió el operador

class DiffPlan(BaseModel):
    items_agregados: list[ItemCompra]
    items_removidos: list[ItemCompra]
    items_modificados: list[dict]       # antes/después
    delta_costo_total: float
    delta_retorno_esperado: float
    delta_var: float
    nuevos_proveedores_incluidos: list[str]
    proveedores_excluidos: list[str]

class EscenarioContrafactual(BaseModel):
    escenario_id: str
    recomendacion_base_id: str
    perturbacion: Perturbacion
    recomendacion_alterna: Recomendacion
    diff: DiffPlan
    factibilidad: Literal["FACTIBLE", "FACTIBLE_DEGRADADO", 
                          "INFACTIBLE"]
    explicacion_natural: str

# schemas/grafo_causal.py
class NodoCausal(BaseModel):
    id: str
    tipo: Literal["sku", "proveedor", "categoria", "evento",
                  "restriccion", "tendencia", "vulnerabilidad"]
    label: str
    peso_influencia: float              # cuánto influyó en la decisión
    metadata: dict

class AristaCausal(BaseModel):
    source_id: str
    target_id: str
    tipo_relacion: Literal["SUMINISTRA", "PERTENECE_A", "SUSTITUYE",
                            "COMPLEMENTA", "AFECTA", "RESTRINGE",
                            "INFLUYE_POSITIVO", "INFLUYE_NEGATIVO"]
    peso: float                         # magnitud de la relación
    explicacion: str

class GrafoCausal(BaseModel):
    grafo_id: str
    recomendacion_id: str
    nodos: list[NodoCausal]
    aristas: list[AristaCausal]
    nodo_central_id: str                # SKU u objetivo principal

# schemas/agentes.py
class ToolCall(BaseModel):
    tool_name: str
    arguments: dict
    result: dict | None
    error: str | None
    duration_ms: float
    timestamp: datetime

class AgentTrace(BaseModel):
    agent_name: str
    input_summary: str
    output_summary: str
    tool_calls: list[ToolCall]
    reasoning: str | None
    duration_ms: float

class IntentClassification(BaseModel):
    intent: Literal["CONSULTA_PRODUCTO", "SOLICITAR_RECOMENDACION",
                    "CONTRAFACTUAL", "APROBAR_RECOMENDACION",
                    "MODIFICAR_RECOMENDACION", "RECHAZAR_RECOMENDACION",
                    "PEDIR_BORRADOR_NEGOCIACION",
                    "INVESTIGAR_NUEVO", "CONSULTAR_TENDENCIAS",
                    "EXPLICAR_DECISION", "SALUDO", "OTRO"]
    confianza: float
    entidades_extraidas: dict
    requiere_confirmacion: bool

# schemas/tendencias.py
class FuenteTendencia(BaseModel):
    plataforma: Literal["TIKTOK", "INSTAGRAM", "PINTEREST",
                        "GOOGLE_TRENDS", "REDDIT", "FORO"]
    url: str | None
    fecha_observacion: datetime
    metricas: dict                      # views, likes, shares, growth_rate

class TendenciaDetectada(BaseModel):
    tendencia_id: str
    producto_emergente: str
    categoria_estimada: str
    motivo_viralidad: str
    fuentes: list[FuenteTendencia]
    nivel_confianza: float
    velocidad_crecimiento: float        # %/semana estimado
    fecha_deteccion: datetime
    estado: Literal["PROVISIONAL", "VALIDADO", "DESCARTADO"]
    semanas_anticipacion_estimadas: int

class NodoProvisional(BaseModel):
    nodo_id: str
    tipo: Literal["producto", "proveedor", "tendencia"]
    datos: dict
    origen: Literal["web_research", "tendencia", "manual"]
    confianza: float
    fuentes: list[str]
    fecha_creacion: datetime
    requiere_revision: bool

# schemas/preferencias.py
class FeedbackSignal(BaseModel):
    feedback_id: str
    recomendacion_id: str
    operador_id: str
    accion: Literal["APROBAR", "MODIFICAR", "RECHAZAR", 
                    "POSTERGAR", "DELEGAR"]
    cambios: dict | None                # qué modificó
    razones_texto: str | None
    timestamp: datetime

class PerfilOperador(BaseModel):
    operador_id: str
    aversion_stockout: float            # 0-1
    aversion_capital_inmovilizado: float
    sensibilidad_precio: float
    sensibilidad_lead_time: float
    sensibilidad_calidad: float
    preferencia_proveedor_conocido: float
    tolerancia_riesgo: float
    horizonte_planeacion_preferido_semanas: int
    historial_feedback: list[str]       # feedback_ids
    version: int                        # se incrementa en cada update
    confianza_perfil: float             # 0-1, sube con más feedback

# schemas/chat.py
class ChatMessage(BaseModel):
    mensaje_id: str
    sesion_id: str
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    agent_traces: list[AgentTrace] | None
    objetos_adjuntos: dict | None       # Recomendacion, Escenario, etc.
    timestamp: datetime

class SesionChat(BaseModel):
    sesion_id: str
    operador_id: str
    mensajes: list[ChatMessage]
    contexto_activo: dict               # última recomendación, etc.

# schemas/errores.py
class ErrorRespuesta(BaseModel):
    error_code: str
    message: str
    details: dict | None
    timestamp: datetime
    request_id: str

================================================================
SECCIÓN 6 — ESPECIFICACIÓN DE MÓDULOS
================================================================

----------------------------------------------------------------
MÓDULO data_generator/generate_csvs.py
----------------------------------------------------------------
PROPÓSITO: generar dataset sintético verosímil.

ENTRADA: random_seed
SALIDA: 6 CSVs en data/

ALGORITMO:
1. Definir 8 categorías navideñas con patrones estacionales:
   - Función base: seno(2π * (semana - 47) / 52) + 1, recortado a [0, 2]
   - Multiplicador específico por categoría (luces tiene pico más alto, 
     embalaje tiene pico más extendido)
2. Generar 50 SKUs:
   - Distribución 8-10 SKUs por categoría
   - 15% perecederos con vida_util uniforme(30, 90)
   - precio_referencia ~ lognormal según categoría
   - margen objetivo entre 25-60%
3. Generar 6 proveedores con perfiles diferenciados:
   - PROV_NAC_01 (nacional): lead 7-14d, MOQ bajo (10-50), precio +20%
   - PROV_NAC_02 (nacional): lead 10-20d, MOQ medio, precio +15%
   - PROV_ASIA_01 (China): lead 45-60d, MOQ alto (500-2000), precio -30%, 
     descuentos por volumen agresivos
   - PROV_ASIA_02 (China): lead 60-75d, MOQ muy alto, precio -40%
   - PROV_EUR_01 (Italia): lead 30-45d, MOQ medio, precio +30% (premium)
   - PROV_REG_01 (Brasil): lead 15-25d, MOQ medio, precio +5%
4. Matriz proveedor-SKU:
   - Cada SKU tiene 1-3 proveedores
   - Asignación pesada por afinidad categoría-región
5. Ventas históricas (104 semanas):
   - venta(sku, semana) = patron_categoria(sku) * factor_sku * 
                          (1 + ruido_normal(0, 0.15))
   - Trend leve por SKU (algunos crecen, otros decaen)
   - Inyectar 2-3 outliers por SKU para realismo
6. Inventario actual:
   - Random uniforme entre 0 y 4 semanas de demanda esperada
7. Eventos comerciales:
   - Black Friday: semana 47
   - Navidad: semana 51
   - Reyes: semana 1 del año siguiente

VALIDACIÓN: que los CSVs respeten foreign keys (todo SKU referenciado 
existe, todo proveedor existe).

----------------------------------------------------------------
MÓDULO data_generator/generate_pdfs.py
----------------------------------------------------------------
PROPÓSITO: generar PDFs ficticios de catálogos para alimentar el RAG.

ALGORITMO:
1. Para cada proveedor, generar un PDF con:
   - Portada con nombre y país
   - Tabla de productos con SKU, nombre, precio, MOQ
   - Términos comerciales (forma de pago, INCOTERMS, garantía)
   - Política de descuentos por volumen
   - Tiempos de producción y despacho
   - Información de contacto
2. Usar reportlab para generar.
3. Variar el formato entre proveedores (no todos lucen igual) para 
   que el RAG tenga que extraer de estructuras distintas.

----------------------------------------------------------------
MÓDULO data_generator/generate_social_posts.py
----------------------------------------------------------------
PROPÓSITO: generar posts simulados de redes para el detector de tendencias.

GENERA: data/posts_simulados.json con 50-100 posts que mezclen:
- Productos del catálogo (no detectables como tendencia)
- 3-5 productos emergentes ficticios mencionados con frecuencia 
  creciente (estos sí deben detectarse como tendencia)
- Ruido (posts no relacionados con navidad)

CADA POST: { plataforma, autor, texto, fecha, likes, shares, hashtags }

----------------------------------------------------------------
MÓDULO clients/data_loader.py
----------------------------------------------------------------
PROPÓSITO: carga única de CSVs en memoria, con cache.

CLASE DataLoader (singleton):
- load_productos() -> dict[sku, Producto]
- load_proveedores() -> dict[proveedor_id, Proveedor]
- load_relaciones() -> list[RelacionComercial]
- load_ventas_historicas() -> pd.DataFrame
- load_inventario() -> dict[sku, int]
- load_eventos() -> list[EventoComercial]

OPTIMIZACIÓN: lazy loading, una vez cargado se mantiene en memoria.

----------------------------------------------------------------
MÓDULO clients/ontologia_client.py (MOCK)
----------------------------------------------------------------
PROPÓSITO: imitar la API que entregará Abi.

CLASE OntologiaClient:
- proveedores_de_sku(sku) -> list[Proveedor]
- categoria_de_sku(sku) -> Categoria
- sustitutos_de_sku(sku) -> list[str]
- proveedores_similares(proveedor_id, k=3) -> list[Proveedor]
- relacion_comercial(sku, proveedor_id) -> RelacionComercial
- inyectar_nodo_provisional(nodo: NodoProvisional) -> bool
  (escribe en data/grafo_provisional.json con MERGE por nodo_id)
- listar_nodos_provisionales() -> list[NodoProvisional]
- vecinos(nodo_id, tipo_relacion=None) -> list[dict]

INTERFAZ EXPLÍCITAMENTE PENSADA PARA SWAP CON NEO4J:
cuando Abi entregue, solo cambiás la implementación interna usando 
neo4j-driver. Los métodos públicos no cambian.

----------------------------------------------------------------
MÓDULO clients/rag_client.py (MOCK)
----------------------------------------------------------------
PROPÓSITO: imitar el RAG que entregará Abi.

VERSIÓN MOCK:
- Lee los PDFs ficticios con pypdf2
- Los segmenta en chunks de 800 chars con overlap 100
- Indexa con TF-IDF (sklearn) — sin embeddings reales
- buscar(query, k=5, filtro_proveedor=None) -> list[Chunk]

VERSIÓN FUTURA (cuando Abi entregue):
- Mismo método público, internamente usa sentence-transformers + FAISS

----------------------------------------------------------------
MÓDULO clients/llm_client.py
----------------------------------------------------------------
PROPÓSITO: wrapper sobre Gemini con retry, fallback, structured output.

CLASE LLMClient:
- generate_text(prompt, temperature=0.3, max_tokens=2000) -> str
- generate_structured(prompt, schema: BaseModel, retries=2) -> BaseModel
- classify(texto, categorias: list[str]) -> str
- function_call(prompt, tools: list[ToolDef]) -> ToolCall

CARACTERÍSTICAS:
- Reintento exponencial con jitter
- Si falla N veces: log warning + devolver fallback estructurado
- Cache LRU de prompts idénticos (TTL 5 min) para evitar costos
- Logs estructurados de cada llamada (latencia, tokens, costo estimado)

----------------------------------------------------------------
MÓDULO clients/web_fetcher.py
----------------------------------------------------------------
PROPÓSITO: fetcher con Playwright que extrae texto visible.

MÉTODOS:
- async fetch_url(url, timeout=15) -> WebContent
  donde WebContent tiene: html_raw, texto_visible, titulo, metadata, 
  screenshots_paths (opcional)
- async fetch_multiple(urls) -> list[WebContent]

CARACTERÍSTICAS:
- Headless Chromium
- User-Agent rotativo
- Retry en timeouts
- Cache en disco con TTL 24h (porque en hackathon no querés re-scrapear)

----------------------------------------------------------------
MÓDULO services/forecast/forecast_service.py
----------------------------------------------------------------
PROPÓSITO: pronóstico de demanda con intervalos de confianza calibrados.

MÉTODO PRINCIPAL:
- forecast(sku, semanas_adelante: int) -> ForecastResult

LÓGICA:
1. Cargar histórico del SKU (data_loader)
2. Si tiene >= 52 semanas:
   2a. Aplicar Holt-Winters (statsmodels.tsa.holtwinters.ExponentialSmoothing)
       con seasonal_periods=52
   2b. Calcular residuos in-sample
   2c. Bootstrap de residuos para construir intervalos calibrados
3. Si tiene < 52 semanas:
   3a. Llamar a cold_start: usar patrón estacional de la categoría
   3b. Escalar por nivel promedio del SKU si hay datos parciales
4. Validar que p5 < p50 < p95 (sanity check)
5. Construir samples = [Normal(media, std) para 1000 muestras]
6. Devolver ForecastResult

EXTENSIONES OPCIONALES:
- Prophet (Facebook) si está disponible
- Detección de outliers con IQR antes de fittear
- Boosting de demanda si hay tendencia detectada en redes para ese SKU 
  (TrendDetector ya inyectó NodoProvisional con velocidad_crecimiento)

----------------------------------------------------------------
MÓDULO services/forecast/cold_start.py
----------------------------------------------------------------
PROPÓSITO: forecast para SKUs sin historia.

LÓGICA:
1. Tomar la categoría del SKU desde OntologiaClient
2. Recuperar el patrón estacional de la categoría (52 floats)
3. Estimar nivel promedio:
   - Si el SKU tiene >0 semanas pero <52: usar lo que tiene
   - Si tiene 0 semanas: usar promedio de SKUs similares de la 
     misma categoría
4. Construir forecast = patron_categoria[semana_objetivo] * nivel_estimado
5. std = std promedio de la categoría * 1.5 (penalty por incertidumbre 
   adicional de cold start)

----------------------------------------------------------------
MÓDULO services/monte_carlo/simulator.py
----------------------------------------------------------------
PROPÓSITO: motor de simulación Monte Carlo.

MÉTODO PRINCIPAL:
- simular(items: list[ItemCompra], 
          forecasts: dict[sku, ForecastResult],
          n_sims: int = 10000,
          correlaciones: dict | None = None,
          seed: int = 42) -> ResultadoMonteCarlo

ALGORITMO:
1. Para cada SKU en items, samplear n_sims demandas:
   - Sin correlaciones: D[s] ~ Normal(forecast.media, forecast.std)
   - Con correlaciones: muestrear desde Normal multivariada usando 
     matriz de correlación entre SKUs (productos sustitutos correlacionan 
     positivo, complementarios también)
2. Para cada simulación s = 1..n_sims:
   2a. Para cada item (sku, cantidad, costo_unit):
       - vendido = min(cantidad, D[sku, s])
       - sobrante = max(0, cantidad - D[sku, s])
       - faltante = max(0, D[sku, s] - cantidad)
       - ingreso = vendido * precio_referencia[sku]
       - costo_compra = cantidad * costo_unit
       - costo_stock_muerto = sobrante * costo_unit * factor_perdida
         (factor_perdida = 0.7 para no perecederos, 1.0 para perecederos)
       - costo_oportunidad = faltante * margen_perdido[sku]
       - ganancia[s, item] = ingreso - costo_compra - costo_stock_muerto 
                              - costo_oportunidad
   2b. ganancia_total[s] = sum(ganancia[s, item] for item in items)
3. Calcular métricas:
   - retorno_esperado = mean(ganancia_total)
   - p5, p25, p50, p75, p95 = percentiles
   - VaR_95 = -p5  (pérdida máxima al 95% de confianza)
   - CVaR_95 = -mean(ganancia_total | ganancia_total <= p5)
   - probabilidad_perdida = mean(ganancia_total < 0)
4. Devolver ResultadoMonteCarlo con samples para histograma

OPTIMIZACIONES:
- Vectorizar con numpy (no loops)
- Si n_sims > 50k: paralelizar con multiprocessing

----------------------------------------------------------------
MÓDULO services/monte_carlo/correlations.py
----------------------------------------------------------------
PROPÓSITO: estimar matriz de correlación entre demandas de SKUs.

LÓGICA:
1. Tomar matriz de ventas históricas (filas=semanas, columnas=SKUs)
2. Calcular matriz de correlación de Pearson
3. Ajustar a positiva semidefinida (nearest PSD si necesario)
4. Devolver matriz

USO: en simular() para muestrear demandas correlacionadas con 
np.random.multivariate_normal.

----------------------------------------------------------------
MÓDULO services/monte_carlo/risk_metrics.py
----------------------------------------------------------------
PROPÓSITO: calcular métricas de riesgo financiero.

FUNCIONES:
- value_at_risk(samples, alpha=0.95) -> float
- conditional_var(samples, alpha=0.95) -> float
- sharpe_ratio(samples, risk_free=0) -> float
- maximum_drawdown(cumulative_samples) -> float
- probability_of_loss(samples) -> float

----------------------------------------------------------------
MÓDULO services/optimizer/milp_solver.py
----------------------------------------------------------------
PROPÓSITO: solver MILP determinista (base sobre la cual se construye 
el estocástico).

FORMULACIÓN MATEMÁTICA:

Conjuntos:
- S = SKUs objetivo
- P = proveedores
- (s,p) ∈ R donde R es la relación válida

Parámetros:
- d_s = demanda esperada del SKU s (E[D_s])
- c_{s,p} = costo unitario del SKU s al proveedor p
- moq_{s,p} = MOQ
- lt_p = lead time del proveedor p
- T = semanas hasta el evento
- B = buffer de seguridad
- vu_s = vida útil (∞ si no perecedero)
- per_s = 1 si perecedero, 0 si no
- M = constante grande (big-M)
- alfa = nivel de cobertura mínimo (0.95)

Variables:
- x_{s,p} ∈ Z+ : cantidad a comprar
- y_{s,p} ∈ {0,1} : indicador de compra
- z_{s,p,t} ∈ {0,1} : indicador de tramo de descuento t aplicado

Función objetivo (minimizar):
  min Σ_{s,p} [ x_{s,p} * c_{s,p} * (1 - desc_efectivo(x_{s,p})) ]
        + λ_stockout * Σ_s max(0, alfa * d_s - Σ_p x_{s,p})
        + λ_capital * Σ_{s,p} c_{s,p} * x_{s,p}

Restricciones:
1. Cobertura: Σ_p x_{s,p} >= alfa * d_s   ∀ s
2. MOQ activado: x_{s,p} >= moq_{s,p} * y_{s,p}   ∀ (s,p) ∈ R
3. MOQ desactivado: x_{s,p} <= M * y_{s,p}   ∀ (s,p) ∈ R
4. Lead time: y_{s,p} = 0 si lt_p > T - B
5. Perecederos: y_{s,p} = 0 si per_s = 1 y vu_s < T + 4
6. Presupuesto (opcional): Σ costo_total <= B_max
7. Descuentos por volumen: linealización con variables binarias z

LINEALIZACIÓN DE DESCUENTOS:
Para cada tramo t con (qty_t, desc_t):
- z_{s,p,t} = 1 si x_{s,p} ∈ [qty_t, qty_{t+1})
- Σ_t z_{s,p,t} <= 1
- precio_efectivo = Σ_t z_{s,p,t} * c_{s,p} * (1 - desc_t)

IMPLEMENTACIÓN: PuLP con CBC solver (open source, viene con PuLP).

----------------------------------------------------------------
MÓDULO services/optimizer/chance_constraints.py
----------------------------------------------------------------
PROPÓSITO: convertir restricciones probabilísticas en MILP usando 
Sample Average Approximation (SAA).

CONCEPTO:
La restricción ideal sería:
  P(Σ_p x_{s,p} >= D_s) >= 1 - β
donde D_s es la variable aleatoria de demanda.

Esto NO es lineal. La aproximación SAA:
1. Samplear N escenarios ω_1, ..., ω_N de D_s desde el forecast
2. Para cada escenario ω_k introducir variable binaria u_{s,k}:
   - u_{s,k} = 1 si Σ_p x_{s,p} >= D_s(ω_k), 0 si no
3. Restricción: Σ_p x_{s,p} + M*(1-u_{s,k}) >= D_s(ω_k)   ∀ s, k
4. Restricción: Σ_k u_{s,k} >= (1-β) * N   ∀ s
   (cubrimos demanda en al menos (1-β)*N escenarios)

PARÁMETROS RECOMENDADOS:
- N = 100 a 500 escenarios (más es mejor pero más lento)
- β = 0.05 (cubrir al menos 95% de los escenarios)

ALTERNATIVA CONSERVADORA (más rápida):
Reemplazar D_s por p_{1-β} del forecast y usar restricción determinista:
  Σ_p x_{s,p} >= forecast.p95   (si β=0.05)
Esto se llama "robust optimization" simple. Es válido como fallback.

----------------------------------------------------------------
MÓDULO services/optimizer/two_stage_stochastic.py
----------------------------------------------------------------
PROPÓSITO: programa estocástico de dos etapas con recurso.

MOTIVACIÓN:
En la realidad, primero compramos (etapa 1) y después vemos demanda 
real (etapa 2). En etapa 2 podemos rematar sobrante, hacer compras 
de emergencia, etc. La optimización debe minimizar costo etapa 1 + 
expected costo etapa 2.

FORMULACIÓN:
Etapa 1 (decisión "here-and-now"):
  x_{s,p} = cantidad comprada antes de ver demanda

Etapa 2 (recurso, una vez observada D_s = ξ_s):
  v_s(ξ_s) = ventas (limitadas por min(x_total_s, ξ_s))
  o_s(ξ_s) = sobrante = max(0, x_total_s - ξ_s)
  f_s(ξ_s) = faltante = max(0, ξ_s - x_total_s)

Costo etapa 2 (función Q(x, ξ)):
  Q(x, ξ) = Σ_s [c_sobrante_s * o_s + c_faltante_s * f_s]

Problema completo:
  min Σ_{s,p} c_{s,p} * x_{s,p} + E_ξ[ Q(x, ξ) ]
  s.t. restricciones de etapa 1

APROXIMACIÓN SAA:
  min Σ_{s,p} c_{s,p} * x_{s,p} + (1/N) Σ_k Q(x, ξ_k)

Donde ξ_k son N escenarios sampleados del Monte Carlo.

Q(x, ξ_k) se computa resolviendo el subproblema de etapa 2 para 
cada escenario, que es un LP simple (continuo).

TÉCNICA AVANZADA: Benders decomposition para escalar a más SKUs/escenarios.
Para hackathon: SAA con 50-100 escenarios y resolverlo monolítico.

----------------------------------------------------------------
MÓDULO services/optimizer/heuristic_fallback.py
----------------------------------------------------------------
PROPÓSITO: si el solver no converge en X segundos, devolver una 
solución factible decente.

ALGORITMO GREEDY:
1. Ordenar SKUs por urgencia (faltante = max(0, demanda - inventario))
2. Para cada SKU:
   - Filtrar proveedores viables (lead time OK)
   - Elegir el más barato que cumpla MOQ
   - Si no hay proveedor que cumpla cobertura, agregar segundo proveedor
3. Validar que se cumplen restricciones globales (presupuesto)
4. Si excede presupuesto: recortar SKUs por margen ascendente
5. Devolver solución con flag "heuristica=True"

----------------------------------------------------------------
MÓDULO services/optimizer/optimizer_service.py
----------------------------------------------------------------
PROPÓSITO: interfaz unificada que orquesta todo lo anterior.

MÉTODO PRINCIPAL:
- optimizar(
    skus_objetivo: list[str],
    forecasts: dict[sku, ForecastResult],
    evento: EventoComercial,
    perfil: PerfilOperador,
    presupuesto: float | None = None,
    proveedores_excluidos: list[str] = [],
    metodo: Literal["determinista", "saa", "two_stage"] = "saa",
    timeout_segundos: int = 30,
  ) -> Recomendacion

FLUJO:
1. Cargar parámetros (relaciones, MOQs, lead times) desde data_loader
2. Ajustar pesos λ_stockout y λ_capital según perfil del operador
3. Llamar al solver elegido
4. Si timeout o infactibilidad: caer a heurística
5. Pasar la solución por Monte Carlo para calcular MetricasRiesgo
6. Construir GrafoCausal (delegar a causal_graph_service)
7. Generar texto de justificación (template + opcionalmente LLM)
8. Empaquetar Recomendacion completa
9. Cachear en data/recomendaciones/{id}.json

----------------------------------------------------------------
MÓDULO services/contrafactual/perturbations.py
----------------------------------------------------------------
PROPÓSITO: definir las perturbaciones soportadas.

CADA PERTURBACIÓN ES UNA CLASE CON:
- aplicar(estado_base) -> estado_modificado
- describir() -> str

PERTURBACIONES IMPLEMENTADAS:
1. QuiebreProveedor(proveedor_id):
   - Excluir proveedor de la lista válida
   - Re-optimizar
2. CambioDemanda(sku_o_categoria, factor):
   - Multiplicar forecast.media y forecast.std por factor
   - Re-optimizar
3. AdelantoEvento(dias):
   - Reducir T (semanas hasta evento)
   - Re-optimizar (algunos proveedores quedan inviables por lead time)
4. CambioPresupuesto(nuevo_presupuesto):
   - Ajustar restricción de presupuesto
5. TipoCambio(moneda, factor):
   - Ajustar precios de proveedores en esa moneda
6. MOQCambia(proveedor_id, sku, nuevo_moq):
   - Ajustar parámetro MOQ
7. NuevoCompetidor(impacto_demanda_pct):
   - Reducir forecasts globales
8. Custom(lambda):
   - Para perturbaciones one-off

----------------------------------------------------------------
MÓDULO services/contrafactual/nl_parser.py
----------------------------------------------------------------
PROPÓSITO: parsear lenguaje natural del operador a Perturbacion.

EJEMPLO INPUT: "qué pasa si el proveedor PROV_ASIA_01 quiebra"
EJEMPLO OUTPUT: Perturbacion(tipo="QUIEBRE_PROVEEDOR", 
                              parametros={"proveedor_id": "PROV_ASIA_01"})

LÓGICA:
1. Pasarle a Gemini con prompt + few-shot examples + schema
2. Validar el output contra Pydantic
3. Si no parsea: pedir confirmación al operador con sugerencias

----------------------------------------------------------------
MÓDULO services/contrafactual/reoptimizer.py
----------------------------------------------------------------
PROPÓSITO: aplicar perturbación y re-correr el solver.

MÉTODO:
- reoptimizar(rec_base: Recomendacion, perturbacion: Perturbacion) 
    -> EscenarioContrafactual

FLUJO:
1. Cargar el contexto de la recomendación base
2. Aplicar perturbacion al contexto (proveedores, forecasts, etc.)
3. Re-llamar a optimizer_service.optimizar() con el contexto modificado
4. Calcular DiffPlan entre rec_base y rec_alterna
5. Generar explicación natural de qué cambió y por qué
6. Devolver EscenarioContrafactual

----------------------------------------------------------------
MÓDULO services/contrafactual/diff_engine.py
----------------------------------------------------------------
PROPÓSITO: calcular diferencias estructuradas entre dos planes.

LÓGICA:
1. Indexar items de cada plan por (sku, proveedor_id)
2. Calcular: agregados, removidos, modificados (cantidad, precio)
3. Calcular deltas agregados: costo total, retorno, VaR
4. Devolver DiffPlan

----------------------------------------------------------------
MÓDULO services/web_research/extractor.py
----------------------------------------------------------------
PROPÓSITO: extraer información estructurada de URLs.

FLUJO:
1. Recibir URL o query (si es query, hacer search primero)
2. Llamar a web_fetcher.fetch_url
3. Construir prompt para Gemini con:
   - Texto extraído (truncado a ~5000 tokens)
   - Schema JSON requerido
   - Instrucciones: "extraé estos campos, si no encontrás algo 
     ponelo en null, no inventes"
4. Validar el JSON contra Pydantic
5. Si falla: reintentar con prompt aclaratorio
6. Devolver NodoProvisional con confianza calculada por:
   - Cuántos campos completos
   - Si la URL es de fuente confiable (whitelist)
   - Si los valores son numéricamente plausibles

----------------------------------------------------------------
MÓDULO services/web_research/cross_validator.py
----------------------------------------------------------------
PROPÓSITO: validar consistencia cruzando múltiples fuentes.

LÓGICA:
1. Recibir N NodoProvisional del mismo producto/proveedor
2. Para cada campo numérico (precio, MOQ, lead_time):
   - Calcular mediana y desviación
   - Marcar outliers (>2σ de la mediana)
3. Para cada campo string (nombre, descripción):
   - Calcular similaridad coseno entre versiones
4. Devolver NodoProvisional consolidado con:
   - Valores = mediana de fuentes coherentes
   - confianza = penalizada por inconsistencias
   - fuentes = lista de URLs

----------------------------------------------------------------
MÓDULO services/web_research/research_service.py
----------------------------------------------------------------
PROPÓSITO: orquesta extractor + cross_validator.

MÉTODO:
- investigar(query: str, n_fuentes_min: int = 3) -> NodoProvisional

FLUJO:
1. Buscar query en buscador (Google search via API o fallback a 
   URLs del registry)
2. Tomar top N URLs del registry de fuentes confiables
3. fetch_multiple en paralelo
4. extractor sobre cada uno
5. cross_validator para consolidar
6. Llamar a OntologiaClient.inyectar_nodo_provisional()
7. Devolver NodoProvisional

----------------------------------------------------------------
MÓDULO services/trends/virality_detector.py
----------------------------------------------------------------
PROPÓSITO: detectar productos virales emergentes.

FLUJO:
1. Recibir corpus de posts (de redes simuladas o reales)
2. Pasarle a Gemini con prompt:
   "Analiza estos posts navideños. Identifica productos mencionados 
    que muestran señales de viralidad creciente. Para cada uno, 
    devolvé: nombre, motivo de viralidad, plataformas donde aparece, 
    velocidad estimada de crecimiento, nivel de confianza."
3. Validar JSON contra Pydantic (lista de TendenciaDetectada)
4. Para cada tendencia:
   - Verificar si ya existe en ontología (si sí, actualizar 
     velocidad_crecimiento)
   - Si no existe, inyectar como NodoProvisional
5. Devolver lista

----------------------------------------------------------------
MÓDULO services/critic/attack_strategies.py
----------------------------------------------------------------
PROPÓSITO: cada estrategia es una clase que ataca una recomendación.

ESTRATEGIAS:
1. RetrasoAduaneroStrategy:
   - Aumentar lead_time de proveedores extranjeros en 30%
   - Re-validar viabilidad temporal
   - Si algún ítem queda fuera de ventana, generar Vulnerabilidad

2. CaidaDemandaStrategy:
   - Usar p5 en vez de p50 como demanda
   - Recalcular stock muerto
   - Si stock muerto > umbral, Vulnerabilidad

3. QuiebreProveedorStrategy:
   - Para cada proveedor de la rec, simular su quiebre con contrafactual
   - Si la rec alterna tiene costo 20% mayor, Vulnerabilidad

4. ObsolescenciaPostEventoStrategy:
   - Para cada item perecedero, calcular fracción no vendida en 
     escenarios de baja demanda
   - Si > 25%, Vulnerabilidad

5. TipoCambioStrategy:
   - Aplicar shock de +20% en monedas extranjeras
   - Recalcular costos
   - Si costo total sube >15%, Vulnerabilidad

6. CompetidorDescuentoStrategy:
   - Asumir competidor lanza promo -30% en categoría top
   - Aplicar reducción de demanda 20% a esa categoría
   - Recalcular ventas perdidas

7. FallaCalidadStrategy:
   - Penalizar proveedores con confiabilidad < 0.7
   - Estimar costo de devoluciones

----------------------------------------------------------------
MÓDULO services/critic/critic_service.py
----------------------------------------------------------------
PROPÓSITO: ejecutar todas las estrategias y consolidar.

MÉTODO:
- atacar(rec: Recomendacion) -> list[Vulnerabilidad]

FLUJO:
1. Ejecutar todas las strategies en paralelo
2. Cada una devuelve 0+ Vulnerabilidades
3. Ordenar por severidad e impacto_usd_p95
4. Para top 3, generar mitigacion_sugerida con LLM
5. Devolver lista

----------------------------------------------------------------
MÓDULO services/negotiator/negotiator_service.py
----------------------------------------------------------------
PROPÓSITO: redactar borradores de email al proveedor.

MÉTODO:
- redactar(
    proveedor: Proveedor,
    items: list[ItemCompra],
    historial: dict,  # volumen acumulado, frecuencia, etc.
    perfil_operador: PerfilOperador,
  ) -> str

FLUJO:
1. Calcular volumen_acumulado_usd con el proveedor (de feedback histórico)
2. Determinar tono según relación:
   - Volumen > $50k y frecuencia >= 3/año: tono cercano, primer nombre
   - Volumen entre $10-50k: tono profesional cordial
   - Primer pedido: tono formal con presentación
3. Construir prompt para Gemini:
   - Sistema: "Sos un asistente de compras profesional. Redactá emails 
     concisos, profesionales, en español neutro. NO uses emojis. NO 
     inventes datos."
   - Usuario: contexto estructurado + tono + items + justificación 
     de descuento (basada en volumen)
4. Generar borrador
5. Validar que contenga: saludo, lista de items, condiciones solicitadas, 
   despedida
6. Devolver string (NO se envía)

----------------------------------------------------------------
MÓDULO services/preference_learning/preference_service.py
----------------------------------------------------------------
PROPÓSITO: actualizar perfil del operador en base a feedback.

MÉTODO:
- registrar_feedback(signal: FeedbackSignal) -> PerfilOperador

LÓGICA DE ACTUALIZACIÓN:
1. Cargar perfil actual
2. Aplicar reglas según FeedbackSignal:
   - APROBAR sin cambios: refuerzo del perfil actual (no cambia, pero 
     incrementa confianza_perfil)
   - MODIFICAR aumentando cantidad: aversion_stockout += 0.05 (clamp 0-1)
   - MODIFICAR disminuyendo cantidad: aversion_capital_inmovilizado += 0.05
   - MODIFICAR cambiando proveedor a uno más rápido: 
     sensibilidad_lead_time += 0.05
   - MODIFICAR cambiando proveedor a uno más barato: 
     sensibilidad_precio += 0.05
   - MODIFICAR cambiando a proveedor de mayor reputación: 
     sensibilidad_calidad += 0.05
   - RECHAZAR: log + reducir confianza_perfil temporalmente
3. Persistir atómicamente (escribir a tmp + rename)
4. Append al feedback_log.jsonl
5. Devolver perfil actualizado

EXTENSIÓN AVANZADA (BAYESIAN UPDATER):
- Cada parámetro del perfil es una Beta(α, β)
- APROBAR: α += 1
- RECHAZAR: β += 1
- MODIFICAR: actualizar parámetros específicos
- Punto estimado del perfil = E[Beta(α,β)] = α/(α+β)
- confianza_perfil = 1 - sqrt(var(Beta(α,β)))

EXTENSIÓN MÁS AVANZADA (INVERSE RL):
- Ver el operador como un agente que optimiza una recompensa desconocida
- Inferir la recompensa que mejor explica las decisiones observadas
- Usarla en futuras optimizaciones como ponderador del objetivo
- Para hackathon: probablemente fuera de scope, pero documentado por si 
  alguien quiere intentarlo

----------------------------------------------------------------
MÓDULO services/causal_graph/graph_builder.py
----------------------------------------------------------------
PROPÓSITO: construir el GrafoCausal a partir de una Recomendacion.

LÓGICA:
1. Nodo central: Evento objetivo
2. Para cada item:
   - Nodo SKU
   - Nodo Proveedor
   - Arista evento → SKU (tipo AFECTA, peso = boost_demanda)
   - Arista SKU → Proveedor (tipo SUMINISTRA, peso = cantidad/total)
   - Nodo Categoría con arista SKU → Categoría
3. Para cada restricción activa:
   - Nodo Restriccion (MOQ, lead_time, presupuesto, etc.)
   - Arista Restriccion → SKU/Proveedor (tipo RESTRINGE)
4. Para cada Vulnerabilidad:
   - Nodo Vulnerabilidad
   - Arista Vulnerabilidad → SKU/Proveedor (tipo INFLUYE_NEGATIVO)
5. Calcular peso_influencia de cada nodo:
   - Si es proveedor: contribución al costo total
   - Si es restricción: shadow price del solver (dual variable)
   - Si es vulnerabilidad: impacto_usd_esperado / costo_total

OUTPUT: GrafoCausal listo para que Franky lo renderice (cytoscape.js).

================================================================
SECCIÓN 7 — AGENTES Y ORQUESTACIÓN
================================================================

----------------------------------------------------------------
ARQUITECTURA DE AGENTES (LANGGRAPH)
----------------------------------------------------------------

ESTADO COMPARTIDO (SharedAgentState):
- mensaje_usuario: str
- intent: IntentClassification | None
- contexto_sesion: dict
- perfil_operador: PerfilOperador
- recomendacion_actual: Recomendacion | None
- escenario_contrafactual: EscenarioContrafactual | None
- traces: list[AgentTrace]
- respuesta_final: str | None

GRAFO DE FLUJO:
[USER_MESSAGE]
    ↓
[INTENT_CLASSIFIER] → clasifica intent
    ↓
[ROUTER] → según intent, va a:
    ├─ SUPPLIER_AGENT (consulta producto/proveedor)
    ├─ FORECAST_AGENT (consulta demanda)
    ├─ OPTIMIZER_AGENT (genera recomendación)
    │       ↓
    │   [CRITIC_AGENT] (red-teaming)
    │       ↓
    │   [GRAPH_BUILDER]
    │       ↓
    │   [RESPONSE_FORMATTER]
    ├─ CONTRAFACTUAL_AGENT (re-optimiza bajo perturbación)
    ├─ NEGOTIATOR_AGENT (redacta borrador)
    ├─ RESEARCHER_AGENT (web research)
    ├─ TRENDS_AGENT (detecta tendencias)
    └─ FALLBACK (respuesta directa)
    ↓
[FEEDBACK_CAPTURE] → si el usuario aprobó/rechazó, registrar señal
    ↓
[RESPONSE]

----------------------------------------------------------------
TOOLS REGISTRADAS PARA EL ORQUESTADOR
----------------------------------------------------------------
Cada tool tiene docstring que el LLM lee para decidir cuándo invocarla.

@tool
def consultar_producto(sku: str) -> dict:
    """Recupera información de un producto del catálogo. 
    Usar cuando el usuario pregunta por un SKU específico, sus 
    proveedores, su categoría o sus sustitutos."""

@tool
def buscar_en_documentos(query: str, k: int = 5) -> list[dict]:
    """Busca información semántica en catálogos PDF de proveedores 
    y contratos. Usar cuando se necesita información que no está 
    estructurada en la base de datos."""

@tool
def investigar_web(query: str) -> dict:
    """Investiga en la web información sobre un producto o proveedor 
    que NO existe en la base interna. Usar solo cuando consultar_producto 
    devuelve vacío."""

@tool
def detectar_tendencias() -> list[dict]:
    """Analiza señales recientes de redes sociales y tendencias para 
    detectar productos navideños emergentes. Usar cuando el usuario 
    pregunta por novedades, tendencias o productos virales."""

@tool
def generar_recomendacion(
    evento_id: str,
    semanas_hasta_evento: int,
    presupuesto: float | None = None,
    skus_objetivo: list[str] | None = None,
) -> Recomendacion:
    """Genera una recomendación de compra completa para un evento. 
    Incluye optimización estocástica, simulación Monte Carlo, 
    crítica adversarial y grafo causal. Usar cuando el usuario pide 
    'qué comprar' o similar."""

@tool
def simular_contrafactual(
    recomendacion_id: str, 
    perturbacion_descripcion_natural: str
) -> EscenarioContrafactual:
    """Re-calcula la recomendación bajo un escenario hipotético 
    descripto en lenguaje natural ('qué pasa si...'). Usar cuando 
    el usuario plantea hipótesis."""

@tool
def redactar_negociacion(
    recomendacion_id: str, 
    proveedor_id: str
) -> str:
    """Redacta un borrador de email para enviar al proveedor con la 
    orden de compra. NO envía el email, solo lo deja listo para 
    revisión humana."""

@tool
def explicar_decision(recomendacion_id: str, aspecto: str) -> str:
    """Explica en lenguaje natural por qué la recomendación toma una 
    decisión específica (elección de proveedor, cantidad, exclusión). 
    Usar cuando el usuario pide 'por qué'."""

================================================================
SECCIÓN 8 — ENDPOINTS HTTP COMPLETOS
================================================================

[Para cada endpoint: path, método, request, response, errores, ejemplo]

GET    /api/v1/health
GET    /api/v1/productos?categoria=&page=&size=
GET    /api/v1/productos/{sku}
GET    /api/v1/productos/{sku}/forecast?semanas=
GET    /api/v1/proveedores
GET    /api/v1/proveedores/{proveedor_id}
GET    /api/v1/inventario
GET    /api/v1/inventario/alertas
GET    /api/v1/eventos
POST   /api/v1/recomendaciones/generar
GET    /api/v1/recomendaciones/{id}
GET    /api/v1/recomendaciones?estado=&desde=&hasta=
POST   /api/v1/simulacion/montecarlo
POST   /api/v1/contrafactual
POST   /api/v1/contrafactual/natural-language
POST   /api/v1/chat
GET    /api/v1/chat/sesiones/{sesion_id}
POST   /api/v1/agentes/web-research
POST   /api/v1/agentes/tendencias
POST   /api/v1/agentes/critico/atacar
POST   /api/v1/negociacion/borrador
POST   /api/v1/feedback
GET    /api/v1/grafo/causal/{recomendacion_id}
GET    /api/v1/perfil/{operador_id}
GET    /api/v1/grafo/provisional        # nodos provisionales del grafo

================================================================
SECCIÓN 9 — OBSERVABILIDAD
================================================================

LOGGING (loguru):
- Cada request: request_id, path, duration, status
- Cada llamada a LLM: prompt_hash, tokens_in, tokens_out, duration, costo
- Cada llamada al solver: variables, restricciones, gap, status, duration
- Cada inyección al grafo: nodo_id, origen, confianza

MÉTRICAS IN-MEMORY (Prometheus-style, sin Prom):
- contador_requests_por_endpoint
- histograma_latencia_optimizer
- contador_llamadas_llm
- contador_fallbacks_heuristica
- contador_cache_hits

TRACES:
- Cada Recomendacion lleva una lista AgentTrace que se persiste
- /api/v1/traces/{recomendacion_id} devuelve el trace para debugging

================================================================
SECCIÓN 10 — PLAN DE IMPLEMENTACIÓN POR HORAS
================================================================

[Detalla qué módulos se hacen en qué hora, dependencias, checkpoints]

H0-H1: schemas + estructura + config
H1-H3: data_generator (CSVs + PDFs + posts)
H3-H4: data_loader + ontologia_client mock + rag_client mock
H4-H5: forecast_service básico (Holt-Winters + cold start)
H5-H7: monte_carlo simulator + risk_metrics
H7-H10: optimizer (MILP determinista + SAA)
H10-H11: heuristic_fallback + optimizer_service
H11-H13: FastAPI con todos los endpoints (mockeados primero, conectar después)
H13-H15: web_research + trend_detector
H15-H17: orchestrator + intent_classifier + tools básicas
H17-H19: critic + negotiator
H19-H21: contrafactual (perturbations + reoptimizer + nl_parser)
H21-H22: preference_learning + causal_graph
H22-H23: smoke_test end-to-end + bug fixes
H23-H24: README, ejemplos curl, dormir

================================================================
SECCIÓN 11 — REGLAS DE CÓDIGO INVIOLABLES
================================================================

- Python 3.11+
- Type hints OBLIGATORIOS en funciones públicas
- Pydantic v2 para todos los datos
- async/await para IO (LLM, scraping, DB futura)
- Docstrings en formato Google en funciones públicas
- loguru en vez de print
- HTTPException con detail estructurado
- Sin globals mutables salvo singletons explícitos (DataLoader)
- Idempotencia en escrituras
- Cache donde tenga sentido (LLM calls, scraping)
- No tocar archivos de schemas una vez definidos sin avisar al equipo

================================================================
SECCIÓN 12 — RIESGOS Y PLANES B
================================================================

| Componente | Riesgo | Mitigación | Plan B |
|---|---|---|---|
| Solver MILP | Tiempo excesivo | Limit time, gap | Heurística greedy |
| Gemini | Rate limit | Cache + retry | Templates hardcodeados |
| Playwright | Falla instalación | Retry install | URLs cacheadas |
| Monte Carlo | Lento con n=10k | Vectorizar numpy | n=2000 |
| LangGraph | Curva aprendizaje | Empezar simple | Routing if/elif manual |
| Contrafactual NL parsing | Ambiguo | Few-shot prompt | Lista de presets |
| Abi no entrega | Bloqueo | Mock idéntico | Demo con mock |
| Franky no integra | Demo roto | Mock APEX o usar Postman | Demo con curl |

================================================================
SECCIÓN 13 — CRITERIOS DE "LISTO PARA DEMO"
================================================================

GOLDEN PATH (5 minutos de pitch):
1. Mostrar dashboard con 50 productos, 6 proveedores, alertas activas
2. Apretar "Generar recomendación para Black Friday"
3. Recomendación aparece en <8s con grafo causal + vulnerabilidades 
   + histograma Monte Carlo
4. Operador escribe en chat: "qué pasa si PROV_ASIA_01 quiebra"
5. Plan alterno aparece en <8s con diff visual
6. Operador aprueba el plan original
7. Aparece borrador de email al proveedor
8. Operador modifica cantidad de un SKU
9. Sistema registra feedback, perfil se actualiza
10. Mostrar tendencia detectada en redes (NodoProvisional reciente)

SI ESOS 10 PASOS FUNCIONAN: GANASTE.

================================================================
SECCIÓN 14 — CÓMO USAR ESTE DOCUMENTO
================================================================

1. PARA VOS: leelo entero al menos una vez para tener el modelo mental.
2. PARA GENERAR CÓDIGO CON IA: copiá la sección del módulo + las 
   secciones 1, 2, 3, 5 (dependencias) y pedí: "Implementá este 
   módulo completo en Python. Devolvé el archivo runnable."
3. PARA COORDINAR EQUIPO:
   - Mandale a Franky las secciones 5 (schemas) y 8 (endpoints)
   - Mandale a Abi las secciones de clients/ y schemas/tendencias.py
   - Mandale a Iván el documento entero, dividan secciones
4. ORDEN DE IMPLEMENTACIÓN: estricto por dependencias (sección 10).

FIN DEL DOCUMENTO