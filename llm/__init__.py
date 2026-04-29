"""Capa de enriquecimiento LLM (Bloque 10).

LLM SOLO COMO TRADUCTOR de decisiones formales a lenguaje humano.
NUNCA decide, NUNCA calcula, NUNCA cambia los valores.

Uso:
    from llm import explicar
    expl = explicar("dec_xxx", store=audit_store)
    print(expl.texto)        # 2-3 oraciones legibles
    print(expl.cita_fuentes)  # normas/reglas citadas
    print(expl.fallback)     # True si el LLM fallo y se uso modo deterministico
"""

from __future__ import annotations

from llm.explainer import (
    AlucinacionDetectada,
    ExplicacionHumana,
    PromptBuilder,
    explicar,
)

__all__ = [
    "AlucinacionDetectada",
    "ExplicacionHumana",
    "PromptBuilder",
    "explicar",
]
