"""Tests del dispatcher (Bloque 7).

Cubre:
    - 3 escenarios del proyecto (existing+historia, new+similar, trend+conf).
    - Integracion deontica: si bloqueada por norma, no se invoca algoritmo.
    - SafeExpressionEvaluator: rechaza dunders, lambdas, imports.
    - rules.yaml schema validation: errores estructurales y semanticos.
    - Templates {{ context.x }} en parametros.
    - First-match-wins por prioridad.
    - Construccion de stages con mezcla de defaults + overrides.

NO requiere Neo4j corriendo. El DecisionContext se construye inline en
tests; la integracion con OntologyClientV2 (`from_ontology`) se mockea.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatcher import (  # noqa: E402
    AlgorithmDispatcher,
    AlgorithmRecommendation,
    DecisionContext,
    EventoProximo,
    ExpresionInsegura,
    ExpresionInvalida,
    Kind,
    RulesYAMLInvalido,
    SafeExpressionEvaluator,
    SimilarRef,
    TipoSku,
    TrendSignal,
)
from dispatcher.algorithms import CATALOGO  # noqa: E402
from dispatcher.dispatcher import _safe_for_json  # noqa: E402
from dispatcher.rules import (  # noqa: E402
    load_rules,
    resolve_template,
)


CATALOGO_RULES = ROOT / "config" / "dispatcher_rules.yaml"


# Mock minimal de eval_deontica (mismos field names que EvaluacionDeontica
# del Bloque 6, accessible por getattr).
class _FakeEval:
    def __init__(
        self,
        permitida: bool,
        bloqueada_por: tuple = (),
        obligaciones_pendientes: tuple = (),
    ) -> None:
        self.permitida = permitida
        self.bloqueada_por = bloqueada_por
        self.obligaciones_pendientes = obligaciones_pendientes

    def to_dict(self) -> dict:
        return {
            "permitida": self.permitida,
            "bloqueada_por": list(self.bloqueada_por),
            "obligaciones_pendientes": list(self.obligaciones_pendientes),
        }


# =============================================================================
# Helper: construir DecisionContext rapido para escenarios
# =============================================================================


def _ctx_existing_estable(sku: str = "247329") -> DecisionContext:
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.EXISTING,
        nombre="ESFERA DECOR 10x10",
        categoria="DECORACION",
        semanas_historia=104,
        cantidad_stock=200.0,
        velocidad=12.0,
        volatilidad_forecast=0.18,
        cold_start_confidence=1.0,
        similar_top_k=(),
        proveedores_disponibles=3,
    )


def _ctx_existing_volatil(sku: str = "247330") -> DecisionContext:
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.EXISTING,
        nombre="ARTICULO VOLATIL",
        semanas_historia=78,
        volatilidad_forecast=0.55,
    )


def _ctx_new_con_similar_alto(sku: str = "246295") -> DecisionContext:
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.NEW,
        nombre="ESFERA NAVIDENA NUEVA",
        semanas_historia=0,
        cold_start_confidence=0.8,
        similar_top_k=(
            SimilarRef(sku="247329", score_total=0.85, confidence=0.8),
            SimilarRef(sku="247330", score_total=0.78, confidence=0.7),
        ),
    )


def _ctx_new_con_similar_dudoso(sku: str = "246300") -> DecisionContext:
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.NEW,
        nombre="ARTICULO RARO",
        cold_start_confidence=0.4,
        similar_top_k=(
            SimilarRef(sku="111", score_total=0.45, confidence=0.5),
        ),
    )


def _ctx_trend_alta_conf(sku: str = "555") -> DecisionContext:
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.TRENDING,
        nombre="ARBOL ARTIFICIAL TRENDY",
        semanas_historia=60,
        volatilidad_forecast=0.4,
        trend_signal=TrendSignal(
            fuente="google_trends", valor=2.1, confianza=0.85
        ),
    )


def _ctx_bloqueada_deontica(sku: str = "247329") -> DecisionContext:
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.EXISTING,
        semanas_historia=100,
        eval_deontica=_FakeEval(
            permitida=False,
            bloqueada_por=("F_compra_perecedero_sin_viabilidad",),
        ),
    )


# =============================================================================
# Test: 3 escenarios principales del prompt
# =============================================================================


class TestEscenarioExistingConHistoria(unittest.TestCase):
    """SKU establecido con historia >= 52 sem y volatilidad < 0.3 ->
    regla_001 (affine + ewma + bounded + simple_dev + dynamic_control).
    """

    def setUp(self):
        self.dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)

    def test_dispara_regla_001_existing_estable(self):
        ctx = _ctx_existing_estable()
        rec = self.dispatcher.decidir(ctx)
        self.assertTrue(rec.algoritmo_invocado, f"esperaba algoritmo, rec={rec}")
        self.assertEqual(rec.reglas_aplicadas, ("regla_001_existing_estable",))
        # Stages incluyen los 5 descriptores de la regla
        self.assertIn("affine_ordering_policy", rec.descriptores_ids)
        self.assertIn("ewma_smoothing", rec.descriptores_ids)
        self.assertIn("bounded_deviations", rec.descriptores_ids)
        self.assertIn("dynamic_control_framing", rec.descriptores_ids)
        # Confianza de la regla 001 es 0.90 (sin ajustes para existing)
        self.assertAlmostEqual(rec.confianza, 0.90, places=2)

    def test_volatil_dispara_regla_002_con_correlated(self):
        ctx = _ctx_existing_volatil()
        rec = self.dispatcher.decidir(ctx)
        self.assertEqual(rec.reglas_aplicadas, ("regla_002_existing_volatil",))
        self.assertIn("correlated_deviations", rec.descriptores_ids)

    def test_parametros_ewma_alpha_correcto(self):
        ctx = _ctx_existing_estable()
        rec = self.dispatcher.decidir(ctx)
        ewma = next(s for s in rec.stages if s.descriptor_id == "ewma_smoothing")
        self.assertEqual(ewma.parametros["alpha"], 0.15)

    def test_kinds_diferentes_por_stage(self):
        """Verificar que no hay dos stages del mismo kind."""
        ctx = _ctx_existing_estable()
        rec = self.dispatcher.decidir(ctx)
        kinds = list(rec.kinds)
        self.assertEqual(len(kinds), len(set(kinds)),
            f"kinds repetidos: {kinds}")


class TestEscenarioColdStartConSimilar(unittest.TestCase):
    """SKU NEW con similar de score >= 0.7 -> regla_010 con cold_start_similarity
    + open_loop. Hereda parametros del similar via template.
    """

    def setUp(self):
        self.dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)

    def test_dispara_regla_010_cold_start(self):
        ctx = _ctx_new_con_similar_alto()
        rec = self.dispatcher.decidir(ctx)
        self.assertTrue(rec.algoritmo_invocado)
        self.assertEqual(rec.reglas_aplicadas, ("regla_010_cold_start_similar_alto",))
        self.assertIn("cold_start_similarity", rec.descriptores_ids)
        self.assertIn("open_loop", rec.descriptores_ids)

    def test_template_heredar_de_sku_resuelto(self):
        """{{ context.similar_top_sku }} debe resolverse al sku del top-1 (247329)."""
        ctx = _ctx_new_con_similar_alto()
        rec = self.dispatcher.decidir(ctx)
        cs = next(
            s for s in rec.stages if s.descriptor_id == "cold_start_similarity"
        )
        self.assertEqual(cs.parametros["heredar_de_sku"], "247329")

    def test_confianza_penalizada_si_cold_start_low(self):
        """Si cold_start_confidence < 0.7, la confianza_base se ajusta abajo."""
        ctx = _ctx_new_con_similar_dudoso()
        rec = self.dispatcher.decidir(ctx)
        # regla_011 base 0.40, ajustada por cold_start_confidence=0.4
        # ajustada = 0.40 * 0.4 = 0.16
        self.assertLess(rec.confianza, 0.40)

    def test_similar_dudoso_dispara_regla_011(self):
        ctx = _ctx_new_con_similar_dudoso()
        rec = self.dispatcher.decidir(ctx)
        self.assertEqual(
            rec.reglas_aplicadas, ("regla_011_cold_start_similar_dudoso",)
        )
        # No usa cold_start_similarity (no hay similar bueno)
        self.assertNotIn("cold_start_similarity", rec.descriptores_ids)


class TestEscenarioTrendSignal(unittest.TestCase):
    """Trend signal con confidence >= 0.8 -> regla_020 con affine + unbounded."""

    def setUp(self):
        self.dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)

    def test_trend_alta_conf_dispara_regla_020(self):
        ctx = _ctx_trend_alta_conf()
        rec = self.dispatcher.decidir(ctx)
        self.assertTrue(rec.algoritmo_invocado)
        self.assertEqual(
            rec.reglas_aplicadas, ("regla_020_trend_signal_alta_confidence",)
        )

    def test_trend_alta_usa_unbounded(self):
        ctx = _ctx_trend_alta_conf()
        rec = self.dispatcher.decidir(ctx)
        self.assertIn("unbounded_deviations", rec.descriptores_ids)
        self.assertNotIn("bounded_deviations", rec.descriptores_ids)

    def test_trend_alta_da_bonus_confianza(self):
        """trend_confidence>=0.8 da bonus 5%."""
        ctx = _ctx_trend_alta_conf()
        rec = self.dispatcher.decidir(ctx)
        # base 0.75 * 1.05 = 0.7875
        self.assertGreater(rec.confianza, 0.75)


# =============================================================================
# Test: integracion deontica
# =============================================================================


class TestIntegracionDeontica(unittest.TestCase):
    def setUp(self):
        self.dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)

    def test_bloqueada_por_norma_no_invoca_algoritmo(self):
        ctx = _ctx_bloqueada_deontica()
        rec = self.dispatcher.decidir(ctx)
        self.assertFalse(rec.algoritmo_invocado)
        self.assertEqual(rec.stages, ())
        self.assertEqual(rec.reglas_aplicadas, ())
        self.assertEqual(
            rec.bloqueada_por_deontica, ("F_compra_perecedero_sin_viabilidad",)
        )
        self.assertEqual(rec.confianza, 0.0)
        # Razonamiento debe mencionar la deontica
        rz = " ".join(rec.razonamiento)
        self.assertIn("Deontica BLOQUEA", rz)

    def test_eval_deontica_permitida_avanza_normal(self):
        eval_ok = _FakeEval(permitida=True)
        ctx = DecisionContext(
            sku="247329",
            tipo_sku=TipoSku.EXISTING,
            semanas_historia=104,
            volatilidad_forecast=0.18,
            eval_deontica=eval_ok,
        )
        rec = self.dispatcher.decidir(ctx)
        self.assertTrue(rec.algoritmo_invocado)
        self.assertEqual(
            rec.reglas_aplicadas, ("regla_001_existing_estable",)
        )

    def test_sin_eval_deontica_avanza_normal(self):
        """eval_deontica=None -> dispatcher procede normalmente."""
        ctx = _ctx_existing_estable()
        rec = self.dispatcher.decidir(ctx)
        self.assertTrue(rec.algoritmo_invocado)
        self.assertEqual(rec.bloqueada_por_deontica, ())


# =============================================================================
# Test: Safe AST evaluator
# =============================================================================


class TestSafeExpressionEvaluator(unittest.TestCase):
    def setUp(self):
        self.ev = SafeExpressionEvaluator({"context"})

    def test_evalua_comparaciones_basicas(self):
        ctx = _ctx_existing_estable()
        ns = {"context": ctx}
        self.assertTrue(self.ev.evaluate("context.semanas_historia >= 52", ns))
        self.assertFalse(self.ev.evaluate("context.semanas_historia < 10", ns))

    def test_evalua_atributo_anidado(self):
        ctx = _ctx_new_con_similar_alto()
        ns = {"context": ctx}
        self.assertEqual(
            self.ev.evaluate("context.similar_top_k[0].sku", ns), "247329"
        )

    def test_evalua_and_or_not(self):
        ctx = _ctx_existing_estable()
        ns = {"context": ctx}
        self.assertTrue(
            self.ev.evaluate(
                "context.tipo_sku == 'existing' and context.semanas_historia > 50",
                ns,
            )
        )
        self.assertTrue(
            self.ev.evaluate(
                "context.tipo_sku == 'new' or context.semanas_historia > 50",
                ns,
            )
        )
        # ctx_existing_estable tiene volatilidad=0.18 < 0.3, es_volatil=False,
        # not es_volatil = True
        self.assertTrue(self.ev.evaluate("not context.es_volatil", ns))

    def test_funciones_permitidas(self):
        ctx = _ctx_existing_estable()
        ns = {"context": ctx}
        self.assertEqual(self.ev.evaluate("len(context.similar_top_k)", ns), 0)
        self.assertEqual(self.ev.evaluate("max(1, 2, 3)", ns), 3)

    def test_rechaza_dunder(self):
        with self.assertRaises(ExpresionInsegura):
            self.ev.validate("context.__class__")

    def test_rechaza_lambda(self):
        with self.assertRaises(ExpresionInsegura):
            self.ev.validate("(lambda x: x)(1)")

    def test_rechaza_listcomp(self):
        with self.assertRaises(ExpresionInsegura):
            self.ev.validate("[x for x in [1,2,3]]")

    def test_rechaza_funcion_no_permitida(self):
        with self.assertRaises(ExpresionInsegura):
            self.ev.validate("open('/etc/passwd')")
        with self.assertRaises(ExpresionInsegura):
            self.ev.validate("__import__('os')")

    def test_rechaza_nombre_no_permitido(self):
        with self.assertRaises(ExpresionInsegura):
            self.ev.validate("os.path.exists('/')")
        with self.assertRaises(ExpresionInsegura):
            self.ev.validate("ctx.foo")  # ctx no esta en allowed_names

    def test_rechaza_asignacion(self):
        # `ast.parse(mode='eval')` ya rechaza esto en parse, no en validate
        with self.assertRaises(ExpresionInvalida):
            self.ev.validate("x = 5")

    def test_evaluacion_de_template_resolver(self):
        ctx = _ctx_new_con_similar_alto()
        ns = {"context": ctx}
        # Template completo
        self.assertEqual(
            resolve_template("{{ context.similar_top_sku }}", ns, self.ev),
            "247329",
        )
        # No-template: passthrough
        self.assertEqual(resolve_template(0.15, ns, self.ev), 0.15)
        self.assertEqual(resolve_template("texto plano", ns, self.ev), "texto plano")


# =============================================================================
# Test: rules.yaml schema validation
# =============================================================================


class TestRulesYAMLValidacion(unittest.TestCase):
    """Errores estructurales y semanticos en rules.yaml deben levantar
    RulesYAMLInvalido con mensaje accionable.
    """

    def _write_yaml(self, content: str) -> Path:
        f = tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", encoding="utf-8", delete=False
        )
        f.write(content)
        f.close()
        return Path(f.name)

    def test_carga_catalogo_real_ok(self):
        rules = load_rules(CATALOGO_RULES)
        self.assertGreater(len(rules), 0)
        # Ordenado por prioridad desc
        prioridades = [r.prioridad for r in rules]
        self.assertEqual(prioridades, sorted(prioridades, reverse=True))

    def test_id_duplicado_levanta(self):
        path = self._write_yaml(
            """
- id: dup
  prioridad: 50
  cuando: []
  algoritmo: open_loop
- id: dup
  prioridad: 40
  cuando: []
  algoritmo: open_loop
"""
        )
        with self.assertRaises(RulesYAMLInvalido) as ctx:
            load_rules(path)
        self.assertIn("duplicado", str(ctx.exception))

    def test_descriptor_inexistente_levanta(self):
        path = self._write_yaml(
            """
- id: r1
  prioridad: 50
  cuando: []
  algoritmo: "open_loop + descriptor_inexistente"
"""
        )
        with self.assertRaises(RulesYAMLInvalido) as ctx:
            load_rules(path)
        self.assertIn("descriptor_inexistente", str(ctx.exception))

    def test_dos_descriptores_mismo_kind_levanta(self):
        path = self._write_yaml(
            """
- id: r1
  prioridad: 50
  cuando: []
  algoritmo: "affine_ordering_policy + open_loop"
"""
        )
        with self.assertRaises(RulesYAMLInvalido) as ctx:
            load_rules(path)
        self.assertIn("kind", str(ctx.exception))

    def test_condicion_insegura_levanta(self):
        path = self._write_yaml(
            """
- id: r1
  prioridad: 50
  cuando:
    - "context.__class__ == 'foo'"
  algoritmo: open_loop
"""
        )
        with self.assertRaises(RulesYAMLInvalido) as ctx:
            load_rules(path)
        self.assertIn("dunder", str(ctx.exception).lower() + str(ctx.exception))

    def test_template_inseguro_levanta(self):
        path = self._write_yaml(
            """
- id: r1
  prioridad: 50
  cuando: []
  algoritmo: "open_loop + uniform_recency_weighting + bounded_deviations + simple_absolute_deviation + static_robust_framing"
  parametros:
    bounded_deviations:
      epsilon_factor: "{{ context.__dict__ }}"
"""
        )
        with self.assertRaises(RulesYAMLInvalido) as ctx:
            load_rules(path)
        msg = str(ctx.exception).lower()
        self.assertTrue("dunder" in msg or "private" in msg or "__dict__" in msg)

    def test_prioridad_fuera_de_rango_levanta(self):
        path = self._write_yaml(
            """
- id: r1
  prioridad: 200
  cuando: []
  algoritmo: open_loop
"""
        )
        with self.assertRaises(RulesYAMLInvalido):
            load_rules(path)

    def test_extra_field_rechazado(self):
        path = self._write_yaml(
            """
- id: r1
  prioridad: 50
  cuando: []
  algoritmo: open_loop
  campo_no_existente: 42
"""
        )
        with self.assertRaises(RulesYAMLInvalido):
            load_rules(path)


# =============================================================================
# Test: orden y first-match-wins
# =============================================================================


class TestPriorityFirstMatchWins(unittest.TestCase):
    def setUp(self):
        self.dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)

    def test_existing_estable_no_dispara_regla_002(self):
        """existing+volatilidad<0.3 dispara 001, NO 002 (mas baja prio)."""
        ctx = _ctx_existing_estable()
        rec = self.dispatcher.decidir(ctx)
        self.assertEqual(rec.reglas_aplicadas, ("regla_001_existing_estable",))
        self.assertNotIn("regla_002_existing_volatil", rec.reglas_aplicadas)

    def test_evento_proximo_supera_regla_001(self):
        """regla_030 (prio 88) gana sobre regla_001 (prio 90)? No, 90 > 88.
        En realidad este test verifica: 030 NO gana cuando volatilidad<0.3
        porque la 001 (prio 90) la supera."""
        ctx = DecisionContext(
            sku="x",
            tipo_sku=TipoSku.EXISTING,
            semanas_historia=100,
            volatilidad_forecast=0.18,
            evento_proximo=EventoProximo(
                nombre="Navidad 2026", dias_hasta=20
            ),
        )
        rec = self.dispatcher.decidir(ctx)
        # Prioridad 90 > 88 -> regla_001 gana
        self.assertEqual(rec.reglas_aplicadas, ("regla_001_existing_estable",))


# =============================================================================
# Test: catalogo de algoritmos
# =============================================================================


class TestCatalogoAlgoritmos(unittest.TestCase):
    def test_catalogo_no_vacio(self):
        self.assertGreaterEqual(len(CATALOGO), 15)

    def test_catalogo_ids_unicos(self):
        ids = list(CATALOGO.keys())
        self.assertEqual(len(ids), len(set(ids)))

    def test_kinds_cubren_los_ejes_principales(self):
        kinds_presentes = {d.kind for d in CATALOGO.values()}
        # Al menos los 5 ejes principales del paper
        self.assertIn(Kind.POLICY_FORM, kinds_presentes)
        self.assertIn(Kind.WEIGHTING, kinds_presentes)
        self.assertIn(Kind.UNCERTAINTY_SET, kinds_presentes)
        self.assertIn(Kind.DEVIATION_METRIC, kinds_presentes)
        self.assertIn(Kind.CONSTRAINT_FAMILY, kinds_presentes)

    def test_descriptores_inmutables(self):
        d = next(iter(CATALOGO.values()))
        with self.assertRaises(Exception):
            d.descriptor_id = "x"  # type: ignore[misc]

    def test_dump_to_turtle_genera_string_no_vacio(self):
        from dispatcher.algorithms import dump_to_turtle

        ttl = dump_to_turtle()
        self.assertIn("a :Algorithm", ttl)
        self.assertIn("affine_ordering_policy", ttl)
        # Cada descriptor genera al menos 4 lineas (label, comment, kind, ref/concepto)
        self.assertGreater(len(ttl.splitlines()), len(CATALOGO) * 3)


# =============================================================================
# Test: audit trail
# =============================================================================


class TestAuditTrail(unittest.TestCase):
    def test_audit_jsonl_se_genera(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.jsonl"
            d = AlgorithmDispatcher.from_yaml(CATALOGO_RULES, audit_path=audit)
            d.decidir(_ctx_existing_estable())
            d.decidir(_ctx_new_con_similar_alto())

            self.assertTrue(audit.exists())
            lines = audit.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                rec = json.loads(line)
                self.assertIn("ts", rec)
                self.assertIn("context", rec)
                self.assertIn("recommendation", rec)
                self.assertIn("sku", rec["recommendation"])

    def test_safe_for_json_helper_tolera_dataclass_anidado(self):
        ctx = _ctx_new_con_similar_alto()
        out = _safe_for_json(ctx)
        self.assertEqual(out["sku"], "246295")
        self.assertEqual(len(out["similar_top_k"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
