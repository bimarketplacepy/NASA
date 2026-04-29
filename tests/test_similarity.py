"""tests/test_similarity.py - Tests automatizados del motor de similaridad.

Tarea 1 v2 - Bloque 5 - Stage 6.

Cubre los componentes principales del modulo similarity con fixtures
sinteticas + mocks. CI-safe: no requiere Neo4j vivo ni modelo de
embeddings cargado, solo dependencias Python (numpy, pandas, pyyaml).

Modulos cubiertos:

- ``similarity.types``: SimilarityResult validation, BehavioralFlag enum,
  to_dict serialization.
- ``similarity.config``: load_config + StructuralAttribute parsing.
- ``similarity.embeddings``: _normalizar_campo, construir_texto (incluye
  dedup de nombre/nombre_corto), hash_dataset (estabilidad +
  sensibilidad).
- ``similarity.engine``: scorers individuales (lexical, structural,
  behavioral, trend) + composite con renormalizacion de pesos.
- ``similarity.precompute_top_k``: matrices lexica/estructural/composite,
  extract_top_k_edges, dedupe_pairs.
- ``client_v2``: OntologyClientV2._to_v1_sku helper.

Ejecutar:

    python -m unittest tests.test_similarity -v
"""

from __future__ import annotations

import unittest

import numpy as np

from ontology_semantic.similarity import (
    BehavioralFlag,
    SimilarityConfig,
    SimilarityEngine,
    SimilarityResult,
    load_config,
)
from ontology_semantic.similarity.config import StructuralAttribute
from ontology_semantic.similarity.embeddings import (
    _normalizar_campo,
    construir_texto,
    hash_dataset,
)
from ontology_semantic.similarity.precompute_top_k import (
    compute_composite_matrix,
    compute_lexical_matrix,
    compute_structural_matrix,
    dedupe_pairs,
    extract_top_k_edges,
)
from ontology_semantic.client_v2 import OntologyClientV2, QUERY_TEXT_SKU


# ============================================================================
# Helpers de fixtures.
# ============================================================================

def make_fake_cfg(
    behavioral_available: bool = False,
    trend_available: bool = False,
    embedding_dim: int = 4,
) -> SimilarityConfig:
    """Construye un SimilarityConfig minimo y reproducible para tests."""
    return SimilarityConfig(
        weights={"lexical": 0.5, "structural": 0.3,
                 "behavioral": 0.1, "trend": 0.1},
        threshold_default=0.6,
        top_k_default=10,
        embedding_model_name="paraphrase-multilingual-MiniLM-L12-v2",
        embedding_dim=embedding_dim,
        text_template="{nombre}. {nombre_corto}. {categoria}.",
        structural_attributes=(
            StructuralAttribute("pais_origen", "categorical", 1.0),
            StructuralAttribute("perecedero", "boolean", 1.0),
            StructuralAttribute("unidad", "categorical", 0.5),
            StructuralAttribute("categoria_id", "categorical", 1.5),
            StructuralAttribute("grupo_id", "categorical", 1.0),
        ),
        behavioral_available=behavioral_available,
        trend_available=trend_available,
    )


def make_unitary_embeddings() -> np.ndarray:
    """Devuelve 3 embeddings unitarios sinteticos con cosenos conocidos.

    cos(0,1) = 0.6, cos(0,2) = 0.0, cos(1,2) = 0.8.
    """
    embs = np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.6, 0.8, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ], dtype=np.float32)
    for i in range(embs.shape[0]):
        embs[i] /= np.linalg.norm(embs[i])
    return embs


# ============================================================================
# 1. SimilarityResult / BehavioralFlag.
# ============================================================================

class TestSimilarityResult(unittest.TestCase):
    """Validacion de la dataclass SimilarityResult y to_dict()."""

    def _make(self, **overrides) -> SimilarityResult:
        defaults = dict(
            sku_a="A", sku_b="B",
            score_lexical=0.8, score_structural=0.6,
            score_behavioral=0.0, score_trend=0.0,
            score_total=0.7, confidence=0.8,
        )
        defaults.update(overrides)
        return SimilarityResult(**defaults)

    def test_construye_valido(self):
        r = self._make()
        self.assertEqual(r.sku_a, "A")
        self.assertEqual(r.sku_b, "B")
        self.assertEqual(
            r.behavioral_flag, BehavioralFlag.UNAVAILABLE_GLOBAL,
        )

    def test_rechaza_score_fuera_de_rango(self):
        with self.assertRaises(ValueError):
            self._make(score_lexical=1.5)
        with self.assertRaises(ValueError):
            self._make(score_total=-0.1)

    def test_to_dict_serializa_enum_y_tupla(self):
        r = self._make(
            behavioral_flag=BehavioralFlag.UNAVAILABLE_GLOBAL,
            flags=("trend_no_signal", "test"),
        )
        d = r.to_dict()
        self.assertEqual(d["behavioral_flag"], "unavailable_global")
        self.assertEqual(d["flags"], ["trend_no_signal", "test"])
        self.assertEqual(d["score_lex"], 0.8)
        self.assertEqual(d["score_str"], 0.6)


class TestBehavioralFlag(unittest.TestCase):
    """Verifica que el enum tiene los valores esperados (.value es lo que
    se persiste a Neo4j)."""

    def test_valores(self):
        self.assertEqual(BehavioralFlag.AVAILABLE.value, "available")
        self.assertEqual(BehavioralFlag.MISSING_BOTH.value, "missing_both")
        self.assertEqual(BehavioralFlag.UNAVAILABLE_GLOBAL.value,
                         "unavailable_global")


# ============================================================================
# 2. Config.
# ============================================================================

class TestLoadConfig(unittest.TestCase):
    """Asegura que el YAML real del proyecto se parsea correctamente."""

    def test_load_real_yaml(self):
        cfg = load_config()
        self.assertEqual(set(cfg.weights.keys()),
                         {"lexical", "structural", "behavioral", "trend"})
        self.assertEqual(cfg.embedding_dim, 384)
        self.assertGreater(len(cfg.structural_attributes), 0)
        # Suma de pesos = 1.0 +/- 0.001
        self.assertAlmostEqual(sum(cfg.weights.values()), 1.0, places=3)


# ============================================================================
# 3. construir_texto + _normalizar_campo + hash_dataset.
# ============================================================================

class TestNormalizarCampo(unittest.TestCase):

    def test_none(self):
        self.assertEqual(_normalizar_campo(None), "")

    def test_empty(self):
        self.assertEqual(_normalizar_campo(""), "")

    def test_strip_trailing_dots(self):
        self.assertEqual(_normalizar_campo("BOLSA NAV."), "BOLSA NAV")
        self.assertEqual(_normalizar_campo("BOLSA NAV..."), "BOLSA NAV")

    def test_no_modifica_dots_internos(self):
        self.assertEqual(_normalizar_campo("BOLSA NAV. 8091"),
                         "BOLSA NAV. 8091")


class TestConstruirTexto(unittest.TestCase):
    template = "{nombre}. {nombre_corto}. {categoria}."

    def test_caso_lleno_no_dobles_espacios(self):
        t = construir_texto(self.template, {
            "nombre": "ESFERA DECOR 10X10X10CM",
            "nombre_corto": "Esfera Decorativa",
            "categoria_nombre": "ESFERAS",
            "grupo_nombre": "ADORNOS",
            "pais_origen": "Paraguay",
        })
        self.assertIn("ESFERA DECOR", t)
        self.assertIn("Esfera Decorativa", t)
        self.assertIn("ESFERAS", t)
        self.assertNotIn("  ", t)
        self.assertNotIn("..", t)

    def test_dedup_nombre_corto_identico(self):
        t = construir_texto(self.template, {
            "nombre": "BOLSA NAVIDENA 29570",
            "nombre_corto": "BOLSA NAVIDENA 29570",
            "categoria_nombre": "BAZAR",
        })
        self.assertEqual(t.count("BOLSA NAVIDENA 29570"), 1)

    def test_dedup_nombre_corto_subset(self):
        # nombre_corto es prefijo (con punto) de nombre -> se descarta
        t = construir_texto(self.template, {
            "nombre": "BOLSA P/ REGALO NAV. B01 8091",
            "nombre_corto": "BOLSA P/ REGALO NAV.",
            "categoria_nombre": "BAZAR",
        })
        self.assertEqual(t.count("BOLSA P/ REGALO NAV"), 1)
        self.assertNotIn("..", t)

    def test_promocion_cuando_nombre_es_subset_de_nombre_corto(self):
        t = construir_texto(self.template, {
            "nombre": "BOLSA",
            "nombre_corto": "BOLSA NAVIDAD ROJA",
            "categoria_nombre": "BAZAR",
        })
        self.assertIn("BOLSA NAVIDAD ROJA", t)

    def test_nones_no_rompen_template(self):
        t = construir_texto(self.template, {
            "nombre": "X",
            "nombre_corto": None,
            "categoria_nombre": None,
            "grupo_nombre": None,
            "pais_origen": None,
        })
        self.assertNotIn("  ", t)
        self.assertNotIn(". .", t)


class TestHashDataset(unittest.TestCase):

    def test_estable_bajo_reorden(self):
        productos = [{"sku": "1"}, {"sku": "2"}, {"sku": "3"}]
        textos = ["t1", "t2", "t3"]
        h1 = hash_dataset(productos, textos)
        h2 = hash_dataset(list(reversed(productos)), list(reversed(textos)))
        self.assertEqual(h1, h2,
                         "Hash debe ser invariante a reordenamiento")

    def test_sensible_a_cambio_de_texto(self):
        productos = [{"sku": "1"}]
        h1 = hash_dataset(productos, ["a"])
        h2 = hash_dataset(productos, ["b"])
        self.assertNotEqual(h1, h2)

    def test_sensible_a_cambio_de_sku(self):
        h1 = hash_dataset([{"sku": "1"}], ["a"])
        h2 = hash_dataset([{"sku": "2"}], ["a"])
        self.assertNotEqual(h1, h2)


# ============================================================================
# 4. SimilarityEngine: scorers individuales + composite.
# ============================================================================

class TestSimilarityEngineLexical(unittest.TestCase):

    def setUp(self):
        cfg = make_fake_cfg()
        self.eng = SimilarityEngine(
            cfg=cfg,
            embeddings=make_unitary_embeddings(),
            sku_to_row={"A": 0, "B": 1, "C": 2},
        )

    def test_identidad(self):
        self.assertEqual(self.eng.score_lexical("A", "A"), 1.0)

    def test_cosine_conocido(self):
        self.assertAlmostEqual(self.eng.score_lexical("A", "B"), 0.6,
                               places=3)

    def test_ortogonal(self):
        self.assertAlmostEqual(self.eng.score_lexical("A", "C"), 0.0,
                               places=3)

    def test_keyerror_sku_desconocido(self):
        with self.assertRaises(KeyError):
            self.eng.score_lexical("A", "Z")

    def test_runtime_error_sin_embeddings(self):
        cfg = make_fake_cfg()
        eng = SimilarityEngine(cfg=cfg)  # sin embeddings
        with self.assertRaises(RuntimeError):
            eng.score_lexical("A", "B")


class TestSimilarityEngineStructural(unittest.TestCase):

    def setUp(self):
        self.cfg = make_fake_cfg()
        self.attrs = {
            "A": {"pais_origen": "Paraguay", "perecedero": False,
                  "unidad": "Unid", "categoria_id": 100, "grupo_id": 10},
            "B": {"pais_origen": "Paraguay", "perecedero": False,
                  "unidad": "Unid", "categoria_id": 100, "grupo_id": 10},
            "C": {"pais_origen": "China", "perecedero": True,
                  "unidad": "Unid", "categoria_id": 200, "grupo_id": 20},
        }
        self.eng = SimilarityEngine(
            cfg=self.cfg,
            embeddings=make_unitary_embeddings(),
            sku_to_row={"A": 0, "B": 1, "C": 2},
            attrs_by_sku=self.attrs,
        )

    def test_identidad(self):
        self.assertEqual(self.eng.score_structural("A", "A"), 1.0)

    def test_match_total(self):
        self.assertEqual(self.eng.score_structural("A", "B"), 1.0)

    def test_solo_unidad_coincide(self):
        # Pesos: pais=1, perec=1, unidad=0.5, cat=1.5, grupo=1 -> total 5
        # Match (solo unidad): 0.5 / 5 = 0.1
        self.assertAlmostEqual(self.eng.score_structural("A", "C"),
                               0.1, places=3)

    def test_sku_sin_attrs_devuelve_cero(self):
        eng = SimilarityEngine(
            cfg=self.cfg,
            embeddings=make_unitary_embeddings(),
            sku_to_row={"A": 0, "B": 1},
            attrs_by_sku={"A": self.attrs["A"]},  # B sin attrs
        )
        self.assertEqual(eng.score_structural("A", "B"), 0.0)

    def test_attrs_parciales_con_nones(self):
        # Solo categoria coincide, los demas son None en B
        attrs = {
            "A": {"pais_origen": "Paraguay", "perecedero": False,
                  "unidad": "Unid", "categoria_id": 100, "grupo_id": 10},
            "B": {"pais_origen": None, "perecedero": None,
                  "unidad": "", "categoria_id": 100, "grupo_id": None},
        }
        eng = SimilarityEngine(
            cfg=self.cfg,
            embeddings=make_unitary_embeddings(),
            sku_to_row={"A": 0, "B": 1},
            attrs_by_sku=attrs,
        )
        # Solo categoria_id es comparable (peso 1.5) -> match 1.5/1.5 = 1.0
        self.assertEqual(eng.score_structural("A", "B"), 1.0)


class TestSimilarityEngineBehavioral(unittest.TestCase):

    def test_unavailable_global_por_default(self):
        cfg = make_fake_cfg(behavioral_available=False)
        eng = SimilarityEngine(cfg=cfg)
        score, flag = eng.score_behavioral("A", "B")
        self.assertEqual(score, 0.0)
        self.assertEqual(flag, BehavioralFlag.UNAVAILABLE_GLOBAL)

    def test_missing_both_cuando_no_hay_data(self):
        cfg = make_fake_cfg(behavioral_available=True)
        eng = SimilarityEngine(cfg=cfg)
        score, flag = eng.score_behavioral("A", "B")
        self.assertEqual(score, 0.0)
        self.assertEqual(flag, BehavioralFlag.MISSING_BOTH)

    def test_cosine_real_cuando_hay_data(self):
        cfg = make_fake_cfg(behavioral_available=True)
        eng = SimilarityEngine(
            cfg=cfg,
            monthly_sales_by_sku={
                "A": np.array([1.0, 0.0, 0.0]),
                "B": np.array([0.6, 0.8, 0.0]),  # cos = 0.6
            },
        )
        score, flag = eng.score_behavioral("A", "B")
        self.assertAlmostEqual(score, 0.6, places=3)
        self.assertEqual(flag, BehavioralFlag.AVAILABLE)


class TestSimilarityEngineTrend(unittest.TestCase):

    def test_no_signal_devuelve_cero(self):
        cfg = make_fake_cfg()
        eng = SimilarityEngine(cfg=cfg, trend_signal_text="")
        self.assertEqual(eng.score_trend("A"), 0.0)

    def test_score_con_embed_fn_inyectada(self):
        cfg = make_fake_cfg()
        # Usamos un embed_fn fake que devuelve un vector unitario fijo.
        # asi el score es producto punto con embedding[0].
        fake_trend = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        eng = SimilarityEngine(
            cfg=cfg,
            embeddings=make_unitary_embeddings(),
            sku_to_row={"A": 0, "B": 1, "C": 2},
            trend_signal_text="fake trend",
            embed_fn=lambda _: fake_trend,
        )
        # SKU A es [1, 0, 0, 0], dot con [1, 0, 0, 0] = 1.0
        self.assertAlmostEqual(eng.score_trend("A"), 1.0, places=3)
        # SKU C tiene 0 en la primera dim -> dot = 0
        self.assertAlmostEqual(eng.score_trend("C"), 0.0, places=3)


class TestSimilarityEngineComposite(unittest.TestCase):

    def setUp(self):
        cfg = make_fake_cfg()
        self.attrs = {
            "A": {"pais_origen": "Paraguay", "perecedero": False,
                  "unidad": "Unid", "categoria_id": 100, "grupo_id": 10},
            "B": {"pais_origen": "Paraguay", "perecedero": False,
                  "unidad": "Unid", "categoria_id": 100, "grupo_id": 10},
        }
        self.eng = SimilarityEngine(
            cfg=cfg,
            embeddings=make_unitary_embeddings(),
            sku_to_row={"A": 0, "B": 1, "C": 2},
            attrs_by_sku=self.attrs,
        )

    def test_renormalizacion_correcta(self):
        # lex(A,B) = 0.6, str(A,B) = 1.0, beh = 0.0 missing, trd = 0.0 missing
        # confidence = w_lex + w_str = 0.5 + 0.3 = 0.8
        # eff_lex = 0.5/0.8 = 0.625, eff_str = 0.3/0.8 = 0.375
        # total = 0.625 * 0.6 + 0.375 * 1.0 = 0.375 + 0.375 = 0.75
        r = self.eng.composite_score("A", "B")
        self.assertAlmostEqual(r.score_total, 0.75, places=3)
        self.assertAlmostEqual(r.confidence, 0.8, places=3)
        self.assertEqual(r.behavioral_flag, BehavioralFlag.UNAVAILABLE_GLOBAL)
        self.assertIn("behavioral_unavailable_global", r.flags)
        self.assertIn("trend_no_signal", r.flags)

    def test_identidad(self):
        r = self.eng.composite_score("A", "A")
        self.assertEqual(r.score_total, 1.0)
        self.assertEqual(r.confidence, 1.0)
        self.assertIn("identity", r.flags)

    def test_weights_override_invalido(self):
        with self.assertRaises(ValueError):
            self.eng.composite_score("A", "B",
                                     weights_override={"inventado": 1.0})


# ============================================================================
# 5. Matrices y top-K.
# ============================================================================

class TestMatrices(unittest.TestCase):

    def test_lexical_matrix_simetrica_y_diagonal_unitaria(self):
        embs = make_unitary_embeddings()
        mat = compute_lexical_matrix(embs)
        np.testing.assert_allclose(np.diag(mat), 1.0, atol=1e-5)
        np.testing.assert_allclose(mat, mat.T, atol=1e-5)

    def test_structural_matrix_simetrica(self):
        cfg = make_fake_cfg()
        productos = [
            {"sku": "A", "row": 0, "texto": "...",
             "attrs": {"pais_origen": "Paraguay", "perecedero": False,
                       "unidad": "Unid", "categoria_id": 100, "grupo_id": 10}},
            {"sku": "B", "row": 1, "texto": "...",
             "attrs": {"pais_origen": "Paraguay", "perecedero": False,
                       "unidad": "Unid", "categoria_id": 100, "grupo_id": 10}},
            {"sku": "C", "row": 2, "texto": "...",
             "attrs": {"pais_origen": "China", "perecedero": True,
                       "unidad": "Unid", "categoria_id": 200, "grupo_id": 20}},
        ]
        mat = compute_structural_matrix(productos, cfg)
        np.testing.assert_allclose(mat, mat.T, atol=1e-5)
        np.testing.assert_allclose(np.diag(mat), 1.0, atol=1e-5)

    def test_composite_matrix_renormaliza(self):
        cfg = make_fake_cfg()
        # Toda la matriz lex es 0.5, toda struct es 1.0
        lex = np.full((3, 3), 0.5, dtype=np.float32)
        struct = np.full((3, 3), 1.0, dtype=np.float32)
        composite, conf = compute_composite_matrix(lex, struct, cfg)
        # confidence = 0.8, eff_lex=0.625, eff_str=0.375
        # composite = 0.625 * 0.5 + 0.375 * 1.0 = 0.6875
        self.assertAlmostEqual(conf, 0.8, places=3)
        np.testing.assert_allclose(composite, 0.6875, atol=1e-3)


class TestExtractTopK(unittest.TestCase):

    def test_extrae_k_correctos(self):
        # 3 SKUs, top-2 cada uno = 6 dirigidas
        composite = np.array([
            [1.0, 0.9, 0.1],
            [0.9, 1.0, 0.5],
            [0.1, 0.5, 1.0],
        ], dtype=np.float32)
        edges = extract_top_k_edges(
            composite=composite, lex=composite, struct=composite,
            skus=["A", "B", "C"], confidence=0.8, k=2,
        )
        self.assertEqual(len(edges), 6)

    def test_threshold_filtra(self):
        composite = np.array([
            [1.0, 0.9, 0.1],
            [0.9, 1.0, 0.5],
            [0.1, 0.5, 1.0],
        ], dtype=np.float32)
        edges = extract_top_k_edges(
            composite=composite, lex=composite, struct=composite,
            skus=["A", "B", "C"], confidence=0.8, k=2, threshold=0.7,
        )
        # Solo (A,B) y (B,A) >= 0.7
        self.assertEqual(len(edges), 2)
        for e in edges:
            self.assertGreaterEqual(e["score_total"], 0.7)


class TestDedupePairs(unittest.TestCase):

    def test_colapsa_simetricos(self):
        edges = [
            {"sku_a": "A", "sku_b": "B", "score_lex": 0.8,
             "score_str": 1.0, "score_total": 0.85, "confidence": 0.8},
            {"sku_a": "B", "sku_b": "A", "score_lex": 0.8,
             "score_str": 1.0, "score_total": 0.85, "confidence": 0.8},
        ]
        d = dedupe_pairs(edges)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["sku_a"], "A")
        self.assertEqual(d[0]["sku_b"], "B")

    def test_descarta_self_loops(self):
        edges = [
            {"sku_a": "A", "sku_b": "A", "score_lex": 1.0,
             "score_str": 1.0, "score_total": 1.0, "confidence": 0.8},
        ]
        self.assertEqual(dedupe_pairs(edges), [])

    def test_orden_lexicografico(self):
        edges = [
            {"sku_a": "Z", "sku_b": "A", "score_lex": 0.5,
             "score_str": 0.5, "score_total": 0.5, "confidence": 0.8},
        ]
        d = dedupe_pairs(edges)
        self.assertEqual(d[0]["sku_a"], "A")
        self.assertEqual(d[0]["sku_b"], "Z")


# ============================================================================
# 6. OntologyClientV2 helpers.
# ============================================================================

class TestOntologyClientV2Helpers(unittest.TestCase):

    def test_to_v1_sku_string_numerico(self):
        self.assertEqual(OntologyClientV2._to_v1_sku("17629"), 17629)
        self.assertIsInstance(OntologyClientV2._to_v1_sku("17629"), int)

    def test_to_v1_sku_int(self):
        self.assertEqual(OntologyClientV2._to_v1_sku(17629), 17629)

    def test_to_v1_sku_alfanumerico_se_preserva(self):
        self.assertEqual(OntologyClientV2._to_v1_sku("ABC123"), "ABC123")

    def test_to_v1_sku_con_guiones(self):
        # SKU futuro con dashes (la TBox declara xsd:string + pattern
        # alfanumerico) debe quedar como string.
        self.assertEqual(OntologyClientV2._to_v1_sku("A-B"), "A-B")

    def test_query_text_sku_constant(self):
        # Sentinel para resultados de productos_similares_a_descripcion.
        self.assertEqual(QUERY_TEXT_SKU, "<text-query>")


if __name__ == "__main__":
    unittest.main()
