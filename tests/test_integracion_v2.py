"""Tests de integracion v2 - 4 escenarios end-to-end (Bloque 11).

Cada escenario corre el pipeline completo:

    DecisionContext -> Deontica (Bloque 6) -> Dispatcher (Bloque 7)
                       -> Audit PROV-O (Bloque 8) -> Explainer LLM (Bloque 10)

Verifica que cada capa hace lo correcto Y que las capas se conectan bien:

    1. Existente reposicion         -> EWMA + bounded, audit OK, explainer OK
    2. SKU nuevo cold-start         -> open_loop + cold_start_similarity
    3. Trend signal alta confianza  -> regla_020 con unbounded
    4. Decision bloqueada (perecedero) -> dispatcher devuelve sin algoritmo,
                                          audit registra bloqueo, explainer
                                          explica POR QUE
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audit import AuditStore  # noqa: E402
from deontic import DeonticResolver  # noqa: E402
from dispatcher import (  # noqa: E402
    AlgorithmDispatcher,
    DecisionContext,
    SimilarRef,
    TipoSku,
    TrendSignal,
)
from llm import explicar  # noqa: E402


CATALOGO_RULES = ROOT / "config" / "dispatcher_rules.yaml"
CATALOGO_NORMAS = ROOT / "ontology_semantic" / "normas_marketplace.ttl"


# =============================================================================
# Helpers
# =============================================================================


def _fresh_pipeline(tmp: Path):
    """Construye los componentes del pipeline en estado limpio."""
    audit_store = AuditStore(tmp / "audit.ttl")
    dispatcher = AlgorithmDispatcher.from_yaml(
        CATALOGO_RULES, audit_store=audit_store
    )
    resolver = DeonticResolver.from_ttl(CATALOGO_NORMAS)
    return resolver, dispatcher, audit_store


def _evaluar_deonticamente(
    resolver: DeonticResolver,
    decision: dict,
    contexto: dict,
):
    """Wrapper para que los tests no dependan de la firma exacta del resolver."""
    return resolver.evaluar(decision, contexto)


# =============================================================================
# ESCENARIO 1: SKU existente reposicion
# =============================================================================


class TestEscenario1_ExistenteReposicion(unittest.TestCase):
    """SKU 247329 (ESFERA DECOR 10x10), historia 104 semanas, baja
    volatilidad. Espero:
    - Deontica permite (ninguna prohibition aplica).
    - Dispatcher dispara regla_001_existing_estable.
    - Stages: affine + ewma + bounded + simple_dev + dynamic_control.
    - Audit log persiste la decision.
    - Explainer genera prosa que cita la regla.
    """

    def test_pipeline_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolver, dispatcher, audit_store = _fresh_pipeline(Path(tmp))

            # 1. Deontica: evaluamos la decision propuesta de comprar SKU 247329
            decision = {
                "tipo": "compra",
                "monto_usd": 500.0,
                "lead_time_dias": 5.0,
                "aprobacion_supervisor": True,
                "aprobacion_excepcion": False,
                "validacion_humana": False,
                "justificacion_escrita": False,
                "exceso_budget_pct": 0.0,
                "cantidad": 50.0,
                "descuento_volumen_pct": 0.0,
            }
            contexto_deontico = {
                "now": datetime(2026, 6, 15, tzinfo=timezone.utc),  # fuera de pico
                "perecedero": False,
                "shelf_life_dias": 0.0,
                "sku_critico": False,
                "sku_piloto": False,
                "cold_start": False,
                "proveedor_activo": True,
                "proveedor_exterior": False,
                "proveedores_disponibles": 3,
            }
            eval_d = _evaluar_deonticamente(resolver, decision, contexto_deontico)
            self.assertTrue(eval_d.permitida,
                f"Esperaba permitida, ev={eval_d}")

            # 2. Dispatcher con eval deontica permitida
            ctx = DecisionContext(
                sku="247329",
                tipo_sku=TipoSku.EXISTING,
                nombre="ESFERA DECOR 10x10",
                categoria="DECORACION",
                semanas_historia=104,
                volatilidad_forecast=0.18,
                proveedores_disponibles=3,
                eval_deontica=eval_d,
            )
            rec = dispatcher.decidir(ctx)
            self.assertTrue(rec.algoritmo_invocado)
            self.assertEqual(
                rec.reglas_aplicadas, ("regla_001_existing_estable",)
            )
            self.assertIn("affine_ordering_policy", rec.descriptores_ids)
            self.assertIn("ewma_smoothing", rec.descriptores_ids)
            self.assertIn("bounded_deviations", rec.descriptores_ids)
            self.assertAlmostEqual(rec.confianza, 0.90, places=2)

            # 3. Audit persistio la decision
            ids = audit_store.list_decisions()
            self.assertEqual(len(ids), 1)
            data = audit_store.get_decision(ids[0])
            self.assertEqual(data["rule_applied"], "regla_001_existing_estable")
            self.assertFalse(data["blocked_by_deontic"])

            # 4. Explainer genera prosa legible (modo fallback offline)
            expl = explicar(ids[0], audit_store, forzar_fallback=True)
            self.assertGreater(len(expl.texto), 30)
            self.assertIn("regla_001_existing_estable", expl.cita_fuentes)
            self.assertIn("247329", expl.texto)


# =============================================================================
# ESCENARIO 2: SKU nuevo cold-start con similar alto
# =============================================================================


class TestEscenario2_ColdStartConSimilar(unittest.TestCase):
    """SKU 246295 (ESFERA NAVIDENA NUEVA), sin historia, similar top-1
    score 0.85 sobre SKU 247329. Espero:
    - Deontica: si hay 1 solo proveedor + aprobacion -> P5 derrota O4 (Bloque 6).
    - Dispatcher dispara regla_010_cold_start_similar_alto.
    - Stages incluyen open_loop + cold_start_similarity.
    - heredar_de_sku resuelto a 247329 via template.
    """

    def test_pipeline_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolver, dispatcher, audit_store = _fresh_pipeline(Path(tmp))

            # Deontica: SKU critico con 1 proveedor + aprobacion -> P5 derrota O4
            decision = {
                "tipo": "compra",
                "monto_usd": 200.0,
                "lead_time_dias": 5.0,
                "aprobacion_supervisor": True,
                "aprobacion_excepcion": True,  # <- la clave
                "validacion_humana": False,
                "justificacion_escrita": False,
                "exceso_budget_pct": 0.0,
                "cantidad": 20.0,
                "descuento_volumen_pct": 0.0,
            }
            contexto_deontico = {
                "now": datetime(2026, 6, 15, tzinfo=timezone.utc),
                "perecedero": False,
                "sku_critico": True,
                "sku_piloto": False,
                "cold_start": True,
                "cold_start_confidence": 0.8,  # >= 0.5 -> O5 no aplica
                "proveedor_activo": True,
                "proveedor_exterior": False,
                "proveedores_disponibles": 1,  # solo 1 -> O4 disparada
            }
            eval_d = _evaluar_deonticamente(resolver, decision, contexto_deontico)
            self.assertTrue(eval_d.permitida,
                f"P5 deberia derrotar O4, ev={eval_d}")
            derrotadas_ids = [nid for nid, _ in eval_d.normas_derrotadas]
            self.assertIn("O_sku_critico_dos_proveedores", derrotadas_ids)

            # Dispatcher
            ctx = DecisionContext(
                sku="246295",
                tipo_sku=TipoSku.NEW,
                nombre="ESFERA NAVIDENA NUEVA",
                categoria="DECORACION",
                cold_start_confidence=0.8,
                similar_top_k=(
                    SimilarRef(sku="247329", score_total=0.85, confidence=0.8),
                ),
                eval_deontica=eval_d,
            )
            rec = dispatcher.decidir(ctx)
            self.assertTrue(rec.algoritmo_invocado)
            self.assertEqual(
                rec.reglas_aplicadas, ("regla_010_cold_start_similar_alto",)
            )
            self.assertIn("open_loop", rec.descriptores_ids)
            self.assertIn("cold_start_similarity", rec.descriptores_ids)

            # Template heredar_de_sku resuelto
            cs = next(
                s for s in rec.stages
                if s.descriptor_id == "cold_start_similarity"
            )
            self.assertEqual(cs.parametros["heredar_de_sku"], "247329")

            # Audit
            ids = audit_store.list_decisions()
            self.assertEqual(len(ids), 1)
            data = audit_store.get_decision(ids[0])
            self.assertIn("cold_start_similarity", data["stages"])

            # Explainer
            expl = explicar(ids[0], audit_store, forzar_fallback=True)
            self.assertIn("regla_010_cold_start_similar_alto", expl.cita_fuentes)


# =============================================================================
# ESCENARIO 3: Trend signal con cold_start_confidence baja -> revision humana
# =============================================================================


class TestEscenario3_TrendBajaConfianzaRevisionHumana(unittest.TestCase):
    """Trend signal pero la cold_start_confidence < 0.5 dispara la
    obligacion deontica O5 (validacion humana). Espero:
    - Deontica: O5 aplicable y NO satisfecha -> obligacion pendiente.
    - Dispatcher: bloqueada por deontica (no invoca algoritmo).
    - Audit: registra wasBlockedByDeontic=true + wasBlockedBy O5.
    - Explainer: explica POR QUE bloqueada.
    """

    def test_pipeline_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolver, dispatcher, audit_store = _fresh_pipeline(Path(tmp))

            # Deontica: cold_start_confidence < 0.5 + sin validacion humana -> O5
            decision = {
                "tipo": "compra",
                "monto_usd": 300.0,
                "lead_time_dias": 5.0,
                "aprobacion_supervisor": True,
                "aprobacion_excepcion": False,
                "validacion_humana": False,  # <- la clave: O5 dispara
                "justificacion_escrita": False,
                "exceso_budget_pct": 0.0,
                "cantidad": 20.0,
                "descuento_volumen_pct": 0.0,
            }
            contexto_deontico = {
                "now": datetime(2026, 6, 15, tzinfo=timezone.utc),
                "perecedero": False,
                "sku_critico": False,
                "sku_piloto": False,
                "cold_start": True,
                "cold_start_confidence": 0.4,  # <- la clave: < 0.5
                "proveedor_activo": True,
                "proveedor_exterior": False,
                "proveedores_disponibles": 2,
            }
            eval_d = _evaluar_deonticamente(resolver, decision, contexto_deontico)
            self.assertFalse(eval_d.permitida,
                f"O5 deberia bloquear, ev={eval_d}")
            self.assertIn(
                "O_validacion_humana_coldstart_low_conf",
                eval_d.obligaciones_pendientes,
            )

            # Dispatcher: deteca bloqueo deontico, no invoca algoritmo
            ctx = DecisionContext(
                sku="555_TRENDING",
                tipo_sku=TipoSku.TRENDING,
                nombre="ARBOL TRENDY",
                categoria="ARBOLES",
                semanas_historia=10,
                cold_start_confidence=0.4,
                trend_signal=TrendSignal(
                    fuente="google_trends", valor=2.1, confianza=0.85
                ),
                eval_deontica=eval_d,
            )
            rec = dispatcher.decidir(ctx)
            self.assertFalse(rec.algoritmo_invocado)
            self.assertEqual(rec.stages, ())
            self.assertIn(
                "O_validacion_humana_coldstart_low_conf",
                rec.bloqueada_por_deontica,
            )

            # Audit
            ids = audit_store.list_decisions()
            data = audit_store.get_decision(ids[0])
            self.assertTrue(data["blocked_by_deontic"])

            # Explainer: dice que esta BLOQUEADA y cita la obligacion
            expl = explicar(ids[0], audit_store, forzar_fallback=True)
            self.assertIn("BLOQUEADA", expl.texto)
            self.assertIn(
                "O_validacion_humana_coldstart_low_conf",
                expl.cita_fuentes,
            )


# =============================================================================
# ESCENARIO 4: Decision bloqueada por F estricta (perecedero sin viabilidad)
# =============================================================================


class TestEscenario4_BloqueadaPerecederoSinViabilidad(unittest.TestCase):
    """Compra de perecedero con lead_time 30d y shelf_life 14d. Espero:
    - Deontica: F1 (no defeasible) bloquea.
    - Dispatcher: no invoca algoritmo.
    - Audit: wasBlockedBy F_compra_perecedero_sin_viabilidad.
    - Explainer: cita la prohibicion.
    """

    def test_pipeline_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolver, dispatcher, audit_store = _fresh_pipeline(Path(tmp))

            decision = {
                "tipo": "compra",
                "monto_usd": 800.0,
                "lead_time_dias": 30.0,  # > shelf life
                "aprobacion_supervisor": True,
                "aprobacion_excepcion": False,
                "validacion_humana": False,
                "justificacion_escrita": False,
                "exceso_budget_pct": 0.0,
                "cantidad": 100.0,
                "descuento_volumen_pct": 0.0,
            }
            contexto_deontico = {
                "now": datetime(2026, 6, 15, tzinfo=timezone.utc),
                "perecedero": True,
                "shelf_life_dias": 14.0,  # 30 >= 14 -> F1 dispara
                "sku_critico": False,
                "sku_piloto": False,
                "cold_start": False,
                "proveedor_activo": True,
                "proveedor_exterior": False,
                "proveedores_disponibles": 3,
            }
            eval_d = _evaluar_deonticamente(resolver, decision, contexto_deontico)
            self.assertFalse(eval_d.permitida)
            self.assertIn(
                "F_compra_perecedero_sin_viabilidad", eval_d.bloqueada_por
            )

            # Dispatcher
            ctx = DecisionContext(
                sku="LECHE_NAVIDENA",
                tipo_sku=TipoSku.EXISTING,
                nombre="LECHE CONDENSADA NAVIDENA",
                categoria="LACTEOS",
                semanas_historia=80,
                eval_deontica=eval_d,
            )
            rec = dispatcher.decidir(ctx)
            self.assertFalse(rec.algoritmo_invocado)
            self.assertIn(
                "F_compra_perecedero_sin_viabilidad",
                rec.bloqueada_por_deontica,
            )

            # Audit
            ids = audit_store.list_decisions()
            data = audit_store.get_decision(ids[0])
            self.assertTrue(data["blocked_by_deontic"])
            self.assertIn(
                "F_compra_perecedero_sin_viabilidad",
                data["blocked_by_normas"],
            )

            # Explainer
            expl = explicar(ids[0], audit_store, forzar_fallback=True)
            self.assertIn("BLOQUEADA", expl.texto)
            self.assertIn(
                "F_compra_perecedero_sin_viabilidad", expl.cita_fuentes
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
