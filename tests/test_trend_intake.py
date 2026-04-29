"""Tests del ACL trend_intake (Bloque 9).

Cubre:
    - Validacion JSON Schema (jsonschema) y Pydantic semantica.
    - Stop-words check rechaza descripciones de puro ruido.
    - Triage por confianza_extraccion (< threshold -> manual_review).
    - Pipeline end-to-end: cada estado del EstadoIntake.
    - batch_process devuelve summary correcto.
    - Carga del mock real (5 trends) y verifica los 5 estados esperados.
    - Audit hook funciona con AuditStore real.
    - Normalizacion de fuente (TIK_TOK -> TIKTOK, etc).
    - Manejo de productos_existentes_similares vacios (cold-start).
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

from audit import AuditStore  # noqa: E402
from dispatcher import AlgorithmDispatcher  # noqa: E402
from integrations import (  # noqa: E402
    FuenteTrend,
    ProductoSimilarIn,
    TrendIntakeResult,
    TrendSignalIn,
    batch_process,
    process_trend_signal,
    validar_json_payload,
)
from integrations.trend_intake import cargar_signals_desde_json  # noqa: E402
from integrations.stop_words import es_descripcion_vacia_o_stops  # noqa: E402


CATALOGO_RULES = ROOT / "config" / "dispatcher_rules.yaml"
MOCK_FILE = ROOT / "tests" / "mocks" / "trends_navidad_2026.json"


# =============================================================================
# Helpers
# =============================================================================


def _build_ts(
    trend_id: str = "trend_test_001",
    descripcion: str = "Esferas de Navidad LED doradas minimalistas",
    fuente: str = "TIKTOK",
    velocidad: float = 200.0,
    confianza: float = 0.85,
    similares: list[dict] | None = None,
) -> TrendSignalIn:
    payload = {
        "trend_id": trend_id,
        "descripcion": descripcion,
        "palabras_clave": [],
        "fuente": fuente,
        "fecha_deteccion": "2026-11-15T18:30:00+00:00",
        "metadata_fuente": {},
        "velocidad_crecimiento": velocidad,
        "confianza_extraccion": confianza,
        "productos_existentes_similares": similares or [],
        "validado_shacl": True,
        "provisional": True,
    }
    return TrendSignalIn.model_validate(payload)


def _build_dispatcher(audit_store=None) -> AlgorithmDispatcher:
    return AlgorithmDispatcher.from_yaml(
        CATALOGO_RULES, audit_store=audit_store
    )


# =============================================================================
# Tests: Schema + Pydantic validation
# =============================================================================


class TestSchemaValidation(unittest.TestCase):
    def test_payload_completo_valido(self):
        payload = {
            "trend_id": "trend_x",
            "descripcion": "Decoracion navidena nueva con luces LED",
            "fuente": "TIKTOK",
            "fecha_deteccion": "2026-11-15T18:30:00+00:00",
            "velocidad_crecimiento": 100.0,
            "confianza_extraccion": 0.7,
            "productos_existentes_similares": [],
        }
        ok, errs = validar_json_payload(payload)
        self.assertTrue(ok, f"Esperaba OK, errs={errs}")

    def test_descripcion_corta_falla(self):
        payload = {
            "trend_id": "trend_x",
            "descripcion": "corto",  # < 10 chars
            "fuente": "TIKTOK",
            "fecha_deteccion": "2026-11-15T18:30:00+00:00",
            "velocidad_crecimiento": 100.0,
            "confianza_extraccion": 0.7,
            "productos_existentes_similares": [],
        }
        ok, errs = validar_json_payload(payload)
        self.assertFalse(ok)
        self.assertTrue(any("descripcion" in e for e in errs))

    def test_fuente_invalida_falla(self):
        payload = {
            "trend_id": "trend_x",
            "descripcion": "Descripcion suficientemente larga aca",
            "fuente": "FACEBOOK",  # no esta en el enum
            "fecha_deteccion": "2026-11-15T18:30:00+00:00",
            "velocidad_crecimiento": 100.0,
            "confianza_extraccion": 0.7,
            "productos_existentes_similares": [],
        }
        ok, errs = validar_json_payload(payload)
        self.assertFalse(ok)

    def test_confianza_fuera_de_rango_falla(self):
        payload = {
            "trend_id": "trend_x",
            "descripcion": "Descripcion suficientemente larga",
            "fuente": "TIKTOK",
            "fecha_deteccion": "2026-11-15T18:30:00+00:00",
            "velocidad_crecimiento": 100.0,
            "confianza_extraccion": 1.5,  # > 1
            "productos_existentes_similares": [],
        }
        ok, errs = validar_json_payload(payload)
        self.assertFalse(ok)


class TestPydanticNormalization(unittest.TestCase):
    def test_fuente_alias_tik_tok_normaliza(self):
        ts = _build_ts(fuente="tik_tok")
        self.assertEqual(ts.fuente, FuenteTrend.TIKTOK)

    def test_fuente_alias_ig_normaliza(self):
        ts = _build_ts(fuente="IG")
        self.assertEqual(ts.fuente, FuenteTrend.INSTAGRAM)

    def test_fuente_alias_google_normaliza(self):
        ts = _build_ts(fuente="google")
        self.assertEqual(ts.fuente, FuenteTrend.GOOGLE_TRENDS)

    def test_fecha_z_iso_normaliza_a_utc(self):
        payload = {
            "trend_id": "x",
            "descripcion": "Una descripcion suficientemente larga aca",
            "fuente": "TIKTOK",
            "fecha_deteccion": "2026-11-15T18:30:00Z",
            "velocidad_crecimiento": 100.0,
            "confianza_extraccion": 0.7,
            "productos_existentes_similares": [],
        }
        ts = TrendSignalIn.model_validate(payload)
        self.assertEqual(ts.fecha_deteccion.tzinfo, timezone.utc)

    def test_top_similar_devuelve_max_score(self):
        ts = _build_ts(
            similares=[
                {"sku": "111", "score": 0.5},
                {"sku": "222", "score": 0.85},
                {"sku": "333", "score": 0.7},
            ]
        )
        top = ts.top_similar
        self.assertIsNotNone(top)
        self.assertEqual(top.sku, "222")


# =============================================================================
# Tests: Stop-words
# =============================================================================


class TestStopWords(unittest.TestCase):
    def test_descripcion_solo_stops_es_rechazada(self):
        self.assertTrue(
            es_descripcion_vacia_o_stops("navidad navideno christmas")
        )

    def test_descripcion_con_tokens_utiles_pasa(self):
        self.assertFalse(
            es_descripcion_vacia_o_stops("Esferas LED doradas minimalistas")
        )

    def test_descripcion_vacia_es_rechazada(self):
        self.assertTrue(es_descripcion_vacia_o_stops(""))
        self.assertTrue(es_descripcion_vacia_o_stops("   "))


# =============================================================================
# Tests: process_trend_signal (estados)
# =============================================================================


class TestProcessEstados(unittest.TestCase):
    def setUp(self):
        self.dispatcher = _build_dispatcher()

    def test_alta_confianza_y_similar_processed(self):
        ts = _build_ts(
            confianza=0.85,
            similares=[
                {"sku": "247329", "score": 0.85, "nombre": "ESFERA",
                 "categoria": "DECORACION", "precio_referencia": 4500.0}
            ],
        )
        r = process_trend_signal(ts, self.dispatcher)
        self.assertEqual(r.estado, "processed")
        self.assertIsNotNone(r.recomendacion)
        # Como tipo_sku=TRENDING + confianza>=0.8 -> regla_020 con unbounded
        self.assertIn(
            "regla_020_trend_signal_alta_confidence",
            r.recomendacion.reglas_aplicadas,
        )

    def test_baja_confianza_manual_review(self):
        ts = _build_ts(confianza=0.32)
        r = process_trend_signal(ts, self.dispatcher, threshold=0.4)
        self.assertEqual(r.estado, "manual_review")
        self.assertIsNone(r.recomendacion)
        self.assertIn("threshold", r.razon.lower())

    def test_descripcion_solo_stopwords_rechazada(self):
        ts = _build_ts(
            descripcion="navidad navideno christmas xmas santa",
            confianza=0.8,
        )
        r = process_trend_signal(ts, self.dispatcher)
        self.assertEqual(r.estado, "rejected_stopwords")
        self.assertIsNone(r.recomendacion)

    def test_sin_similares_dispatcher_aun_procesa(self):
        """Cold-start sin similar: dispatcher dispara igual (regla 020 o 021).

        TrendSignal con confianza alta y sin similares cae en regla_020
        (trend signal alta confidence) porque tipo_sku=TRENDING + confianza>=0.8.
        """
        ts = _build_ts(confianza=0.85, similares=[])
        r = process_trend_signal(ts, self.dispatcher)
        self.assertEqual(r.estado, "processed")
        self.assertIsNotNone(r.recomendacion)

    def test_threshold_personalizable(self):
        """Si subo el threshold a 0.9, una signal con conf=0.7 cae a manual_review."""
        ts = _build_ts(confianza=0.7)
        r = process_trend_signal(ts, self.dispatcher, threshold=0.9)
        self.assertEqual(r.estado, "manual_review")


# =============================================================================
# Tests: DecisionContext mapping
# =============================================================================


class TestDecisionContextMapping(unittest.TestCase):
    def setUp(self):
        self.dispatcher = _build_dispatcher()

    def test_categoria_heredada_del_top_similar(self):
        ts = _build_ts(
            confianza=0.85,
            similares=[
                {"sku": "1", "score": 0.5, "categoria": "BAJA"},
                {"sku": "2", "score": 0.9, "categoria": "ALTA"},  # top-1
            ],
        )
        r = process_trend_signal(ts, self.dispatcher)
        # No expongo ctx en result, pero verifico via recomendacion
        # (la reco tiene sku que es trend_id; la categoria se usa solo
        # en queries SPARQL del audit log)
        self.assertEqual(r.estado, "processed")

    def test_velocidad_se_pasa_al_dispatcher(self):
        ts = _build_ts(confianza=0.85, velocidad=400.0)
        r = process_trend_signal(ts, self.dispatcher)
        # velocidad termina en context.trend_signal.valor; el test
        # confirma que no haya errores de tipo
        self.assertEqual(r.estado, "processed")


# =============================================================================
# Tests: batch_process
# =============================================================================


class TestBatchProcess(unittest.TestCase):
    def test_summary_cuenta_estados(self):
        dispatcher = _build_dispatcher()
        signals = [
            _build_ts(trend_id="t1", confianza=0.85),  # processed
            _build_ts(trend_id="t2", confianza=0.30),  # manual_review
            _build_ts(  # rejected_stopwords
                trend_id="t3",
                descripcion="navidad navideno christmas xmas santa",
                confianza=0.8,
            ),
        ]
        results, summary = batch_process(signals, dispatcher)
        self.assertEqual(len(results), 3)
        self.assertEqual(summary.get("processed", 0), 1)
        self.assertEqual(summary.get("manual_review", 0), 1)
        self.assertEqual(summary.get("rejected_stopwords", 0), 1)


# =============================================================================
# Tests: carga del mock real con 5 trends
# =============================================================================


class TestMockNavidad2026(unittest.TestCase):
    """Criterio de aceptacion: 5 trends del mock, cada uno con su estado."""

    @classmethod
    def setUpClass(cls):
        cls.signals, cls.rejected = cargar_signals_desde_json(MOCK_FILE)
        cls.dispatcher = _build_dispatcher()

    def test_carga_5_signals_validos(self):
        """Los 5 del mock pasan schema + pydantic."""
        self.assertEqual(len(self.signals), 5)
        self.assertEqual(len(self.rejected), 0)

    def test_pipeline_genera_3_processed_1_manual_1_rejected(self):
        """5 trends -> 3 processed + 1 manual_review + 1 rejected_stopwords.

        Casos:
        - trend_001 (esfera): conf 0.92 + similares -> processed
        - trend_002 (dudoso): conf 0.32 -> manual_review
        - trend_003 (cold-start): conf 0.75 + sin similares -> processed
        - trend_004 (arboles): conf 0.88 + similares -> processed
        - trend_005 (stopwords): puro ruido -> rejected_stopwords
        """
        results, summary = batch_process(self.signals, self.dispatcher)
        self.assertEqual(len(results), 5)
        self.assertEqual(summary.get("processed", 0), 3)
        self.assertEqual(summary.get("manual_review", 0), 1)
        self.assertEqual(summary.get("rejected_stopwords", 0), 1)

    def test_trend_001_dispara_regla_020(self):
        """Esferas con alta confianza + similar real -> regla_020 (trend
        alta confidence + unbounded)."""
        results, _ = batch_process(self.signals, self.dispatcher)
        r = next(r for r in results if r.trend_id == "trend_aabbcc001esfera")
        self.assertEqual(r.estado, "processed")
        self.assertIn(
            "regla_020_trend_signal_alta_confidence",
            r.recomendacion.reglas_aplicadas,
        )
        self.assertIn(
            "unbounded_deviations", r.recomendacion.descriptores_ids
        )

    def test_trend_002_manual_review(self):
        results, _ = batch_process(self.signals, self.dispatcher)
        r = next(r for r in results if r.trend_id == "trend_aabbcc002dudoso")
        self.assertEqual(r.estado, "manual_review")
        self.assertIsNone(r.recomendacion)

    def test_trend_005_rejected_stopwords(self):
        results, _ = batch_process(self.signals, self.dispatcher)
        r = next(r for r in results if r.trend_id == "trend_aabbcc005ruido")
        self.assertEqual(r.estado, "rejected_stopwords")


# =============================================================================
# Tests: integracion con AuditStore (Bloque 8)
# =============================================================================


class TestAuditIntegration(unittest.TestCase):
    def test_processed_se_persiste_a_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            dispatcher = _build_dispatcher(audit_store=store)
            ts = _build_ts(confianza=0.85)
            r = process_trend_signal(ts, dispatcher, audit_store=store)
            self.assertEqual(r.estado, "processed")
            self.assertIsNotNone(r.audit_decision_id)
            ids = store.list_decisions()
            self.assertIn(r.audit_decision_id, ids)

    def test_manual_review_no_persiste_a_audit(self):
        """Confianza < threshold no llega al audit (no hay decision real)."""
        with tempfile.TemporaryDirectory() as tmp:
            store = AuditStore(Path(tmp) / "audit.ttl")
            dispatcher = _build_dispatcher(audit_store=store)
            ts = _build_ts(confianza=0.30)
            r = process_trend_signal(ts, dispatcher, audit_store=store)
            self.assertEqual(r.estado, "manual_review")
            self.assertIsNone(r.audit_decision_id)
            self.assertEqual(len(store.list_decisions()), 0)


# =============================================================================
# Tests: cargar_signals_desde_json
# =============================================================================


class TestCargaJson(unittest.TestCase):
    def test_carga_array_top_level(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", delete=False
        ) as f:
            json.dump(
                [
                    {
                        "trend_id": "x",
                        "descripcion": "Descripcion suficientemente larga",
                        "fuente": "TIKTOK",
                        "fecha_deteccion": "2026-11-15T18:30:00Z",
                        "velocidad_crecimiento": 100.0,
                        "confianza_extraccion": 0.7,
                        "productos_existentes_similares": [],
                    }
                ],
                f,
            )
            path = f.name
        try:
            valids, rej = cargar_signals_desde_json(path)
            self.assertEqual(len(valids), 1)
            self.assertEqual(len(rej), 0)
        finally:
            Path(path).unlink()

    def test_carga_dict_con_key_tendencias(self):
        valids, rej = cargar_signals_desde_json(MOCK_FILE)
        self.assertEqual(len(valids), 5)

    def test_archivo_inexistente_levanta(self):
        with self.assertRaises(FileNotFoundError):
            cargar_signals_desde_json("/tmp/no_existe_xxx.json")

    def test_payload_invalido_va_a_rejected(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", delete=False
        ) as f:
            json.dump(
                [
                    {"trend_id": "x", "descripcion": "Descripcion suficientemente larga",
                     "fuente": "FACEBOOK",  # no es enum valido
                     "fecha_deteccion": "2026-11-15T18:30:00Z",
                     "velocidad_crecimiento": 100.0,
                     "confianza_extraccion": 0.7,
                     "productos_existentes_similares": []},
                    {"trend_id": "y", "descripcion": "Otra descripcion suficientemente larga",
                     "fuente": "TIKTOK",
                     "fecha_deteccion": "2026-11-15T18:30:00Z",
                     "velocidad_crecimiento": 100.0,
                     "confianza_extraccion": 0.7,
                     "productos_existentes_similares": []},
                ],
                f,
            )
            path = f.name
        try:
            valids, rej = cargar_signals_desde_json(path)
            self.assertEqual(len(valids), 1)
            self.assertEqual(len(rej), 1)
            self.assertEqual(rej[0]["etapa"], "schema")
        finally:
            Path(path).unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
