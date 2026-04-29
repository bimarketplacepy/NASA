"""Clase base y helpers compartidos para los algoritmos de la biblioteca.

Todo algoritmo concreto hereda de ``BaseAlgorithm`` y sobrescribe ``run()``
y opcionalmente ``precondiciones()``. Los helpers de este modulo estan
disponibles para todos:

- ``elegir_proveedor()``: ranking de proveedores con respeto a restricciones.
- ``calcular_var_cvar()``: VaR y CVaR sobre cantidades p5/p50/p95.
- ``aplicar_buffer_minimo()``: factor de seguridad por restriccion deontica.
- ``respeta_min_proveedores()``: validacion de constraint de doble proveedor.
- ``cap_por_presupuesto()``: ajuste de cantidades si exceden el cash disponible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from optimization.schemas import (
    DecisionContext,
    ProveedorCandidato,
    RecomendacionCompra,
    Restriccion,
)


class BaseAlgorithm(ABC):
    """Clase base abstracta para todos los algoritmos de la biblioteca.

    Atributos de clase requeridos:
        id: identificador corto, snake_case (ej: 'open_loop').
        nombre: nombre legible (ej: 'Open-Loop Baseline').
        paper_seccion: referencia al paper de robust optimization (ej: '2.1, 3.2').
        requiere_semanas_minimas: cantidad minima de semanas de historial.
        soporta_unbounded: si soporta deviation unbounded.
        complejidad: 'baja' | 'media' | 'alta' — informativa.
    """

    id: str = ""
    nombre: str = ""
    paper_seccion: str = ""
    requiere_semanas_minimas: int = 0
    soporta_unbounded: bool = False
    complejidad: str = "baja"

    def precondiciones(self, ctx: DecisionContext) -> bool:
        """Default: requiere semanas_efectivas >= requiere_semanas_minimas.

        Las subclases pueden sobrescribir para reglas mas finas.
        """
        return ctx.forecast.caracteristicas_serie.semanas_efectivas >= self.requiere_semanas_minimas

    @abstractmethod
    def run(
        self,
        ctx: DecisionContext,
        restricciones: list[Restriccion],
        parametros: Optional[dict[str, Any]] = None,
    ) -> RecomendacionCompra:
        """Ejecuta el algoritmo. Lo implementa cada subclase."""
        raise NotImplementedError


# ============================================================
# Helpers compartidos
# ============================================================


def elegir_proveedor(
    proveedores: list[ProveedorCandidato],
    restricciones: list[Restriccion],
    cantidad_objetivo: int,
) -> tuple[ProveedorCandidato, list[ProveedorCandidato]]:
    """Selecciona el mejor proveedor segun restricciones y ranking de score.

    Score = 0.5 * confiabilidad + 0.3 * (1 / (1 + lead_time/30)) + 0.2 * (1 / precio_norm)

    Si hay restriccion ``preferir_proveedor_local``, se aumenta score de
    proveedores nacionales. Si hay ``min_proveedores``, se devuelven al menos
    N alternativos.

    Args:
        proveedores: lista de candidatos.
        restricciones: restricciones deonticas a respetar.
        cantidad_objetivo: cantidad a comprar (para validar capacidad).

    Returns:
        ``(elegido, alternativos)``.

    Raises:
        ValueError: si no hay proveedores candidatos.
    """
    if not proveedores:
        raise ValueError("No hay proveedores candidatos")

    elegibles = [p for p in proveedores if (p.capacidad_max_semanal or 10**9) >= cantidad_objetivo / 8]

    if not elegibles:
        elegibles = list(proveedores)

    preferir_local = any(r.tipo == "preferir_proveedor_local" for r in restricciones)
    precios = [p.precio_unitario for p in elegibles]
    precio_max = max(precios) if precios else 1.0

    def score(p: ProveedorCandidato) -> float:
        s_conf = p.confiabilidad
        s_lead = 1.0 / (1.0 + p.lead_time_dias / 30.0)
        s_precio = 1.0 - (p.precio_unitario / precio_max) if precio_max > 0 else 1.0
        s = 0.5 * s_conf + 0.3 * s_lead + 0.2 * s_precio
        if preferir_local and p.region.lower() == "nacional":
            s += 0.15
        return s

    ranked = sorted(elegibles, key=score, reverse=True)
    elegido = ranked[0]
    alternativos = ranked[1:]

    return elegido, alternativos


def respeta_min_proveedores(
    restricciones: list[Restriccion],
    cantidad_proveedores_disponibles: int,
) -> tuple[bool, int]:
    """Valida la restriccion de minimo de proveedores.

    Returns:
        ``(cumple, minimo_requerido)``.
    """
    minimo = 1
    for r in restricciones:
        if r.tipo == "min_proveedores":
            minimo = max(minimo, int(r.parametros.get("cantidad", 1)))
    return cantidad_proveedores_disponibles >= minimo, minimo


def aplicar_buffer_minimo(
    cantidad_central: int,
    restricciones: list[Restriccion],
) -> tuple[int, float]:
    """Aplica factor_seguridad si hay restriccion de buffer minimo.

    Returns:
        ``(cantidad_ajustada, factor_aplicado)``.
    """
    factor = 1.0
    for r in restricciones:
        if r.tipo == "buffer_minimo":
            factor = max(factor, float(r.parametros.get("factor_seguridad", 1.0)))
    return int(round(cantidad_central * factor)), factor


def cap_por_presupuesto(
    cantidad: int,
    precio_unitario: float,
    presupuesto: float,
) -> tuple[int, bool]:
    """Reduce la cantidad si excede el presupuesto disponible.

    Returns:
        ``(cantidad_final, fue_capada)``.
    """
    if precio_unitario <= 0:
        return cantidad, False
    cantidad_max = int(presupuesto // precio_unitario)
    if cantidad > cantidad_max:
        return cantidad_max, True
    return cantidad, False


def calcular_var_cvar(
    cantidad_p5: int,
    cantidad_central: int,
    cantidad_p95: int,
    precio_unitario: float,
    nivel: float = 0.95,
) -> tuple[float, float]:
    """Calcula VaR y CVaR aproximados sobre el costo del peor caso.

    Aproximacion simple basada en intervalos: VaR como costo p95 - costo central,
    CVaR como promedio del costo en la cola superior (~p95-p99).

    Args:
        cantidad_p5: peor caso conservador (subcompra).
        cantidad_central: cantidad recomendada.
        cantidad_p95: peor caso por exceso (sobrecompra).
        precio_unitario: precio por unidad del proveedor elegido.
        nivel: nivel de confianza (0.95 default).

    Returns:
        ``(var, cvar)`` en unidades monetarias.
    """
    costo_central = cantidad_central * precio_unitario
    costo_p95 = cantidad_p95 * precio_unitario
    costo_p5 = cantidad_p5 * precio_unitario

    var = max(0.0, costo_p95 - costo_central)
    # CVaR: penaliza la cola del peor caso (sobrecompra) considerando tambien el riesgo
    # de subcompra (lucro cesante aproximado a 50% del precio).
    riesgo_sobrecompra = max(0.0, costo_p95 - costo_central)
    riesgo_subcompra = max(0.0, costo_central - costo_p5) * 0.5
    cvar = riesgo_sobrecompra * 1.2 + riesgo_subcompra
    return round(var, 2), round(cvar, 2)


def costo_esperado(cantidad: int, precio_unitario: float) -> float:
    """Costo esperado simple."""
    return round(cantidad * precio_unitario, 2)


def listar_restricciones_aplicadas(restricciones: list[Restriccion]) -> list[str]:
    """Devuelve los IDs de norma de las restricciones que afectaron la decision."""
    return [r.fuente_norma_id for r in restricciones if r.fuente_norma_id]
