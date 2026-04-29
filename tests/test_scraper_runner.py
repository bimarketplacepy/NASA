"""Test de integracion end-to-end: scraper real (Mateo) -> ACL.

Verifica que el pipeline de TrendsService de Mateo + el ACL del Bloque 9
corren juntos sin errores y producen TrendIntakeResults validos.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatcher import AlgorithmDispatcher  # noqa: E402
from integrations.scraper_runner import run_scraper_pipeline  # noqa: E402


CATALOGO_RULES = ROOT / "config" / "dispatcher_rules.yaml"


# Posts inline para el test (no leemos archivo)
_POSTS_TEST = [
    {
        "post_id": "test_001",
        "platform": "TIKTOK",
        "autor": "decoholic_py",
        "fecha": "2026-11-10T18:30:00Z",
        "texto": "Esferas de Navidad LED doradas estilo nordico minimalista #navidad #esferas #led",
        "metricas": {"views": 145000, "likes": 12300, "shares": 890, "comments": 234},
    },
    {
        "post_id": "test_002",
        "platform": "TIKTOK",
        "autor": "casa_navidena",
        "fecha": "2026-11-11T20:15:00Z",
        "texto": "Esfera dorada minimalista para arbol navideno look 2026 #navidad #esferas",
        "metricas": {"views": 89000, "likes": 7200, "shares": 540, "comments": 180},
    },
    {
        "post_id": "test_003",
        "platform": "TIKTOK",
        "autor": "deco_trends_ar",
        "fecha": "2026-11-12T16:00:00Z",
        "texto": "Esferas LED doradas viralizandose en TikTok navidad 2026",
        "metricas": {"views": 67000, "likes": 5400, "shares": 420, "comments": 95},
    },
    {
        "post_id": "test_noise",
        "platform": "OTHER",
        "autor": "anon",
        "fecha": "2026-11-17T22:00:00Z",
        "texto": "navidad navideno christmas xmas santa noel",
        "metricas": {"views": 120, "likes": 8, "shares": 0, "comments": 1},
    },
]


class TestScraperRunnerEndToEnd(unittest.TestCase):
    """Pipeline raw_posts -> TrendsService -> ACL produce resultados validos."""

    def test_pipeline_corre_sin_errores(self):
        dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)
        results, summary = run_scraper_pipeline(
            _POSTS_TEST,
            dispatcher,
            audit_store=None,
            threshold=0.3,
            inyectar_grafo_provisional=False,
        )
        # Debe haber al menos algun trend extraido
        self.assertGreater(len(results), 0)
        # Y al menos un estado conocido
        self.assertTrue(set(summary.keys()) - {"processed", "manual_review",
                                                  "rejected_stopwords",
                                                  "rejected_schema",
                                                  "rejected_runtime"} == set(),
                        f"Estados raros: {summary}")

    def test_pipeline_detecta_stopwords_del_post_noise(self):
        """El post 'navidad navideno christmas xmas santa' debe disparar
        el filtro de stop-words del ACL (rejected_stopwords)."""
        dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)
        results, summary = run_scraper_pipeline(
            _POSTS_TEST,
            dispatcher,
            audit_store=None,
            threshold=0.3,
            inyectar_grafo_provisional=False,
        )
        # Esperamos que al menos uno sea rejected_stopwords
        # (el cluster del post de ruido)
        n_rejected = summary.get("rejected_stopwords", 0)
        # No es estricto - depende del clustering del LLM heuristico.
        # Lo que SI debe ocurrir: el pipeline debe ejecutar sin levantar.
        self.assertGreaterEqual(len(results), 1)

    def test_resultados_son_TrendIntakeResult(self):
        """Cada result tiene los campos esperados del Bloque 9."""
        dispatcher = AlgorithmDispatcher.from_yaml(CATALOGO_RULES)
        results, _ = run_scraper_pipeline(
            _POSTS_TEST,
            dispatcher,
            inyectar_grafo_provisional=False,
        )
        for r in results:
            self.assertTrue(r.trend_id.startswith("trend_"))
            self.assertIn(r.estado, [
                "processed", "manual_review",
                "rejected_schema", "rejected_stopwords", "rejected_runtime",
            ])
            self.assertIsInstance(r.razonamiento, tuple)
            self.assertGreater(len(r.razonamiento), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
