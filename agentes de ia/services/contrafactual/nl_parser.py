"""Parser NL -> Perturbacion.

Version inicial robusta por reglas. Se puede reemplazar por LLM sin cambiar
la interfaz publica.
"""

from __future__ import annotations

import re

from schemas.contrafactual import Perturbacion


def parse_perturbacion(texto: str) -> Perturbacion:
    """Parsea descripcion natural a objeto Perturbacion.

    Args:
        texto: Frase del operador con hipotesis.

    Returns:
        Perturbacion validada.
    """
    t = texto.strip()
    low = t.lower()

    m_quiebre = re.search(r"(prov_[a-z]+_\d{2})", low)
    if "quiebra" in low or "quiebre" in low:
        proveedor_id = (m_quiebre.group(1).upper() if m_quiebre else "")
        return Perturbacion(
            tipo="QUIEBRE_PROVEEDOR",
            parametros={"proveedor_id": proveedor_id} if proveedor_id else {},
            descripcion_natural=t,
        )

    m_budget = re.search(r"(presupuesto).*(\d+(?:[\.,]\d+)?)", low)
    if "presupuesto" in low and m_budget:
        val = float(m_budget.group(2).replace(",", "."))
        return Perturbacion(
            tipo="CAMBIO_PRESUPUESTO",
            parametros={"nuevo_presupuesto": val},
            descripcion_natural=t,
        )

    m_factor = re.search(r"(sube|aumenta|incrementa|baja|cae|reduce).*(\d{1,3})\s*%", low)
    if ("demanda" in low or "ventas" in low) and m_factor:
        pct = float(m_factor.group(2)) / 100.0
        verb = m_factor.group(1)
        factor = (1.0 + pct) if verb in {"sube", "aumenta", "incrementa"} else (1.0 - pct)
        factor = max(0.05, factor)
        return Perturbacion(
            tipo="CAMBIO_DEMANDA",
            parametros={"factor": factor},
            descripcion_natural=t,
        )

    if "competidor" in low:
        m = re.search(r"(\d{1,3})\s*%", low)
        pct = float(m.group(1)) / 100.0 if m else 0.15
        return Perturbacion(
            tipo="NUEVO_COMPETIDOR",
            parametros={"impacto_demanda_pct": pct},
            descripcion_natural=t,
        )

    return Perturbacion(tipo="CUSTOM", parametros={"raw": t}, descripcion_natural=t)
