"""Registry seguro de predicados appliesWhen.

Las normas en TTL referencian predicados POR NOMBRE (string). Las
implementaciones Python se registran aca via decorator. NUNCA usamos eval()
sobre el TTL: un TTL malicioso no puede ejecutar codigo arbitrario, solo
nombrar predicados ya definidos.

Uso desde un modulo de predicados de dominio:

    from deontic.predicates import register_predicate

    @register_predicate("F_compra_perecedero_sin_viabilidad")
    def _f_compra_perecedero_sin_viabilidad(decision, contexto):
        if decision.get("tipo") != "compra":
            return False
        if not contexto.get("perecedero"):
            return False
        lt = float(decision.get("lead_time_dias", 0))
        sl = float(contexto.get("shelf_life_dias", 0))
        return lt >= sl
"""

from __future__ import annotations

from typing import Callable, Mapping

# Tipo del predicado: recibe decision y contexto, devuelve bool.
# Mapping[str, object] cubre dict pero es mas tolerante (acepta cualquier
# tipo mapping-like, util si el caller pasa un objeto custom).
Predicate = Callable[[Mapping[str, object], Mapping[str, object]], bool]


_REGISTRY: dict[str, Predicate] = {}


def register_predicate(name: str) -> Callable[[Predicate], Predicate]:
    """Decorator que registra una funcion como predicado appliesWhen.

    Args:
        name: nombre publico del predicado, usado desde el TTL como valor de
            :appliesWhen. Debe ser unico en el proceso.

    Returns:
        Decorator que registra la funcion y la devuelve sin modificarla.

    Raises:
        ValueError: si `name` ya esta registrado en este proceso (proteccion
            contra colisiones por imports duplicados).
    """

    def deco(fn: Predicate) -> Predicate:
        if name in _REGISTRY and _REGISTRY[name] is not fn:
            raise ValueError(
                f"Predicado '{name}' ya estaba registrado por "
                f"{_REGISTRY[name].__module__}.{_REGISTRY[name].__name__}; "
                f"no puedo re-registrar con {fn.__module__}.{fn.__name__}."
            )
        _REGISTRY[name] = fn
        return fn

    return deco


def get_predicate(name: str) -> Predicate:
    """Devuelve el predicado registrado bajo `name` o levanta KeyError."""
    if name not in _REGISTRY:
        raise KeyError(
            f"Predicado '{name}' no registrado. "
            f"Registrados: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def list_predicates() -> list[str]:
    """Lista de nombres de predicados registrados (orden lexicografico)."""
    return sorted(_REGISTRY)


def reset_registry_for_tests() -> None:
    """Limpia el registry. **Solo para tests** que necesiten aislamiento."""
    _REGISTRY.clear()
