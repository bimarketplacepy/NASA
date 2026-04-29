"""Rule + RuleFile + loader desde YAML con validacion pydantic.

Formato esperado del rules.yaml: top-level es una lista de objetos. Cada
objeto es una regla con los campos:

    id          str         identificador unico, traceable.
    nombre      str         legible para razonamiento.
    prioridad   int [0,100] mayor = se evalua antes (ordenamiento desc).
    cuando      list[str]   expresiones tipo Python que deben ser todas
                            verdaderas para que la regla dispare. Vacia
                            => la regla siempre dispara (fallback).
    algoritmo   str | list  shorthand "a + b + c" o lista explicita de
                            descriptor_ids. Cada token debe existir en
                            el catalogo de algorithms.
    parametros  dict        keyed by descriptor_id: cada valor es un dict
                            de params que override los defaults del
                            descriptor. Valores pueden ser literales o
                            templates "{{ context.x.y }}".
    confianza   float [0,1] confianza_base de la regla. El dispatcher
                            puede ajustarla con factores del contexto.

Decision de diseno: pydantic v2 valida estructura/tipos pero no
semantica (referencias a descriptores inexistentes, sintaxis de
expresiones). Esa validacion la hacemos en el loader DESPUES del parse,
con errores agrupados (no fail-on-first) para que el operador vea
todos los problemas de una sola pasada.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from dispatcher.algorithms import (
    CATALOGO,
    parse_shorthand,
    validate_combination,
)
from dispatcher.conditions import (
    ExpresionInsegura,
    ExpresionInvalida,
    SafeExpressionEvaluator,
)


# =============================================================================
# Excepciones
# =============================================================================


class RulesYAMLInvalido(ValueError):
    """El rules.yaml no parsea o contiene errores semanticos.

    El mensaje agrega TODOS los errores encontrados (multilinea), no solo
    el primero. El operador puede arreglar todo en una pasada.
    """


# =============================================================================
# Pydantic schemas (validacion estructural)
# =============================================================================


class RuleSchema(BaseModel):
    """Schema pydantic v2 de una entrada del rules.yaml.

    Solo valida estructura/tipos. La validacion semantica
    (descriptores inexistentes, sintaxis de expresiones) la hace
    `load_rules`.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    nombre: str = Field(default="")
    prioridad: int = Field(ge=0, le=100)
    cuando: list[str] = Field(default_factory=list)
    algoritmo: str | list[str]
    parametros: dict[str, dict[str, Any]] = Field(default_factory=dict)
    confianza: float = Field(default=0.8, ge=0.0, le=1.0)

    @field_validator("cuando")
    @classmethod
    def _strip_cuando(cls, v: list[str]) -> list[str]:
        # Filtra strings vacios (operador puede dejar lineas en blanco)
        return [s.strip() for s in v if s and s.strip()]


# =============================================================================
# Runtime Rule (post-validacion semantica)
# =============================================================================


@dataclass(frozen=True)
class Rule:
    """Regla resuelta lista para ser evaluada por el dispatcher.

    Equivalente runtime de RuleSchema pero con:
    - `algoritmo` shorthand resuelto a tupla `descriptor_ids`.
    - `cuando` pre-validado (cada expresion ya parseo OK).
    - inmutable (frozen).
    """

    rule_id: str
    nombre: str
    prioridad: int
    cuando: tuple[str, ...]
    descriptor_ids: tuple[str, ...]
    parametros: Mapping[str, Mapping[str, Any]]
    confianza: float


# =============================================================================
# Loader
# =============================================================================


def load_rules(
    path: str | Path,
    evaluator: SafeExpressionEvaluator | None = None,
) -> list[Rule]:
    """Carga, valida y resuelve un rules.yaml.

    Args:
        path: ruta al .yaml.
        evaluator: si se provee, se usa para pre-validar la sintaxis de
            cada expresion en `cuando`. Default: nuevo evaluator con
            allowed_names={"context"}.

    Returns:
        lista de Rule inmutables ordenada por prioridad descendente
        (los empates conservan el orden de aparicion en el YAML — sort
        estable).

    Raises:
        FileNotFoundError: el archivo no existe.
        RulesYAMLInvalido: errores estructurales o semanticos. El mensaje
            agrega todos los problemas detectados.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el rules.yaml: {p}")

    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if raw is None:
        raise RulesYAMLInvalido(f"{p} esta vacio.")
    if not isinstance(raw, list):
        raise RulesYAMLInvalido(
            f"{p}: el top-level debe ser una lista de reglas, "
            f"no {type(raw).__name__}."
        )

    if evaluator is None:
        evaluator = SafeExpressionEvaluator({"context"})

    errores: list[str] = []
    rules: list[Rule] = []
    seen_ids: set[str] = set()

    for idx, item in enumerate(raw):
        prefijo = f"[regla #{idx + 1}]"
        if not isinstance(item, dict):
            errores.append(f"{prefijo} no es un objeto YAML.")
            continue

        # 1. Validacion estructural via pydantic
        try:
            schema = RuleSchema.model_validate(item)
        except ValidationError as e:
            errores.append(
                f"{prefijo} {item.get('id', '<sin id>')}: "
                f"errores estructurales:\n{e}"
            )
            continue

        # 2. Id duplicado
        if schema.id in seen_ids:
            errores.append(
                f"[regla {schema.id!r}] id duplicado (ya aparecio antes)."
            )
            continue
        seen_ids.add(schema.id)

        # 3. Resolver algoritmo shorthand -> descriptor_ids
        try:
            if isinstance(schema.algoritmo, str):
                desc_ids = parse_shorthand(schema.algoritmo)
            else:
                desc_ids = list(schema.algoritmo)
        except ValueError as e:
            errores.append(
                f"[regla {schema.id!r}] algoritmo invalido: {e}"
            )
            continue

        # 4. Cada descriptor_id existe + combinacion coherente
        try:
            validate_combination(desc_ids)
        except (KeyError, ValueError) as e:
            errores.append(
                f"[regla {schema.id!r}] algoritmo {schema.algoritmo!r}: {e}"
            )
            continue

        # 5. Cada key de parametros debe ser un descriptor_id de la regla
        desc_ids_set = set(desc_ids)
        for key in schema.parametros:
            if key not in desc_ids_set:
                errores.append(
                    f"[regla {schema.id!r}] parametros[{key!r}] no "
                    f"corresponde a ningun descriptor de la regla "
                    f"({desc_ids})."
                )
        # Cada parametro debe existir en el descriptor (sino warning,
        # lo dejamos pasar para que Tarea 4 pueda agregar params nuevos)
        for desc_id, params_dict in schema.parametros.items():
            if desc_id not in CATALOGO:
                continue  # ya reportado arriba
            valid_params = set(CATALOGO[desc_id].parametros_dict())
            for pname in params_dict:
                if pname not in valid_params and not _es_template(params_dict[pname]):
                    # Permitimos template strings (se resuelven en runtime)
                    # pero parametros desconocidos sin template => warning.
                    # No es error fatal.
                    pass

        # 6. Pre-validar cada `cuando` (parse + allowlist)
        for cond in schema.cuando:
            try:
                evaluator.validate(cond)
            except (ExpresionInsegura, ExpresionInvalida) as e:
                errores.append(
                    f"[regla {schema.id!r}] cuando {cond!r}: {e}"
                )

        # 7. Pre-validar templates `{{ ... }}` en parametros
        for desc_id, params_dict in schema.parametros.items():
            for pname, pvalue in params_dict.items():
                if _es_template(pvalue):
                    try:
                        evaluator.validate(_extraer_template_expr(pvalue))
                    except (ExpresionInsegura, ExpresionInvalida) as e:
                        errores.append(
                            f"[regla {schema.id!r}] "
                            f"parametros[{desc_id}][{pname}]={pvalue!r}: {e}"
                        )

        rules.append(
            Rule(
                rule_id=schema.id,
                nombre=schema.nombre,
                prioridad=schema.prioridad,
                cuando=tuple(schema.cuando),
                descriptor_ids=tuple(desc_ids),
                parametros={
                    k: dict(v) for k, v in schema.parametros.items()
                },
                confianza=schema.confianza,
            )
        )

    if errores:
        raise RulesYAMLInvalido(
            f"{p}: {len(errores)} error(es):\n  - "
            + "\n  - ".join(errores)
        )

    # Sort estable por prioridad descendente
    rules.sort(key=lambda r: -r.prioridad)
    return rules


# =============================================================================
# Templates {{ context.x.y }}
# =============================================================================


def _es_template(value: Any) -> bool:
    """True si el valor es un template tipo {{...}} (string completo)."""
    return (
        isinstance(value, str)
        and value.strip().startswith("{{")
        and value.strip().endswith("}}")
    )


def _extraer_template_expr(value: str) -> str:
    """Extrae la expresion de un template string {{...}}."""
    s = value.strip()
    return s[2:-2].strip()


def resolve_template(
    value: Any,
    namespace: Mapping[str, Any],
    evaluator: SafeExpressionEvaluator,
) -> Any:
    """Si value es un template, lo evalua. Sino lo devuelve tal cual.

    Returns:
        El valor evaluado (puede ser cualquier tipo Python). Si la
        evaluacion falla (NameError, AttributeError), propaga
        ExpresionInvalida.
    """
    if not _es_template(value):
        return value
    expr = _extraer_template_expr(value)
    return evaluator.evaluate(expr, namespace)


def resolve_params(
    parametros: Mapping[str, Mapping[str, Any]],
    namespace: Mapping[str, Any],
    evaluator: SafeExpressionEvaluator,
) -> dict[str, dict[str, Any]]:
    """Resuelve todos los templates de un mapping de parametros.

    Estructura: {descriptor_id: {param_name: value_o_template}, ...}.
    """
    out: dict[str, dict[str, Any]] = {}
    for desc_id, params in parametros.items():
        out[desc_id] = {
            pname: resolve_template(pval, namespace, evaluator)
            for pname, pval in params.items()
        }
    return out
