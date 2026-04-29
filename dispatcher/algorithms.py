"""Catalogo de descriptores formales de algoritmos.

Cada algoritmo del paper de robust optimization (29 conceptos) se mapea
a un descriptor que NO ejecuta nada: solo describe formalmente que es,
que parametros toma, en que `kind` (eje compositivo) participa y a que
seccion del paper corresponde. La implementacion real de cada algoritmo
es responsabilidad del equipo de Tarea 4.

Decision de diseno: NO incluimos los 29 conceptos a la fuerza. Solo los
descriptores que el dispatcher necesita para producir recomendaciones
formales bajo los escenarios actuales (cold-start, SKU establecido,
trend signal). El resto del catalogo queda como vocabulario disponible
para reglas futuras del rules.yaml. Filosofia: "no fuerces un concepto
a aplicar cuando no lo hace" (citado del prompt).

Ejes compositivos (Kind):
    POLICY_FORM       - como se parametriza la cantidad a pedir.
    WEIGHTING         - como se ponderan los errores de forecast pasados.
    UNCERTAINTY_SET   - regimen del conjunto de incertidumbre robusto.
    DEVIATION_METRIC  - estructura de la metrica de error.
    CONSTRAINT_FAMILY - familia de restricciones del problema.
    FRAMING           - lectura estatica vs dinamica del problema.
    COLD_START        - estrategia para SKUs sin historia.

Una recomendacion del dispatcher es una combinacion de stages, idealmente
uno por kind (la regla YAML decide cuales kinds incluir).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# =============================================================================
# Ejes compositivos
# =============================================================================


class Kind(str, Enum):
    """Eje compositivo del descriptor en una recomendacion."""

    POLICY_FORM = "policy_form"
    WEIGHTING = "weighting"
    UNCERTAINTY_SET = "uncertainty_set"
    DEVIATION_METRIC = "deviation_metric"
    CONSTRAINT_FAMILY = "constraint_family"
    FRAMING = "framing"
    COLD_START = "cold_start"


# =============================================================================
# ParameterSpec + AlgorithmDescriptor
# =============================================================================


@dataclass(frozen=True)
class ParameterSpec:
    """Especificacion de un parametro de un algoritmo.

    Args:
        nombre: identificador del parametro.
        tipo: nombre del tipo Python (`"float"`, `"int"`, `"str"`, `"bool"`).
              Tarea 4 lo usara para deserializar / castear.
        default: valor por defecto si la regla no lo provee.
        descripcion: una linea que explica el parametro.
        rango: (min, max) para tipos numericos. None = sin restriccion.
    """

    nombre: str
    tipo: str
    default: Any
    descripcion: str = ""
    rango: Optional[tuple[float, float]] = None


@dataclass(frozen=True)
class AlgorithmDescriptor:
    """Descriptor formal inmutable de un algoritmo del paper.

    Args:
        descriptor_id: identificador unico (ej: "affine_ordering_policy").
        kind: eje compositivo en el que participa.
        nombre: legible para razonamiento.
        descripcion: 1-2 lineas explicando que hace.
        parametros: mapping nombre -> ParameterSpec.
        referencia: ubicacion en el paper o el proyecto (string libre).
        concepto_paper: numero del concepto en la lista de 29 (None si es
            descriptor del proyecto, ej: ColdStartSimilarity).
        compatible_con: tupla de descriptor_ids con los que compone bien.
            Vacia = compone con cualquier descriptor de otro kind.
            Util para validacion en construccion del Recommendation.
        defaults_dependen_de: campos del DecisionContext de los que se
            sugieren defaults dinamicos (ej: para ColdStartSimilarity
            "similar_top_sku"). Hint para Tarea 4.
    """

    descriptor_id: str
    kind: Kind
    nombre: str
    descripcion: str
    parametros: tuple[ParameterSpec, ...] = ()
    referencia: str = ""
    concepto_paper: Optional[int] = None
    compatible_con: tuple[str, ...] = ()
    defaults_dependen_de: tuple[str, ...] = ()

    def parametros_dict(self) -> dict[str, ParameterSpec]:
        return {p.nombre: p for p in self.parametros}


# =============================================================================
# Catalogo - subset relevante de los 29 conceptos
# =============================================================================
# Numeracion de `concepto_paper` en comentarios sigue la lista del prompt.

_CATALOGO: list[AlgorithmDescriptor] = [
    # --- POLICY_FORM -----------------------------------------------------
    AlgorithmDescriptor(
        descriptor_id="affine_ordering_policy",
        kind=Kind.POLICY_FORM,
        nombre="Politica afin de pedido",
        descripcion=(
            "Pedido como funcion afin de errores de forecast pasados: "
            "x_t = x_t^0 + y0*(d_{t-1} - d_hat_{t-1}) + y1*sum(errors). "
            "Internaliza riesgo via decision rule parametrico."
        ),
        parametros=(
            ParameterSpec(
                nombre="y0_initial",
                tipo="float",
                default=0.0,
                descripcion="Coeficiente para el error mas reciente.",
            ),
            ParameterSpec(
                nombre="y1_initial",
                tipo="float",
                default=0.0,
                descripcion="Coeficiente para la suma acumulada de errores.",
            ),
        ),
        referencia="Paper sec 3-4, ecs (3)-(5)",
        concepto_paper=1,
    ),
    AlgorithmDescriptor(
        descriptor_id="open_loop",
        kind=Kind.POLICY_FORM,
        nombre="Politica open-loop (no-afin)",
        descripcion=(
            "Pedido base x_t = x_t^0 + y0*sum(d_hat). No reacciona a "
            "errores de forecast pasados. Sirve como baseline contra el "
            "que se compara la afin."
        ),
        parametros=(
            ParameterSpec(
                nombre="y0",
                tipo="float",
                default=1.0,
                descripcion="Multiplicador del forecast acumulado.",
            ),
        ),
        referencia="Paper sec 2.2",
        concepto_paper=2,
    ),
    AlgorithmDescriptor(
        descriptor_id="corrective_reformulation",
        kind=Kind.POLICY_FORM,
        nombre="Reformulacion corrective (PI controller)",
        descripcion=(
            "Politica reescrita en terminos de errores e_t = d_t - d_hat_t "
            "en lugar de niveles. Convierte la politica de scaling a "
            "bias-correction (analogo a un controlador PI). Interpretable "
            "causalmente."
        ),
        parametros=(
            ParameterSpec(
                nombre="kp",
                tipo="float",
                default=1.0,
                descripcion="Ganancia proporcional sobre error reciente.",
            ),
            ParameterSpec(
                nombre="ki",
                tipo="float",
                default=0.1,
                descripcion="Ganancia integral sobre suma de errores.",
            ),
        ),
        referencia="Paper sec 5",
        concepto_paper=5,
    ),
    # --- WEIGHTING -------------------------------------------------------
    AlgorithmDescriptor(
        descriptor_id="ewma_smoothing",
        kind=Kind.WEIGHTING,
        nombre="Ponderacion exponencial (EWMA)",
        descripcion=(
            "Pesa errores pasados con w_{t,u} = K * exp(-alpha*(t-u-1)). "
            "Errores recientes pesan mas. Genera forma cerrada para los "
            "coeficientes A_{u,i,w} de las restricciones robustas."
        ),
        parametros=(
            ParameterSpec(
                nombre="alpha",
                tipo="float",
                default=0.15,
                descripcion="Decay exponencial.",
                rango=(0.0, 1.0),
            ),
            ParameterSpec(
                nombre="K",
                tipo="float",
                default=1.0,
                descripcion="Constante de normalizacion.",
                rango=(0.0, 100.0),
            ),
        ),
        referencia="Paper secs 2.3, 5.1, ec (6)",
        concepto_paper=4,
    ),
    AlgorithmDescriptor(
        descriptor_id="uniform_recency_weighting",
        kind=Kind.WEIGHTING,
        nombre="Ponderacion uniforme",
        descripcion=(
            "Todos los errores pesan igual hasta tiempo t. Baseline trivial "
            "contra el que se compara EWMA. Sobreaprende ruido viejo."
        ),
        parametros=(),
        referencia="Paper sec 2.3 (lectura inversa del concepto 26)",
        concepto_paper=26,
    ),
    AlgorithmDescriptor(
        descriptor_id="lead_time_window_weighting",
        kind=Kind.WEIGHTING,
        nombre="Ponderacion por ventana de lead time",
        descripcion=(
            "Pesa mas los errores dentro de la ventana del lead time del "
            "proveedor. Util para evitar stockouts cuando llega el proximo "
            "pedido."
        ),
        parametros=(
            ParameterSpec(
                nombre="ventana_dias",
                tipo="int",
                default=14,
                descripcion="Tamano de la ventana centrada en lead time.",
                rango=(1, 365),
            ),
        ),
        referencia="Paper concepto 28",
        concepto_paper=28,
    ),
    # --- UNCERTAINTY_SET -------------------------------------------------
    AlgorithmDescriptor(
        descriptor_id="unbounded_deviations",
        kind=Kind.UNCERTAINTY_SET,
        nombre="Conjunto de incertidumbre no acotado (Case 1)",
        descripcion=(
            "D_hat = R^{txIxW}. La restriccion robusta solo es finita si "
            "|A_{u,i,w}| <= k^2 / sigma_u. Recupera la politica no-afin "
            "como caso limite. Worst-case shock impact = 0."
        ),
        parametros=(),
        referencia="Paper sec 4, Case 1, ec (31)",
        concepto_paper=7,
    ),
    AlgorithmDescriptor(
        descriptor_id="bounded_deviations",
        kind=Kind.UNCERTAINTY_SET,
        nombre="Conjunto de incertidumbre acotado (Case 2)",
        descripcion=(
            "|d_hat_{u,i,w}| <= epsilon_{u,i,w}. Caso donde la politica afin "
            "agrega valor concreto. Genera la restriccion robusta agregada: "
            "sum(epsilon * (|A| - k^2/sigma)+) <= C_t."
        ),
        parametros=(
            ParameterSpec(
                nombre="epsilon_factor",
                tipo="float",
                default=1.5,
                descripcion="Multiplicador de sigma para fijar epsilon.",
                rango=(0.1, 10.0),
            ),
        ),
        referencia="Paper sec 4, Case 2, ecs (33)-(34)",
        concepto_paper=8,
    ),
    # --- DEVIATION_METRIC ------------------------------------------------
    AlgorithmDescriptor(
        descriptor_id="simple_absolute_deviation",
        kind=Kind.DEVIATION_METRIC,
        nombre="Metrica de desviacion absoluta simple",
        descripcion=(
            "Delta(d) = sum |d - d_hat| / sigma. No captura correlaciones "
            "cruzadas entre productos/semanas. Simple y rapida."
        ),
        parametros=(),
        referencia="Paper concepto 18",
        concepto_paper=18,
    ),
    AlgorithmDescriptor(
        descriptor_id="correlated_deviations",
        kind=Kind.DEVIATION_METRIC,
        nombre="Metrica con correlacion cruzada (Mahalanobis)",
        descripcion=(
            "Delta(d) = ||d - d_hat||^2_{Sigma^-1} usando matriz de "
            "covarianza. Captura heteroscedasticidad y autocorrelacion "
            "(concepto 20)."
        ),
        parametros=(
            ParameterSpec(
                nombre="cov_matrix_path",
                tipo="str",
                default="",
                descripcion="Ruta a un .npy con matriz Sigma. Vacio => usar identidad.",
            ),
        ),
        referencia="Paper conceptos 19-20",
        concepto_paper=19,
    ),
    # --- CONSTRAINT_FAMILY -----------------------------------------------
    AlgorithmDescriptor(
        descriptor_id="robust_constraint_aggregated",
        kind=Kind.CONSTRAINT_FAMILY,
        nombre="Restriccion robusta agregada",
        descripcion=(
            "sum_uIw epsilon_{u,i,w} * (|A_{u,i,w}| - k^2/sigma_{u,i,w})+ "
            "<= C_t. Reformulacion robust-satisficing del paper para "
            "el caso acotado."
        ),
        parametros=(),
        referencia="Paper ec (33)",
        concepto_paper=9,
    ),
    AlgorithmDescriptor(
        descriptor_id="turnover_constraint",
        kind=Kind.CONSTRAINT_FAMILY,
        nombre="Restriccion de rotacion minima",
        descripcion=(
            "sum p*d_hat*r >= psi*c_t * sum(x_tilde - r*d_hat). Minimo "
            "de rotacion sobre demanda forecast."
        ),
        parametros=(
            ParameterSpec(
                nombre="psi_min",
                tipo="float",
                default=0.6,
                descripcion="Fraccion minima de rotacion.",
                rango=(0.0, 1.0),
            ),
        ),
        referencia="Paper sec 3, ec (9)",
        concepto_paper=13,
    ),
    AlgorithmDescriptor(
        descriptor_id="revenue_constraint",
        kind=Kind.CONSTRAINT_FAMILY,
        nombre="Restriccion de ingresos minimos",
        descripcion=(
            "sum p*d_hat*r >= R_phi. Cota inferior de revenue esperado."
        ),
        parametros=(
            ParameterSpec(
                nombre="revenue_floor_usd",
                tipo="float",
                default=0.0,
                descripcion="Piso de ingresos en USD.",
            ),
        ),
        referencia="Paper sec 3, ec (10)",
        concepto_paper=14,
    ),
    AlgorithmDescriptor(
        descriptor_id="cash_constraint",
        kind=Kind.CONSTRAINT_FAMILY,
        nombre="Restriccion de caja end-of-period",
        descripcion=(
            "Z_t + sum(p*beta*d*r - (h+c)*x_tilde) >= -k^2 * Delta. "
            "Liquidez al cierre con working capital, holding y stockout "
            "penalty. Critica para retail navideno (caja en noviembre)."
        ),
        parametros=(
            ParameterSpec(
                nombre="cash_floor_usd",
                tipo="float",
                default=0.0,
                descripcion="Caja minima al cierre.",
            ),
        ),
        referencia="Paper sec 3, ec (11)",
        concepto_paper=15,
    ),
    AlgorithmDescriptor(
        descriptor_id="inventory_constraint",
        kind=Kind.CONSTRAINT_FAMILY,
        nombre="Restriccion de inventario",
        descripcion=(
            "V_{t,w} + sum(x_tilde - r*d) >= k^2 * Delta(d). Inventario "
            "minimo sobre demanda real (no forecast). Fuerza buffer "
            "minimo bajo el peor caso del set acotado."
        ),
        parametros=(),
        referencia="Paper sec 3, ec (12), interpretacion concepto 25",
        concepto_paper=17,
    ),
    # --- FRAMING ---------------------------------------------------------
    AlgorithmDescriptor(
        descriptor_id="dynamic_control_framing",
        kind=Kind.FRAMING,
        nombre="Encuadre dinamico (control problem)",
        descripcion=(
            "La politica afin EWMA convierte el problema robusto en un "
            "control dinamico donde la factibilidad depende de la "
            "capacidad del sistema de absorber y corregir errores en "
            "el tiempo."
        ),
        parametros=(),
        referencia="Paper concepto 29",
        concepto_paper=29,
    ),
    AlgorithmDescriptor(
        descriptor_id="static_robust_framing",
        kind=Kind.FRAMING,
        nombre="Encuadre estatico robusto",
        descripcion=(
            "Lectura estatica del problema: proteger contra el peor caso "
            "fijo. Default cuando no se usa politica afin."
        ),
        parametros=(),
        referencia="Lectura por contraste del concepto 29",
        concepto_paper=None,
    ),
    # --- COLD_START (no es del paper, viene del Bloque 5) ---------------
    AlgorithmDescriptor(
        descriptor_id="cold_start_similarity",
        kind=Kind.COLD_START,
        nombre="Cold-start desde similar precomputado",
        descripcion=(
            "Para SKUs sin historia, hereda parametros del top-1 similar "
            "del Bloque 5 (motor de similitud multidimensional). Usa "
            "context.similar_top_sku como referencia."
        ),
        parametros=(
            ParameterSpec(
                nombre="heredar_de_sku",
                tipo="str",
                default="",
                descripcion=(
                    "SKU del que heredar parametros. Si vacio, el "
                    "dispatcher rellena con context.similar_top_sku."
                ),
            ),
            ParameterSpec(
                nombre="score_minimo",
                tipo="float",
                default=0.7,
                descripcion=(
                    "Score similitud minimo aceptable. Si el top-1 "
                    "queda debajo, el dispatcher reduce confianza."
                ),
                rango=(0.0, 1.0),
            ),
        ),
        referencia="Bloque 5 - SimilarityEngine (proyecto, no paper)",
        concepto_paper=None,
        defaults_dependen_de=("similar_top_sku",),
    ),
]


# Indice por id (acceso O(1))
CATALOGO: dict[str, AlgorithmDescriptor] = {
    d.descriptor_id: d for d in _CATALOGO
}


# =============================================================================
# Helpers publicos
# =============================================================================


def get(descriptor_id: str) -> AlgorithmDescriptor:
    """Devuelve el descriptor o levanta KeyError."""
    if descriptor_id not in CATALOGO:
        raise KeyError(
            f"Descriptor {descriptor_id!r} no esta en el catalogo. "
            f"Disponibles: {sorted(CATALOGO)}"
        )
    return CATALOGO[descriptor_id]


def list_by_kind(kind: Kind) -> list[AlgorithmDescriptor]:
    """Devuelve los descriptores de un eje compositivo."""
    return [d for d in CATALOGO.values() if d.kind == kind]


def parse_shorthand(expr: str) -> list[str]:
    """Convierte shorthand 'a + b + c' a lista de descriptor_ids.

    Sintaxis minimal: descriptor_ids separados por ' + ' (con espacios).
    NO soporta parentesis ni otros operadores. Para casos complejos,
    usar la forma full (lista de stages explicita en YAML).

    Example:
        parse_shorthand("affine_ordering_policy + ewma_smoothing")
        => ["affine_ordering_policy", "ewma_smoothing"]
    """
    tokens = [t.strip() for t in expr.split("+")]
    if any(not t for t in tokens):
        raise ValueError(
            f"Shorthand invalido: {expr!r}. Tokens vacios entre '+'."
        )
    return tokens


def validate_combination(descriptor_ids: list[str]) -> None:
    """Verifica que una combinacion sea coherente.

    Reglas:
    - Cada descriptor_id existe en el catalogo.
    - No mas de un descriptor por kind (excepto kinds informativos).

    Raises:
        KeyError: descriptor inexistente.
        ValueError: hay dos descriptores del mismo kind.
    """
    descs = [get(d) for d in descriptor_ids]
    kinds_seen: dict[Kind, str] = {}
    for d in descs:
        if d.kind in kinds_seen:
            raise ValueError(
                f"Combinacion invalida: dos descriptores del mismo kind "
                f"{d.kind.value!r}: {kinds_seen[d.kind]!r} y {d.descriptor_id!r}."
            )
        kinds_seen[d.kind] = d.descriptor_id


def dump_to_turtle(path: str | None = None) -> str:
    """Serializa el catalogo a Turtle (cada descriptor como :Algorithm).

    Cada AlgorithmDescriptor se materializa como un individuo de la
    clase :Algorithm de la TBox marketplace.ttl, con propiedades:

        rdfs:label  : nombre
        rdfs:comment: descripcion
        :requiere   : valores literales de parametros (referencia conceptual)
        :referencia : string de paper section / proyecto

    Args:
        path: si se especifica, escribe el TTL al archivo. Sino, devuelve
              solo el string.

    Returns:
        contenido TTL como string.
    """
    lines = [
        "# Auto-generado desde dispatcher.algorithms.dump_to_turtle()",
        "# Catalogo de descriptores de algoritmos como individuos :Algorithm",
        "",
        "@prefix :     <http://marketplace.com.py/onto/v1#> .",
        "@prefix mkt:  <http://marketplace.com.py/onto/v1#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]

    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    for d in CATALOGO.values():
        lines.append(f"mkt:algo_{d.descriptor_id} a :Algorithm ;")
        lines.append(f'    rdfs:label "{_esc(d.nombre)}"@es ;')
        lines.append(f'    rdfs:comment "{_esc(d.descripcion)}"@es ;')
        lines.append(f'    mkt:kind "{d.kind.value}" ;')
        if d.referencia:
            lines.append(f'    mkt:referencia "{_esc(d.referencia)}" ;')
        if d.concepto_paper is not None:
            lines.append(f'    mkt:conceptoPaper "{d.concepto_paper}"^^xsd:int ;')
        # Cierra con punto la ultima property
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")

    content = "\n".join(lines)
    if path is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return content
