"""Tests del explainer LLM (Bloque 10).

Cubre:
    - Fallback deterministico produce explicacion legible para 5 decisiones.
    - Detector de alucinacion: numero NO presente en prompt -> rechazo.
    - Detector ignora numeros embebidos en IDs (`dec_xxx`, `247329`).
    - Citas de fuentes (norm_ids, rule_ids) se extraen correctamente.
    - Explainer funciona sin ANTHROPIC_API_KEY (cae a fallback automatico).
    - Decision bloqueada por deontica produce explicacion adecuada.

NO requiere API real. Todos los tests usan `forzar_fallback=True` o
mockean la respuesta del LLM.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audit import AuditStore  # noqa: E402
from dispatcher import (  # noqa: E402
    AlgorithmDispatcher,
    DecisionContext,
    SimilarRef,
    TipoSku,
    TrendSignal,
)
from llm import (  # noqa: E402
    AlucinacionDetectada,
    ExplicacionHumana,
    PromptBuilder,
    explicar,
)
from llm.explainer import (  # noqa: E402
    detectar_alucinacion,
    extraer_citas,
    extraer_numeros,
)


CATALOGO_RULES = ROOT / "config" / "dispatcher_rules.yaml"


# =============================================================================
# Helpers para construir contextos + decisiones de prueba
# =============================================================================


class _FakeEval:
    def __init__(self, permitida=True, bloqueada_por=()):
        self.permitida = permitida
        self.bloqueada_por = tuple(bloqueada_por)
        self.obligaciones_pendientes = ()


def _ctx_existing(sku="247329"):
    return DecisionContext(
        sku=sku, tipo_sku=TipoSku.EXISTING, nombre="ESFERA DECOR 10x10",
        categoria="DECORACION", semanas_historia=104, volatilidad_forecast=0.18,
    )


def _ctx_new_con_similar(sku="246295"):
    return DecisionContext(
        sku=sku, tipo_sku=TipoSku.NEW, nombre="ESFERA NAVIDENA NUEVA",
        categoria="DECORACION", cold_start_confidence=0.8,
        similar_top_k=(SimilarRef(sku="247329", score_total=0.85),),
    )


def _ctx_trending(sku="555"):
    return DecisionContext(
        sku=sku, tipo_sku=TipoSku.TRENDING, nombre="ARBOL TRENDY",
        categoria="ARBOLES", semanas_historia=60, volatilidad_forecast=0.4,
        trend_signal=TrendSignal(fuente="google_trends", valor=2.1, confianza=0.85),
    )


def _ctx_bloqueada(sku="247329"):
    return DecisionContext(
        sku=sku, tipo_sku=TipoSku.EXISTING, nombre="ESFERA",
        categoria="DECORACION", semanas_historia=100,
        eval_deontica=_FakeEval(False, ("F_compra_perecedero_sin_viabilidad",)),
    )


def _setup_store_con_5_decisiones(tmp_dir: Path) -> tuple[AuditStore, list[str]]:
    """Setup: crea audit store con 5 decisiones reales del dispatcher."""
    store = AuditStore(tmp_dir / "audit.ttl")
    dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES, audit_store=store)
    contextos = [
        _ctx_existing(sku="247329"),
        _ctx_existing(sku="247330"),
        _ctx_new_con_similar(sku="246295"),
        _ctx_trending(sku="555"),
        _ctx_bloqueada(sku="999"),
    ]
    for ctx in contextos:
        dispatcher.decidir(ctx)
    decision_ids = store.list_decisions()
    return store, decision_ids


# =============================================================================
# Tests: extraer_numeros + detectar_alucinacion
# =============================================================================


class TestDetectorAlucinacion(unittest.TestCase):
    def test_extraer_numeros_basicos(self):
        nums = extraer_numeros("Confianza 0.90 sobre 100 productos")
        self.assertIn("0.9", nums)
        self.assertIn("100", nums)

    def test_extraer_numeros_ignora_ids_alfanumericos(self):
        """`dec_a7b3c5...` y `regla_001_existing` NO son numeros que
        cuenten para alucinacion."""
        nums = extraer_numeros("decision dec_a7b3c5 con regla regla_001_existing_estable")
        # No deberia capturar "001" porque esta pegado a "regla_" (letras)
        self.assertNotIn("001", nums)
        self.assertNotIn("1", nums)

    def test_extraer_numeros_sku_aislado_si_se_captura(self):
        """SKU 247329 SI se captura porque puede ser un valor citable."""
        nums = extraer_numeros("Producto 247329 de DECORACION")
        self.assertIn("247329", nums)

    def test_no_alucinacion_si_respuesta_subset(self):
        prompt = "Confianza 0.85 sobre SKU 247329 en categoria DECORACION"
        respuesta = "El SKU 247329 tiene confianza 0.85"
        alucino, nums = detectar_alucinacion(prompt, respuesta)
        self.assertFalse(alucino)
        self.assertEqual(nums, set())

    def test_alucinacion_si_numero_inventado(self):
        prompt = "Confianza 0.85 sobre SKU 247329"
        respuesta = "SKU 247329 con confianza 0.95 (inventada)"
        alucino, nums = detectar_alucinacion(prompt, respuesta)
        self.assertTrue(alucino)
        self.assertIn("0.95", nums)

    def test_alucinacion_de_cantidad_inventada(self):
        prompt = "Confianza 0.85"
        respuesta = "Comprar 5000 unidades con confianza 0.85"
        alucino, nums = detectar_alucinacion(prompt, respuesta)
        self.assertTrue(alucino, f"Esperaba alucinacion por 5000, nums={nums}")
        self.assertIn("5000", nums)


# =============================================================================
# Tests: extraer_citas
# =============================================================================


class TestExtraerCitas(unittest.TestCase):
    def test_cita_norma_si_aparece(self):
        respuesta = "Bloqueada por F_compra_perecedero_sin_viabilidad"
        fuentes = ["F_compra_perecedero_sin_viabilidad", "regla_001"]
        cita = extraer_citas(respuesta, fuentes)
        self.assertIn("F_compra_perecedero_sin_viabilidad", cita)

    def test_no_cita_si_no_aparece(self):
        respuesta = "Decision permitida"
        cita = extraer_citas(respuesta, ["F_X", "regla_Y"])
        self.assertEqual(cita, ())


# =============================================================================
# Tests: PromptBuilder
# =============================================================================


class TestPromptBuilder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store, self.ids = _setup_store_con_5_decisiones(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_prompt_incluye_decision_id_y_sku(self):
        builder = PromptBuilder()
        data = self.store.get_decision(self.ids[0])
        prompt = builder.build(data)
        self.assertIn(self.ids[0], prompt)
        self.assertIn("247329", prompt)

    def test_prompt_incluye_regla_aplicada(self):
        builder = PromptBuilder()
        data = self.store.get_decision(self.ids[0])
        prompt = builder.build(data)
        # ctx_existing(247329) dispara regla_001_existing_estable
        self.assertIn("regla_001_existing_estable", prompt)

    def test_prompt_decision_bloqueada(self):
        builder = PromptBuilder()
        # La 5ta decision es la bloqueada
        data = self.store.get_decision(self.ids[4])
        prompt = builder.build(data)
        self.assertIn("si", prompt.lower())  # blocked_by_deontic: si
        self.assertIn("F_compra_perecedero_sin_viabilidad", prompt)


# =============================================================================
# Tests: explicar() con fallback (sin LLM real)
# =============================================================================


class TestExplicarFallback(unittest.TestCase):
    """Sin ANTHROPIC_API_KEY o con forzar_fallback=True, usa fallback
    deterministico."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store, self.ids = _setup_store_con_5_decisiones(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_5_decisiones_devuelven_explicacion_legible(self):
        """Criterio de aceptacion: 5 decisiones de muestra producen
        explicaciones legibles."""
        for did in self.ids:
            expl = explicar(did, self.store, forzar_fallback=True)
            self.assertIsInstance(expl, ExplicacionHumana)
            self.assertTrue(expl.fallback)
            # Texto legible y conciso
            self.assertGreater(len(expl.texto), 30)
            self.assertLess(len(expl.texto), 400)
            # Para decisiones processed: cita la regla
            data = self.store.get_decision(did)
            if data.get("rule_applied"):
                self.assertIn(data["rule_applied"], expl.cita_fuentes)

    def test_fallback_decision_bloqueada_explica_motivo(self):
        # decision[4] es la bloqueada
        expl = explicar(self.ids[4], self.store, forzar_fallback=True)
        self.assertIn("BLOQUEADA", expl.texto)
        self.assertIn(
            "F_compra_perecedero_sin_viabilidad", expl.cita_fuentes
        )

    def test_fallback_explicacion_processed_menciona_regla(self):
        """La explicacion fallback de una decision processed debe citar
        el rule_id."""
        expl = explicar(self.ids[0], self.store, forzar_fallback=True)
        self.assertIn("regla_001_existing_estable", expl.texto)


# =============================================================================
# Tests: alucinacion forzada + rechazo
# =============================================================================


class TestAlucinacionForzada(unittest.TestCase):
    """Inyecta una respuesta LLM con numero inventado y verifica que el
    detector la rechaza y retorna fallback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store, self.ids = _setup_store_con_5_decisiones(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_llm_alucina_numero_falso_se_rechaza(self):
        """Patch _llamar_anthropic para que devuelva una respuesta con
        un numero que no esta en el prompt (5000 unidades inventadas).
        El detector debe atrapar y devolver fallback."""

        def fake_llm(prompt, max_tokens=250, timeout_s=15.0):
            from llm.explainer import _LLMCallResult
            return _LLMCallResult(
                texto=(
                    "Decision para SKU 247329: comprar 5000 unidades segun "
                    "regla_001_existing_estable con confianza 0.99."
                ),
                modelo="mock",
            )

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            with mock.patch("llm.explainer._llamar_anthropic", side_effect=fake_llm):
                expl = explicar(self.ids[0], self.store)
                self.assertTrue(expl.fallback,
                    f"Esperaba fallback por alucinacion, ev={expl}")
                self.assertIn("alucinacion", expl.razon_fallback.lower())
                # En la respuesta_cruda quedan los numeros alucinados
                self.assertIn("5000", expl.respuesta_cruda)
                # Pero el texto final es el fallback (sin 5000)
                self.assertNotIn("5000", expl.texto)

    def test_llm_responde_legitimamente_se_acepta(self):
        """LLM responde sin numeros nuevos -> se acepta."""

        def fake_llm(prompt, max_tokens=250, timeout_s=15.0):
            from llm.explainer import _LLMCallResult
            return _LLMCallResult(
                texto=(
                    "Decision para SKU 247329 aplica regla_001_existing_estable, "
                    "categoria DECORACION estable."
                ),
                modelo="mock",
            )

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            with mock.patch("llm.explainer._llamar_anthropic", side_effect=fake_llm):
                expl = explicar(self.ids[0], self.store)
                self.assertFalse(expl.fallback)
                self.assertIn("regla_001_existing_estable", expl.cita_fuentes)


# =============================================================================
# Tests: error de API se maneja con fallback
# =============================================================================


class TestErrorLLM(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store, self.ids = _setup_store_con_5_decisiones(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_llm_levanta_excepcion_se_usa_fallback(self):
        def fake_llm(prompt, max_tokens=250, timeout_s=15.0):
            raise RuntimeError("API timeout simulado")

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            with mock.patch("llm.explainer._llamar_anthropic", side_effect=fake_llm):
                expl = explicar(self.ids[0], self.store)
                self.assertTrue(expl.fallback)
                self.assertIn("LLM error", expl.razon_fallback)

    def test_sin_api_key_usa_fallback(self):
        """Sin ANTHROPIC_API_KEY, _llamar_anthropic levanta y caemos a fallback."""
        with mock.patch.dict(os.environ, {}, clear=True):
            expl = explicar(self.ids[0], self.store)
            self.assertTrue(expl.fallback)


# =============================================================================
# Tests: log de calls al LLM
# =============================================================================


class TestLogCalls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store, self.ids = _setup_store_con_5_decisiones(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_se_appenda_si_path_dado(self):
        log_path = Path(self.tmp.name) / "llm_log.jsonl"
        explicar(self.ids[0], self.store,
                  forzar_fallback=True, log_path=log_path)
        explicar(self.ids[1], self.store,
                  forzar_fallback=True, log_path=log_path)
        self.assertTrue(log_path.exists())
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
