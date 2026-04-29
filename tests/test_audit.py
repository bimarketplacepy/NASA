"""Tests del audit trail PROV-O (Bloque 8).

Cubre:
    - AuditStore: creacion, log_decision, idempotencia, get_decision.
    - Subgrafo PROV-O bien formado (clases + propiedades + agentes).
    - Replay: reconstruccion de contexto + diff vs dispatcher actual.
    - 5 queries SPARQL de queries.sparql devolviendo resultados correctos.
    - Integracion con dispatcher: hook opcional, no afecta JSONL existente.
    - Manejo de decisiones bloqueadas por deontica (sin algoritmo).

NO requiere Neo4j corriendo. El audit log se escribe a un tempdir en cada
test para aislamiento.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF

from audit import (  # noqa: E402
    AuditStore,
    AuditStoreError,
    DecisionNotFoundError,
    QUERIES,
    replay,
)
from dispatcher import (  # noqa: E402
    AlgorithmDispatcher,
    DecisionContext,
    SimilarRef,
    TipoSku,
    TrendSignal,
)
from dispatcher.recommendation import (  # noqa: E402
    AlgorithmRecommendation,
    AlgorithmStage,
)


MKT = Namespace("http://marketplace.com.py/onto/v1#")
PROV = Namespace("http://www.w3.org/ns/prov#")

CATALOGO_RULES = ROOT / "config" / "dispatcher_rules.yaml"


# =============================================================================
# Helpers para construir contextos y recomendaciones de prueba
# =============================================================================


class _FakeEval:
    """Mock del EvaluacionDeontica del Bloque 6 (mismos getattr fields)."""

    def __init__(self, permitida=True, bloqueada_por=(), obligaciones_pendientes=()):
        self.permitida = permitida
        self.bloqueada_por = tuple(bloqueada_por)
        self.obligaciones_pendientes = tuple(obligaciones_pendientes)


def _ctx_existing(sku="247329"):
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.EXISTING,
        nombre="ESFERA DECOR 10x10",
        categoria="DECORACION",
        semanas_historia=104,
        volatilidad_forecast=0.18,
        cold_start_confidence=1.0,
        proveedores_disponibles=3,
    )


def _ctx_new_con_similar(sku="246295"):
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.NEW,
        nombre="ESFERA NAVIDENA NUEVA",
        categoria="DECORACION",
        cold_start_confidence=0.8,
        similar_top_k=(SimilarRef(sku="247329", score_total=0.85, confidence=0.8),),
    )


def _ctx_trending(sku="555"):
    return DecisionContext(
        sku=sku,
        tipo_sku=TipoSku.TRENDING,
        nombre="ARBOL TRENDY",
        categoria="ARBOLES",
        semanas_historia=60,
        volatilidad_forecast=0.4,
        trend_signal=TrendSignal(
            fuente="google_trends", valor=2.1, confianza=0.85
        ),
    )


def _ctx_bloqueada():
    return DecisionContext(
        sku="247329",
        tipo_sku=TipoSku.EXISTING,
        nombre="ESFERA",
        categoria="DECORACION",
        semanas_historia=100,
        eval_deontica=_FakeEval(
            permitida=False,
            bloqueada_por=("F_compra_perecedero_sin_viabilidad",),
        ),
    )


def _rec_simple(sku="247329"):
    """AlgorithmRecommendation minimal sin pasar por el dispatcher (para tests
    de store aislados)."""
    return AlgorithmRecommendation(
        sku=sku,
        stages=(
            AlgorithmStage(
                kind="policy_form",
                descriptor_id="affine_ordering_policy",
                parametros={"y0_initial": 0.0, "y1_initial": 0.0},
            ),
            AlgorithmStage(
                kind="weighting",
                descriptor_id="ewma_smoothing",
                parametros={"alpha": 0.15, "K": 1.0},
            ),
        ),
        reglas_aplicadas=("regla_001_existing_estable",),
        confianza=0.90,
        razonamiento=("ok",),
    )


def _rec_bloqueada():
    return AlgorithmRecommendation(
        sku="247329",
        stages=(),
        reglas_aplicadas=(),
        confianza=0.0,
        bloqueada_por_deontica=("F_compra_perecedero_sin_viabilidad",),
        razonamiento=("Deontica BLOQUEA",),
    )


# =============================================================================
# Tests: AuditStore basico
# =============================================================================


class TestAuditStoreBasico(unittest.TestCase):
    def test_store_inicializa_con_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit_log_v1.ttl"
            AuditStore(path)
            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8")
            self.assertIn("@prefix prov:", text)
            self.assertIn("PROV-O", text)
            self.assertIn("v1 (Bloque 8)", text)

    def test_log_decision_devuelve_id_con_prefijo_dec(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            ctx = _ctx_existing()
            rec = _rec_simple()
            decision_id = store.log_decision(context=ctx, recomendacion=rec)
            self.assertTrue(decision_id.startswith("dec_"))
            # uuid4 hex (32 chars) + 'dec_' prefix
            self.assertEqual(len(decision_id), len("dec_") + 32)

    def test_log_decision_idempotente(self):
        """Logging la misma decision_id dos veces no la duplica."""
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            ctx = _ctx_existing()
            rec = _rec_simple()
            did = store.log_decision(
                context=ctx, recomendacion=rec, decision_id="dec_test_idem"
            )
            self.assertEqual(did, "dec_test_idem")
            # Re-log
            did2 = store.log_decision(
                context=ctx, recomendacion=rec, decision_id="dec_test_idem"
            )
            self.assertEqual(did2, "dec_test_idem")
            # Solo aparece UNA vez como sujeto :Decision
            ids = store.list_decisions()
            self.assertEqual(ids.count("dec_test_idem"), 1)

    def test_decision_id_invalido_levanta(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            with self.assertRaises(AuditStoreError):
                store.log_decision(
                    context=_ctx_existing(),
                    recomendacion=_rec_simple(),
                    decision_id="bad-prefix-123",
                )


# =============================================================================
# Tests: subgrafo PROV-O bien formado
# =============================================================================


class TestSubgrafoPROV(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.ttl"
        self.store = AuditStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_decision_es_activity_y_tiene_props_core(self):
        did = self.store.log_decision(
            context=_ctx_existing(), recomendacion=_rec_simple()
        )
        g = self.store.graph()
        dec = MKT[did]

        self.assertIn((dec, RDF.type, MKT.Decision), g)
        self.assertIn((dec, RDF.type, PROV.Activity), g)
        self.assertIsNotNone(g.value(dec, PROV.startedAtTime))
        self.assertIsNotNone(g.value(dec, PROV.endedAtTime))
        self.assertIsNotNone(g.value(dec, PROV.wasAssociatedWith))
        self.assertIsNotNone(g.value(dec, MKT.appliedRule))
        self.assertIsNotNone(g.value(dec, MKT.hadConfidence))

    def test_context_es_entity_con_snapshot(self):
        did = self.store.log_decision(
            context=_ctx_existing(), recomendacion=_rec_simple()
        )
        g = self.store.graph()
        dec = MKT[did]
        ctx = g.value(dec, PROV.used)
        self.assertIsNotNone(ctx)
        self.assertIn((ctx, RDF.type, MKT.DecisionContext), g)
        self.assertIn((ctx, RDF.type, PROV.Entity), g)
        snap = g.value(ctx, MKT.contextSnapshot)
        self.assertIsNotNone(snap)
        # El snapshot debe ser JSON parseable
        import json

        parsed = json.loads(str(snap))
        self.assertEqual(parsed["sku"], "247329")
        self.assertEqual(parsed["tipo_sku"], "existing")

    def test_stages_se_persisten(self):
        did = self.store.log_decision(
            context=_ctx_existing(), recomendacion=_rec_simple()
        )
        g = self.store.graph()
        dec = MKT[did]
        stages = sorted(str(o) for o in g.objects(dec, MKT.hasStageDescriptor))
        self.assertEqual(
            stages, ["affine_ordering_policy", "ewma_smoothing"]
        )

    def test_invocaAlgoritmo_crea_uri_consistente_con_catalogo(self):
        """:invocaAlgoritmo apunta a mkt:algo_<descriptor_id> (consistente con
        el dump_to_turtle del Bloque 7)."""
        did = self.store.log_decision(
            context=_ctx_existing(), recomendacion=_rec_simple()
        )
        g = self.store.graph()
        dec = MKT[did]
        algos = {str(o) for o in g.objects(dec, MKT.invocaAlgoritmo)}
        self.assertIn(str(MKT.algo_affine_ordering_policy), algos)
        self.assertIn(str(MKT.algo_ewma_smoothing), algos)

    def test_decision_bloqueada_registra_normas(self):
        did = self.store.log_decision(
            context=_ctx_bloqueada(),
            recomendacion=_rec_bloqueada(),
            normas_evaluadas=("F_compra_perecedero_sin_viabilidad",),
        )
        g = self.store.graph()
        dec = MKT[did]
        # was_blocked_by_deontic = True
        bd = g.value(dec, MKT.wasBlockedByDeontic)
        self.assertEqual(bool(bd.toPython()), True)
        # wasBlockedBy norm linked
        blocked = list(g.objects(dec, MKT.wasBlockedBy))
        self.assertIn(MKT.F_compra_perecedero_sin_viabilidad, blocked)

    def test_agente_default_es_dispatcher_v1(self):
        did = self.store.log_decision(
            context=_ctx_existing(), recomendacion=_rec_simple()
        )
        g = self.store.graph()
        agent = g.value(MKT[did], PROV.wasAssociatedWith)
        self.assertEqual(str(agent), str(MKT.agente_dispatcher_v1))

    def test_agent_uri_custom(self):
        did = self.store.log_decision(
            context=_ctx_existing(),
            recomendacion=_rec_simple(),
            agent_uri="agente_humano_default",
        )
        g = self.store.graph()
        agent = g.value(MKT[did], PROV.wasAssociatedWith)
        self.assertEqual(str(agent), str(MKT.agente_humano_default))


# =============================================================================
# Tests: get_decision recupera datos completos
# =============================================================================


class TestGetDecision(unittest.TestCase):
    def test_get_decision_devuelve_dict_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            did = store.log_decision(
                context=_ctx_existing(), recomendacion=_rec_simple()
            )
            data = store.get_decision(did)
            self.assertEqual(data["decision_id"], did)
            self.assertEqual(data["rule_applied"], "regla_001_existing_estable")
            self.assertAlmostEqual(data["confidence"], 0.90, places=2)
            self.assertFalse(data["blocked_by_deontic"])
            self.assertEqual(
                sorted(data["stages"]),
                ["affine_ordering_policy", "ewma_smoothing"],
            )
            self.assertEqual(data["agent"], "agente_dispatcher_v1")
            self.assertIsInstance(data["started_at"], datetime)
            self.assertEqual(data["context_snapshot"]["sku"], "247329")

    def test_get_decision_inexistente_levanta(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            with self.assertRaises(DecisionNotFoundError):
                store.get_decision("dec_inexistente")


# =============================================================================
# Tests: integracion con dispatcher (hook opcional)
# =============================================================================


class TestDispatcherIntegration(unittest.TestCase):
    def test_dispatcher_loguea_via_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            dispatcher = AlgorithmDispatcher.from_yaml(
                CATALOGO_RULES, audit_store=store
            )
            ctx = _ctx_existing()
            rec = dispatcher.decidir(ctx)

            ids = store.list_decisions()
            self.assertEqual(len(ids), 1)
            data = store.get_decision(ids[0])
            self.assertEqual(data["rule_applied"], "regla_001_existing_estable")
            self.assertEqual(data["context_snapshot"]["sku"], "247329")

    def test_dispatcher_sin_audit_store_no_genera_log(self):
        dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)
        # Ningun crash, devuelve recomendacion normal
        rec = dispatcher.decidir(_ctx_existing())
        self.assertTrue(rec.algoritmo_invocado)

    def test_dispatcher_loguea_decision_bloqueada(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            dispatcher = AlgorithmDispatcher.from_yaml(
                CATALOGO_RULES, audit_store=store
            )
            rec = dispatcher.decidir(_ctx_bloqueada())
            # Debe loguearse aunque no haya algoritmo
            ids = store.list_decisions()
            self.assertEqual(len(ids), 1)
            data = store.get_decision(ids[0])
            self.assertTrue(data["blocked_by_deontic"])
            self.assertIn(
                "F_compra_perecedero_sin_viabilidad",
                data["blocked_by_normas"],
            )


# =============================================================================
# Tests: replay
# =============================================================================


class TestReplay(unittest.TestCase):
    def test_replay_identico_si_reglas_no_cambian(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            dispatcher = AlgorithmDispatcher.from_yaml(
                CATALOGO_RULES, audit_store=store
            )
            ctx = _ctx_existing()
            dispatcher.decidir(ctx)

            did = store.list_decisions()[0]
            summary = replay(did, store, dispatcher)

            self.assertTrue(
                summary.igual,
                f"Replay deberia ser identico, diff={summary.diff}",
            )
            self.assertEqual(summary.original_rule, summary.replayed_rule)

    def test_replay_reconstruye_context_correctamente(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            dispatcher = AlgorithmDispatcher.from_yaml(
                CATALOGO_RULES, audit_store=store
            )
            # Contexto cold-start con similar - tiene tuple de SimilarRef
            ctx = _ctx_new_con_similar()
            dispatcher.decidir(ctx)

            did = store.list_decisions()[0]
            summary = replay(did, store, dispatcher)

            # El replay debe haber reconstruido el SimilarRef
            self.assertEqual(
                summary.original_rule, "regla_010_cold_start_similar_alto"
            )
            self.assertTrue(summary.igual)
            # El stage cold_start_similarity debe estar
            assert summary.replayed is not None
            self.assertIn(
                "cold_start_similarity", summary.replayed.descriptores_ids
            )

    def test_replay_render_humano_funciona(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            dispatcher = AlgorithmDispatcher.from_yaml(
                CATALOGO_RULES, audit_store=store
            )
            dispatcher.decidir(_ctx_existing())
            did = store.list_decisions()[0]
            summary = replay(did, store, dispatcher)
            text = summary.render()
            self.assertIn(did, text)
            self.assertIn("VEREDICTO", text)


# =============================================================================
# Tests: queries SPARQL
# =============================================================================


class TestQueriesSparql(unittest.TestCase):
    """Verifica que las 5 queries devuelven resultados esperados sobre un
    audit log con varias decisiones."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "audit.ttl"
        cls.store = AuditStore(cls.path)
        dispatcher = AlgorithmDispatcher.from_yaml(
            CATALOGO_RULES, audit_store=cls.store
        )

        # 5 decisiones de prueba con variantes
        dispatcher.decidir(_ctx_existing(sku="247329"))
        dispatcher.decidir(_ctx_existing(sku="247330"))
        dispatcher.decidir(_ctx_new_con_similar(sku="246295"))
        dispatcher.decidir(_ctx_trending(sku="555"))
        dispatcher.decidir(_ctx_bloqueada())  # SKU 247329 bloqueada por F1

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_query_decisiones_ultima_semana(self):
        q = QUERIES["decisiones_ultima_semana"]
        # Hace una semana
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        rows = q.run(self.store.graph(), since=since)
        # Las 5 decisiones del setUpClass cayeron en la ultima semana
        self.assertEqual(len(rows), 5)
        # Tienen sku
        skus = {str(r["sku"]) for r in rows}
        self.assertIn("247329", skus)
        self.assertIn("555", skus)

    def test_query_bloqueadas_por_norma(self):
        q = QUERIES["decisiones_bloqueadas_por_norma"]
        rows = q.run(
            self.store.graph(),
            norma_id="F_compra_perecedero_sin_viabilidad",
        )
        # Solo la decision bloqueada
        self.assertEqual(len(rows), 1)

    def test_query_algoritmos_por_categoria(self):
        q = QUERIES["algoritmos_por_categoria"]
        rows = q.run(self.store.graph())
        # Debe haber al menos categorias DECORACION y ARBOLES
        cats = {str(r["categoria"]) for r in rows}
        self.assertIn("DECORACION", cats)
        # Cada fila tiene un algoritmo y un count
        for r in rows:
            self.assertIsNotNone(r.get("algoritmo"))
            self.assertGreater(int(r["n"]), 0)

    def test_query_cadena_provenance(self):
        q = QUERIES["cadena_provenance"]
        did = self.store.list_decisions()[0]
        rows = q.run(self.store.graph(), decision_id=did)
        # Debe devolver multiples (prop, value)
        self.assertGreater(len(rows), 5)
        props = {str(r["prop"]) for r in rows}
        # Esperamos al menos prov:wasAssociatedWith, prov:used, prov:startedAtTime
        self.assertTrue(
            any("wasAssociatedWith" in p for p in props),
            f"Esperaba wasAssociatedWith en {props}",
        )

    def test_query_decisiones_de_agente(self):
        q = QUERIES["decisiones_de_agente"]
        desde = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        hasta = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        rows = q.run(
            self.store.graph(),
            agent_id="agente_dispatcher_v1",
            desde=desde,
            hasta=hasta,
        )
        # Las 5 decisiones fueron del dispatcher v1
        self.assertEqual(len(rows), 5)


# =============================================================================
# Smoke: 5 decisiones registradas + replay + queries (criterio de aceptacion)
# =============================================================================


class TestSmokeBloque8(unittest.TestCase):
    def test_5_decisiones_quedan_registradas_y_consultables(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "audit_log_v1.ttl"
            store = AuditStore(store_path)
            dispatcher = AlgorithmDispatcher.from_yaml(
                CATALOGO_RULES, audit_store=store
            )

            # 5 decisiones (criterio de aceptacion)
            ctxs = [
                _ctx_existing(sku="247329"),
                _ctx_existing(sku="247330"),
                _ctx_new_con_similar(sku="246295"),
                _ctx_trending(sku="555"),
                _ctx_bloqueada(),
            ]
            decision_ids = []
            for ctx in ctxs:
                rec = dispatcher.decidir(ctx)
                # Sacar el id del log (last in)
                ids = store.list_decisions()
                decision_ids.append(ids[-1])

            self.assertEqual(len(decision_ids), 5)
            self.assertEqual(len(set(decision_ids)), 5)  # todos unicos

            # Las 3 queries de ejemplo del prompt devuelven resultados
            g = store.graph()
            since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            ultima_semana = QUERIES["decisiones_ultima_semana"].run(g, since=since)
            self.assertEqual(len(ultima_semana), 5)

            bloqueadas = QUERIES["decisiones_bloqueadas_por_norma"].run(
                g, norma_id="F_compra_perecedero_sin_viabilidad"
            )
            self.assertEqual(len(bloqueadas), 1)

            algoritmos = QUERIES["algoritmos_por_categoria"].run(g)
            self.assertGreater(len(algoritmos), 0)

            # Replay de una de las decisiones reconstruye el contexto
            summary = replay(decision_ids[0], store, dispatcher)
            self.assertTrue(summary.igual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
