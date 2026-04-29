"""Predicados appliesWhen del dominio Marketplace SA Paraguay.

Cada predicado mapea a una norma del catalogo `normas_marketplace.ttl` y
devuelve True cuando la norma es relevante / disparada para el par
(decision, contexto). La semantica del True depende de la modalidad:

    - Prohibition (F): True => la decision esta engaging en el acto prohibido
      => si la norma queda aplicable (no derrotada), la decision queda
      bloqueada.

    - Obligation (O): True => la obligacion aplica al contexto Y la decision
      no la satisface => si queda aplicable, genera obligacion_pendiente.

    - Permission (P): True => las condiciones de la excepcion se cumplen.
      Util para derrotar Prohibitions/Obligations via :defeats. No bloquea
      ni habilita por si misma.

Convencion de keys en `decision` (dict que describe la accion propuesta):
    - tipo: str. Ej "compra", "ajuste_stock", "decision_dispatcher".
    - sku: str | int.
    - cantidad: float.
    - monto_usd: float.
    - aprobacion_supervisor: bool.
    - aprobacion_excepcion: bool.
    - justificacion_escrita: bool.
    - validacion_humana: bool.
    - lead_time_dias: float.
    - descuento_volumen_pct: float.
    - exceso_budget_pct: float.

Convencion de keys en `contexto` (dict que describe el estado del mundo):
    - now: datetime opcional (UTC). Si falta, el resolver usa datetime.now(UTC).
    - perecedero: bool.
    - shelf_life_dias: float.
    - sku_critico: bool.
    - sku_piloto: bool.
    - cold_start: bool.
    - cold_start_confidence: float.
    - proveedores_disponibles: int (cantidad).
    - proveedor_activo: bool.
    - proveedor_exterior: bool.
    - proveedor_es_nuevo: bool.
    - dias_hasta_evento: float.
    - lead_time_proveedor_dias: float.
    - budget_disponible_categoria_usd: float.
    - budget_threshold_low_usd: float.
    - moq_unidades: float.
    - descuento_volumen_minimo_pct: float.

Ningun predicado lanza excepcion sobre keys faltantes: usan defaults seguros
(False / 0 / inf) que vuelven al predicado conservador (no aplicable).
Esto es deliberado: un contexto mal informado no debe bloquear una decision
ni invocar una norma, debe quedar silenciosamente fuera de scope.
"""

from __future__ import annotations

from typing import Mapping

from deontic.predicates import register_predicate


# =============================================================================
# Helpers de extraccion segura
# =============================================================================


def _bool(d: Mapping[str, object], key: str, default: bool = False) -> bool:
    v = d.get(key, default)
    return bool(v)


def _float(d: Mapping[str, object], key: str, default: float = 0.0) -> float:
    v = d.get(key, default)
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _int(d: Mapping[str, object], key: str, default: int = 0) -> int:
    v = d.get(key, default)
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _str(d: Mapping[str, object], key: str, default: str = "") -> str:
    v = d.get(key, default)
    return str(v) if v is not None else default


# =============================================================================
# Predicados - 11 normas (10 base + 1 P de excepcion para defeats)
# =============================================================================


@register_predicate("F_compra_perecedero_sin_viabilidad")
def _f_perecedero(decision: Mapping[str, object], contexto: Mapping[str, object]) -> bool:
    """F1: prohibido comprar perecedero cuya viabilidad temporal sea < lead time.

    Semantica: True (norma disparada) si la decision es comprar un producto
    perecedero y el lead time del proveedor consume todo el shelf life.
    """
    if _str(decision, "tipo") != "compra":
        return False
    if not _bool(contexto, "perecedero"):
        return False
    lead_time = _float(decision, "lead_time_dias")
    shelf_life = _float(contexto, "shelf_life_dias")
    if shelf_life <= 0:
        # Sin info de shelf life para un perecedero declarado: conservador,
        # consideramos que la norma se dispara (vamos a bloquear).
        return True
    return lead_time >= shelf_life


@register_predicate("F_compra_grande_sin_aprobacion_presupuesto_bajo")
def _f_compra_grande(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """F2: prohibido comprar > umbral sin aprobacion si presupuesto < threshold.

    Umbral: monto > 5000 USD. Threshold de presupuesto bajo: definido en
    contexto.budget_threshold_low_usd (default 10000 USD).
    """
    if _str(decision, "tipo") != "compra":
        return False
    monto = _float(decision, "monto_usd")
    if monto <= 5000:
        return False
    if _bool(decision, "aprobacion_supervisor"):
        return False
    presupuesto = _float(contexto, "budget_disponible_categoria_usd")
    threshold_low = _float(contexto, "budget_threshold_low_usd", 10000.0)
    return presupuesto < threshold_low


@register_predicate("F_compra_a_proveedor_desactivado")
def _f_proveedor_desactivado(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """F3: prohibido comprar a proveedor desactivado.

    Norma estricta no defeasible: si el proveedor figura como inactivo,
    la compra no se ejecuta sin importar otras consideraciones.
    """
    if _str(decision, "tipo") != "compra":
        return False
    # Default True para no bloquear cuando el flag no esta seteado
    # (asumimos proveedor activo si no se informa lo contrario).
    proveedor_activo = _bool(contexto, "proveedor_activo", default=True)
    return not proveedor_activo


@register_predicate("O_sku_critico_dos_proveedores")
def _o_dos_proveedores(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """O4: obligatorio garantizar 2+ proveedores para SKUs criticos.

    Semantica obligacional: True (obligacion incumplida) si la decision es
    sobre un SKU critico y el contexto reporta menos de 2 proveedores
    disponibles. Si la decision incluye aprobacion de excepcion, la P5 la
    derrota via :defeats explicito (ver TTL).
    """
    if _str(decision, "tipo") != "compra":
        return False
    if not _bool(contexto, "sku_critico"):
        return False
    return _int(contexto, "proveedores_disponibles") < 2


@register_predicate("P_compra_sku_critico_unico_proveedor_con_aprobacion")
def _p_unico_proveedor(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """P5: permitido comprar SKU critico con 1 proveedor SI hay aprobacion.

    Excepcion documentada a O_sku_critico_dos_proveedores. Solo aplica si:
    - SKU es critico.
    - Hay exactamente 1 proveedor disponible (no es excusa para 0).
    - La decision incluye aprobacion_excepcion.
    """
    if _str(decision, "tipo") != "compra":
        return False
    if not _bool(contexto, "sku_critico"):
        return False
    if _int(contexto, "proveedores_disponibles") != 1:
        return False
    return _bool(decision, "aprobacion_excepcion")


@register_predicate("O_validacion_humana_coldstart_low_conf")
def _o_validacion_humana(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """O5: obligatoria validacion humana si confidence cold-start < 0.5."""
    if not _bool(contexto, "cold_start"):
        return False
    confidence = _float(contexto, "cold_start_confidence", default=1.0)
    if confidence >= 0.5:
        return False
    return not _bool(decision, "validacion_humana")


@register_predicate("P_excede_budget_categoria_15_temporada_pico")
def _p_excede_budget(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """P6: permitido exceder budget categoria 15% en temporada pico.

    La vigencia temporal (validFrom/validUntil de la norma) ya se filtra a
    nivel resolver. Aca solo chequeamos que el exceso este dentro del 15%.
    """
    if _str(decision, "tipo") != "compra":
        return False
    exceso = _float(decision, "exceso_budget_pct")
    return 0 < exceso <= 15.0


@register_predicate("P_compra_supera_moq_con_descuento_volumen")
def _p_moq_descuento(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """P7: permitido superar MOQ si el descuento por volumen lo justifica.

    Threshold de descuento minimo en contexto (default 10%).
    """
    if _str(decision, "tipo") != "compra":
        return False
    cantidad = _float(decision, "cantidad")
    moq = _float(contexto, "moq_unidades", default=0.0)
    if cantidad <= moq:
        return False
    descuento = _float(decision, "descuento_volumen_pct")
    minimo = _float(contexto, "descuento_volumen_minimo_pct", default=10.0)
    return descuento >= minimo


@register_predicate("F_importacion_sin_lead_time_para_evento")
def _f_importacion_sin_lt(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """F8: prohibido importar sin lead time suficiente para el evento."""
    if _str(decision, "tipo") != "compra":
        return False
    if not _bool(contexto, "proveedor_exterior"):
        return False
    dias_evento = _float(contexto, "dias_hasta_evento", default=float("inf"))
    lead_time = _float(contexto, "lead_time_proveedor_dias")
    return dias_evento < lead_time


@register_predicate("O_justificacion_proveedor_exterior_nuevo")
def _o_justificacion_exterior(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """O9: obligatoria justificacion escrita al comprar a exterior nuevo."""
    if _str(decision, "tipo") != "compra":
        return False
    if not _bool(contexto, "proveedor_exterior"):
        return False
    if not _bool(contexto, "proveedor_es_nuevo"):
        return False
    return not _bool(decision, "justificacion_escrita")


@register_predicate("P_relajar_stock_minimo_sku_piloto")
def _p_sku_piloto(
    decision: Mapping[str, object], contexto: Mapping[str, object]
) -> bool:
    """P10: permitido relajar criterio de stock minimo en SKUs piloto.

    Permission informativa: dispara si la decision involucra un SKU piloto.
    No bloquea ni libera por si misma; existe para que el dispatcher pueda
    consultar `eval_.normas_aplicadas` y saber que esta norma esta vigente.
    """
    return _bool(contexto, "sku_piloto")
