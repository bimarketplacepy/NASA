"""explainer: traduce una decision PROV-O del Bloque 8 a prosa humana.

LLM = traductor, NUNCA decisor. Pipeline:

    1. Lee la decision desde el AuditStore (Bloque 8).
    2. Construye un prompt deterministico desde el subgrafo PROV-O via
       PromptBuilder + template `templates/explainer.txt`.
    3. Llama al LLM (Anthropic Claude API si ANTHROPIC_API_KEY esta;
       fallback deterministico sino).
    4. Postprocessor:
       a. Extrae set de numeros del PROMPT (numeros validos).
       b. Extrae set de numeros del OUTPUT del LLM.
       c. Si output \\ prompt != {} -> AlucinacionDetectada -> rechaza.
       d. Si LLM falla (timeout, api error) -> fallback prosa
          plantilla deterministica.
    5. Devuelve `ExplicacionHumana` con texto, fuentes citadas, flag
       fallback, y log de la call para auditoria.

GARANTIAS:
- El LLM nunca toca la base. Solo recibe el prompt.
- Si alucina numeros, la explicacion se rechaza.
- Si falla, hay fallback que es la decision literal sin prosa.
- Cap de tokens output 250 para forzar concision.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from audit.store import AuditStore


# =============================================================================
# Excepciones
# =============================================================================


class AlucinacionDetectada(ValueError):
    """El LLM emitio numeros que no estaban en el prompt - se rechaza la explicacion."""


# =============================================================================
# ExplicacionHumana
# =============================================================================


@dataclass(frozen=True)
class ExplicacionHumana:
    """Resultado de explicar una decision.

    Attributes:
        decision_id: id de la decision explicada.
        texto: prosa final entregada al operador.
        cita_fuentes: lista de normas/reglas que la prosa cita.
        fallback: True si la prosa viene del fallback (LLM fallo o
            alucino).
        razon_fallback: motivo del fallback. Vacio si no hubo.
        prompt_usado: el prompt completo que se envio al LLM (para
            debugging/audit).
        respuesta_cruda: la respuesta literal del LLM (puede tener
            numeros alucinados que despues se rechazaron).
    """

    decision_id: str
    texto: str
    cita_fuentes: tuple[str, ...]
    fallback: bool = False
    razon_fallback: str = ""
    prompt_usado: str = ""
    respuesta_cruda: str = ""


# =============================================================================
# PromptBuilder
# =============================================================================


_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "explainer.txt"


class PromptBuilder:
    """Construye el prompt LLM desde una decision del audit log.

    Llena el template `explainer.txt` con datos del subgrafo PROV-O.
    No genera prosa propia ni infiere - solo serializa los datos.
    """

    def __init__(
        self,
        template_path: Path | str | None = None,
    ) -> None:
        self.template_path = Path(template_path) if template_path else _TEMPLATE_PATH
        self._template_str = self.template_path.read_text(encoding="utf-8")

    def build(self, decision_data: dict[str, Any]) -> str:
        """Renderiza el prompt para una decision dada.

        Args:
            decision_data: dict como el que devuelve `AuditStore.get_decision()`.

        Returns:
            prompt completo listo para enviar al LLM.
        """
        ctx = decision_data.get("context_snapshot") or {}
        # Stages como bloque legible
        stages_input = (
            decision_data.get("stages")
            or ctx.get("stages")
            or []
        )
        # Tambien verificamos las recomendaciones que vienen como dict
        if not stages_input and isinstance(decision_data.get("recomendacion"), dict):
            stages_input = [
                s.get("descriptor_id")
                for s in decision_data["recomendacion"].get("stages", [])
                if isinstance(s, dict) and s.get("descriptor_id")
            ]

        if stages_input:
            stages_lines = "\n".join(f"  - {s}" for s in stages_input)
        else:
            stages_lines = "  (sin algoritmo - decision bloqueada)"

        consulted = decision_data.get("consulted_normas") or []
        blocked = decision_data.get("blocked_by_normas") or []

        substitutions = {
            "decision_id": decision_data.get("decision_id", "<sin id>"),
            "started_at": _fmt(decision_data.get("started_at")),
            "agent": decision_data.get("agent") or "<sin agente>",
            "rule_applied": decision_data.get("rule_applied") or "(ninguna regla)",
            "confidence": _fmt_num(decision_data.get("confidence")),
            "blocked_by_deontic": "si" if decision_data.get("blocked_by_deontic") else "no",
            "sku": str(ctx.get("sku", "<sin sku>")),
            "nombre": str(ctx.get("nombre", "<sin nombre>")),
            "categoria": str(ctx.get("categoria", "<sin categoria>")),
            "tipo_sku": str(ctx.get("tipo_sku", "<sin tipo>")),
            "semanas_historia": str(ctx.get("semanas_historia", 0)),
            "stages_lines": stages_lines,
            "consulted_normas": (
                ", ".join(consulted) if consulted else "(ninguna)"
            ),
            "blocked_by_normas": (
                ", ".join(blocked) if blocked else "(ninguna)"
            ),
        }
        return Template(self._template_str).safe_substitute(**substitutions)


def _fmt(v: Any) -> str:
    if v is None:
        return "<sin fecha>"
    return str(v)


def _fmt_num(v: Any) -> str:
    if v is None:
        return "0.00"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


# =============================================================================
# LLM Client (Anthropic + fallback deterministico)
# =============================================================================


class _LLMCallResult:
    """Wrapper interno con texto y metadata de la llamada al LLM."""

    def __init__(self, texto: str, modelo: str, fallback_motivo: str = "") -> None:
        self.texto = texto
        self.modelo = modelo
        self.fallback_motivo = fallback_motivo


def _llamar_anthropic(
    prompt: str,
    max_tokens: int = 250,
    timeout_s: float = 15.0,
) -> _LLMCallResult:
    """Llama a la API de Anthropic Claude. Si falla, levanta RuntimeError.

    Requiere ANTHROPIC_API_KEY en env.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no esta seteada")
    try:
        import anthropic  # type: ignore[import]
    except ImportError as e:
        raise RuntimeError(
            "Paquete `anthropic` no instalado. pip install anthropic"
        ) from e

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s)
    msg = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
        max_tokens=max_tokens,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )
    # extraer text content
    content = msg.content
    if isinstance(content, list):
        texto = " ".join(
            getattr(b, "text", "") for b in content if hasattr(b, "text")
        ).strip()
    else:
        texto = str(content).strip()
    return _LLMCallResult(texto=texto, modelo=msg.model)


def _fallback_prosa(decision_data: dict[str, Any]) -> str:
    """Genera prosa deterministica desde la decision (sin LLM).

    Usado cuando: (a) no hay ANTHROPIC_API_KEY, (b) la API falla,
    (c) el LLM alucino. Es la "explicacion fallback" del prompt.
    """
    ctx = decision_data.get("context_snapshot") or {}
    sku = ctx.get("sku", "?")
    nombre = ctx.get("nombre", "")
    rule = decision_data.get("rule_applied") or "(sin regla)"
    blocked = decision_data.get("blocked_by_deontic")
    blocked_normas = decision_data.get("blocked_by_normas") or []
    confidence = decision_data.get("confidence")
    stages = decision_data.get("stages") or []

    if blocked:
        return (
            f"Decision para SKU {sku} {nombre} BLOQUEADA por normas "
            f"deonticas: {', '.join(blocked_normas) if blocked_normas else 'sin detalle'}. "
            "No se invoco algoritmo. Revision manual requerida."
        )

    conf_txt = (
        f"con confianza {float(confidence):.2f}"
        if confidence is not None else "sin confianza calculada"
    )
    stages_txt = ", ".join(stages[:3]) if stages else "sin stages"
    return (
        f"Decision para SKU {sku} {nombre}: aplica la regla {rule} "
        f"{conf_txt}. Algoritmo recomendado: {stages_txt}."
    )


# =============================================================================
# Postprocessor: detector de alucinacion de numeros
# =============================================================================


_NUMBER_RE = re.compile(r"-?\d+(?:[\.,]\d+)?")


def extraer_numeros(text: str) -> set[str]:
    """Extrae todos los numeros de un texto, normalizados a string canonico.

    Ignora numeros embebidos en identificadores tipo `dec_a7b3c5...` o
    `regla_001_existing_estable` o IDs como `247329`. Para distinguir,
    consideramos como "numero independiente" solo aquellos que NO esten
    pegados a letras.

    Devuelve un set de strings normalizados (ej: `0.85` -> `"0.85"`,
    `0,85` -> `"0.85"`).
    """
    nums: set[str] = set()
    # Re que captura numeros NO pegados a letras
    pattern = re.compile(r"(?<![A-Za-z_\d])(-?\d+(?:[\.,]\d+)?)(?![A-Za-z_\d])")
    for m in pattern.finditer(text):
        canon = m.group(1).replace(",", ".")
        # Trimear ceros finales para que "0.90" == "0.9"
        if "." in canon:
            canon = canon.rstrip("0").rstrip(".")
        nums.add(canon if canon else "0")
    return nums


def detectar_alucinacion(prompt: str, respuesta: str) -> tuple[bool, set[str]]:
    """Verifica si la respuesta tiene numeros que no estaban en el prompt.

    Args:
        prompt: el prompt que se envio al LLM.
        respuesta: el texto de respuesta del LLM.

    Returns:
        (alucino: bool, numeros_alucinados: set[str]).
        alucino=True sii respuesta tiene >=1 numero que no esta en prompt.
    """
    nums_prompt = extraer_numeros(prompt)
    nums_resp = extraer_numeros(respuesta)
    alucinados = nums_resp - nums_prompt
    return (len(alucinados) > 0, alucinados)


def extraer_citas(respuesta: str, fuentes_validas: list[str]) -> tuple[str, ...]:
    """Devuelve las fuentes (norm_ids, rule_ids) que la respuesta cita.

    Args:
        respuesta: texto del LLM.
        fuentes_validas: lista de strings (norm_ids, rule_ids) que se
            esperan citar.

    Returns:
        tupla con las fuentes que efectivamente aparecen en el texto.
    """
    return tuple(f for f in fuentes_validas if f in respuesta)


# =============================================================================
# explicar() - API publica
# =============================================================================


def explicar(
    decision_id: str,
    store: "AuditStore",
    template_path: Path | str | None = None,
    forzar_fallback: bool = False,
    max_tokens: int = 250,
    log_path: Optional[Path] = None,
) -> ExplicacionHumana:
    """Explica una decision en lenguaje humano.

    Args:
        decision_id: id en el AuditStore.
        store: instancia de AuditStore (Bloque 8).
        template_path: opcional, ruta a template alternativo.
        forzar_fallback: si True, NO llama al LLM y usa fallback
            deterministico directo. Util para tests o ambientes
            offline.
        max_tokens: limite de tokens output del LLM.
        log_path: si se especifica, append-only JSONL con el call
            (request, response, alucinacion, fallback) para debugging.

    Returns:
        ExplicacionHumana con texto + metadata.

    Raises:
        DecisionNotFoundError: si decision_id no existe en el store.
    """
    decision_data = store.get_decision(decision_id)

    builder = PromptBuilder(template_path=template_path)
    prompt = builder.build(decision_data)

    # Identificar fuentes citables
    fuentes_validas: list[str] = []
    if decision_data.get("rule_applied"):
        fuentes_validas.append(decision_data["rule_applied"])
    fuentes_validas.extend(decision_data.get("consulted_normas", []) or [])
    fuentes_validas.extend(decision_data.get("blocked_by_normas", []) or [])

    if forzar_fallback:
        texto = _fallback_prosa(decision_data)
        cita = extraer_citas(texto, fuentes_validas)
        _log_call(log_path, decision_id, prompt, "", texto, "fallback_forzado")
        return ExplicacionHumana(
            decision_id=decision_id,
            texto=texto,
            cita_fuentes=cita,
            fallback=True,
            razon_fallback="forzado por flag",
            prompt_usado=prompt,
            respuesta_cruda="",
        )

    # Llamada real al LLM
    respuesta_cruda = ""
    razon_fallback = ""
    try:
        result = _llamar_anthropic(prompt, max_tokens=max_tokens)
        respuesta_cruda = result.texto
    except Exception as e:
        respuesta_cruda = ""
        razon_fallback = f"LLM error: {type(e).__name__}: {str(e)[:120]}"

    # Postprocessor: detector de alucinacion
    alucino = False
    nums_alucinados: set[str] = set()
    if respuesta_cruda:
        alucino, nums_alucinados = detectar_alucinacion(prompt, respuesta_cruda)
        if alucino:
            razon_fallback = (
                f"alucinacion detectada: numeros {sorted(nums_alucinados)} "
                "no estaban en el prompt"
            )

    # Si fallo o alucino: fallback
    if not respuesta_cruda or alucino:
        texto = _fallback_prosa(decision_data)
        cita = extraer_citas(texto, fuentes_validas)
        _log_call(log_path, decision_id, prompt, respuesta_cruda, texto, razon_fallback)
        return ExplicacionHumana(
            decision_id=decision_id,
            texto=texto,
            cita_fuentes=cita,
            fallback=True,
            razon_fallback=razon_fallback,
            prompt_usado=prompt,
            respuesta_cruda=respuesta_cruda,
        )

    # LLM OK + sin alucinacion
    cita = extraer_citas(respuesta_cruda, fuentes_validas)
    _log_call(log_path, decision_id, prompt, respuesta_cruda, respuesta_cruda, "")
    return ExplicacionHumana(
        decision_id=decision_id,
        texto=respuesta_cruda,
        cita_fuentes=cita,
        fallback=False,
        razon_fallback="",
        prompt_usado=prompt,
        respuesta_cruda=respuesta_cruda,
    )


# =============================================================================
# Logging
# =============================================================================


def _log_call(
    log_path: Optional[Path],
    decision_id: str,
    prompt: str,
    respuesta: str,
    texto_final: str,
    razon_fallback: str,
) -> None:
    """Apend a JSONL de calls al LLM para debugging."""
    if log_path is None:
        return
    import json
    from datetime import datetime, timezone

    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "decision_id": decision_id,
        "prompt_chars": len(prompt),
        "respuesta_chars": len(respuesta),
        "texto_final_chars": len(texto_final),
        "razon_fallback": razon_fallback,
        "fallback": bool(razon_fallback),
        # No logueo prompt/respuesta literales por defecto (privacidad).
        # Habilitar editando aca si se necesita.
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
