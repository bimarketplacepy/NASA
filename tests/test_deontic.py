"""Tests del modulo deontic (Bloque 6).

Cubre:
    - Caso simple: decision sin normas violadas -> permitida.
    - Conflicto O vs F sobre mismo target: F gana por prioridad.
    - Defeasibility: O derrotada por excepcion documentada via :defeats.
    - Vigencia temporal: norma fuera de fecha NO aplica.
    - Decision sin normas aplicables -> permitida con razonamiento.
    - Registry pattern de predicados (no eval, sandbox).
    - Parsing del TTL (estructura + counts + targets).
    - UnresolvedDeonticConflict cuando hay empate sin :defeats.
    - Audit trail JSONL append-only.

NO requiere Neo4j corriendo. Las normas se parametrizan inline o
se cargan desde el catalogo real (ontology_semantic/normas_marketplace.ttl).
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

# Importar deontic gatilla el side-effect de registrar predicados de marketplace.
import deontic  # noqa: F401  pylint: disable=unused-import
from deontic import (  # noqa: E402
    DeonticResolver,
    EvaluacionDeontica,
    Modality,
    NormaInvalida,
    Norm,
    Obligation,
    Permission,
    Prohibition,
    UnresolvedDeonticConflict,
    list_predicates,
    register_predicate,
)
from deontic.predicates import _REGISTRY  # noqa: E402  (test interno)


CATALOGO_TTL = ROOT / "ontology_semantic" / "normas_marketplace.ttl"


# =============================================================================
# Helpers para construir resolvers con normas inline (sin tocar el catalogo)
# =============================================================================


def _now_pico() -> datetime:
    """Instante dentro de la temporada pico (vigencia P6)."""
    return datetime(2026, 12, 15, 10, 0, 0, tzinfo=timezone.utc)


def _now_no_pico() -> datetime:
    """Instante fuera de la temporada pico (P6 no vigente)."""
    return datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)


def _registrar_si_falta(name: str, fn) -> None:
    """Registra un predicado solo si no existe (idempotente para tests)."""
    if name in _REGISTRY:
        return
    register_predicate(name)(fn)


# Predicados sinteticos para tests inline (registrados una sola vez)

def _pred_siempre_aplica(decision, contexto):
    return True


def _pred_nunca_aplica(decision, contexto):
    return False


def _pred_aplica_si_flag(decision, contexto):
    return bool(decision.get("flag"))


_registrar_si_falta("__test_siempre", _pred_siempre_aplica)
_registrar_si_falta("__test_nunca", _pred_nunca_aplica)
_registrar_si_falta("__test_flag", _pred_aplica_si_flag)


# =============================================================================
# Tests sobre normas SINTETICAS (independientes del catalogo)
# =============================================================================


class TestCasoSimplePermitido(unittest.TestCase):
    """Caso simple: ninguna norma aplica -> permitida."""

    def test_decision_sin_normas_aplicables(self):
        normas = [
            Prohibition(
                norm_id="F_test_nunca",
                applies_when="__test_nunca",
                target="x",
                priority=50,
            ),
        ]
        resolver = DeonticResolver(normas)
        ev = resolver.evaluar({"tipo": "compra"}, {})
        self.assertTrue(ev.permitida)
        self.assertEqual(ev.bloqueada_por, ())
        self.assertEqual(ev.obligaciones_pendientes, ())
        self.assertEqual(ev.normas_aplicadas, ())
        # razonamiento debe mencionar que la decision es libre
        rz = " ".join(ev.razonamiento)
        self.assertIn("sin normas aplicables", rz)
        self.assertIn("libre", rz)

    def test_catalogo_real_decision_inocua(self):
        """Una compra normal de no-perecedero no dispara nada del catalogo real."""
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        decision = {
            "tipo": "compra",
            "monto_usd": 100.0,
            "lead_time_dias": 7.0,
            "aprobacion_supervisor": True,
            "cantidad": 10.0,
            "descuento_volumen_pct": 0.0,
            "exceso_budget_pct": 0.0,
            "validacion_humana": False,
            "justificacion_escrita": False,
            "aprobacion_excepcion": False,
        }
        contexto = {
            "now": _now_no_pico(),
            "perecedero": False,
            "sku_critico": False,
            "sku_piloto": False,
            "cold_start": False,
            "proveedor_activo": True,
            "proveedor_exterior": False,
            "proveedores_disponibles": 3,
        }
        ev = resolver.evaluar(decision, contexto)
        self.assertTrue(ev.permitida, f"Esperaba permitida, ev={ev}")
        self.assertEqual(ev.bloqueada_por, ())
        self.assertEqual(ev.obligaciones_pendientes, ())


class TestConflictoOFGanaPrioridad(unittest.TestCase):
    """Conflicto O vs F sobre mismo target: la de mayor prioridad gana."""

    def test_F_de_mayor_prioridad_derrota_a_O(self):
        normas = [
            Obligation(
                norm_id="O_baja",
                applies_when="__test_siempre",
                target="acto_X",
                priority=30,
                defeasible=True,
            ),
            Prohibition(
                norm_id="F_alta",
                applies_when="__test_siempre",
                target="acto_X",
                priority=80,
                defeasible=True,
            ),
        ]
        resolver = DeonticResolver(normas)
        ev = resolver.evaluar({}, {})
        # F sobrevive, O derrotada
        self.assertIn("F_alta", ev.bloqueada_por)
        self.assertNotIn("O_baja", ev.obligaciones_pendientes)
        derrotadas_ids = [nid for nid, _ in ev.normas_derrotadas]
        self.assertIn("O_baja", derrotadas_ids)
        # Veredicto: bloqueada
        self.assertFalse(ev.permitida)

    def test_O_de_mayor_prioridad_derrota_a_F(self):
        normas = [
            Obligation(
                norm_id="O_alta",
                applies_when="__test_siempre",
                target="acto_Y",
                priority=80,
                defeasible=True,
            ),
            Prohibition(
                norm_id="F_baja",
                applies_when="__test_siempre",
                target="acto_Y",
                priority=30,
                defeasible=True,
            ),
        ]
        resolver = DeonticResolver(normas)
        ev = resolver.evaluar({}, {})
        # O sobrevive, F derrotada
        self.assertIn("O_alta", ev.obligaciones_pendientes)
        self.assertEqual(ev.bloqueada_por, ())
        derrotadas_ids = [nid for nid, _ in ev.normas_derrotadas]
        self.assertIn("F_baja", derrotadas_ids)
        # Veredicto: no permitida porque hay obligacion pendiente
        self.assertFalse(ev.permitida)


class TestDefeasibilityExcepcion(unittest.TestCase):
    """O es derrotada por una P explicita via :defeats."""

    def test_P_derrota_O_via_defeats_explicito(self):
        normas = [
            Obligation(
                norm_id="O_general",
                applies_when="__test_siempre",
                target="t1",
                priority=60,
                defeasible=True,
            ),
            Permission(
                norm_id="P_excepcion",
                applies_when="__test_flag",
                target="t1",
                priority=50,  # menor prioridad pero defeats explicito
                defeasible=True,
                defeats=("O_general",),
            ),
        ]
        resolver = DeonticResolver(normas)

        # Sin flag: P no aplica, O queda como obligacion pendiente
        ev1 = resolver.evaluar({"flag": False}, {})
        self.assertFalse(ev1.permitida)
        self.assertIn("O_general", ev1.obligaciones_pendientes)
        self.assertEqual(ev1.normas_derrotadas, ())

        # Con flag: P aplica, derrota O via :defeats explicito
        ev2 = resolver.evaluar({"flag": True}, {})
        self.assertTrue(ev2.permitida, f"Esperaba permitida, ev={ev2}")
        self.assertNotIn("O_general", ev2.obligaciones_pendientes)
        derrotadas_ids = [nid for nid, _ in ev2.normas_derrotadas]
        self.assertIn("O_general", derrotadas_ids)
        # El motivo debe mencionar :defeats
        motivo_o = next(m for nid, m in ev2.normas_derrotadas if nid == "O_general")
        self.assertIn("defeats", motivo_o.lower())

    def test_norma_no_defeasible_no_puede_ser_derrotada(self):
        """Si A defeats B pero B es defeasible=False -> UnresolvedDeonticConflict."""
        normas = [
            Permission(
                norm_id="P_intenta_derrotar",
                applies_when="__test_siempre",
                target="t2",
                priority=99,
                defeats=("F_estricta",),
            ),
            Prohibition(
                norm_id="F_estricta",
                applies_when="__test_siempre",
                target="t2",
                priority=50,
                defeasible=False,  # NO se puede derrotar
            ),
        ]
        resolver = DeonticResolver(normas)
        with self.assertRaises(UnresolvedDeonticConflict) as ctx:
            resolver.evaluar({}, {})
        self.assertIn("F_estricta", str(ctx.exception))
        self.assertIn("defeasible=False", str(ctx.exception))

    def test_catalogo_real_aprobacion_excepcion_libera_compra(self):
        """Caso end-to-end: P5 derrota O4 cuando hay 1 proveedor + aprobacion."""
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        decision = {
            "tipo": "compra",
            "monto_usd": 200.0,
            "lead_time_dias": 5.0,
            "aprobacion_supervisor": True,
            "aprobacion_excepcion": True,  # <- la clave
            "validacion_humana": False,
            "justificacion_escrita": False,
            "exceso_budget_pct": 0.0,
            "cantidad": 5.0,
            "descuento_volumen_pct": 0.0,
        }
        contexto = {
            "now": _now_no_pico(),
            "perecedero": False,
            "sku_critico": True,  # SKU critico
            "sku_piloto": False,
            "cold_start": False,
            "proveedor_activo": True,
            "proveedor_exterior": False,
            "proveedores_disponibles": 1,  # solo 1 -> O4 disparada
        }
        ev = resolver.evaluar(decision, contexto)
        self.assertTrue(
            ev.permitida,
            f"Con aprobacion_excepcion=True, P5 deberia derrotar O4. ev={ev}",
        )
        derrotadas_ids = [nid for nid, _ in ev.normas_derrotadas]
        self.assertIn("O_sku_critico_dos_proveedores", derrotadas_ids)
        self.assertIn(
            "P_compra_sku_critico_unico_proveedor_con_aprobacion",
            ev.normas_aplicadas,
        )

    def test_catalogo_real_sin_aprobacion_O4_bloquea(self):
        """Caso negativo: sin aprobacion, O4 queda como obligacion pendiente."""
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        decision = {
            "tipo": "compra",
            "monto_usd": 200.0,
            "lead_time_dias": 5.0,
            "aprobacion_supervisor": True,
            "aprobacion_excepcion": False,  # <- sin aprobacion
            "validacion_humana": False,
            "justificacion_escrita": False,
            "exceso_budget_pct": 0.0,
            "cantidad": 5.0,
            "descuento_volumen_pct": 0.0,
        }
        contexto = {
            "now": _now_no_pico(),
            "perecedero": False,
            "sku_critico": True,
            "sku_piloto": False,
            "cold_start": False,
            "proveedor_activo": True,
            "proveedor_exterior": False,
            "proveedores_disponibles": 1,
        }
        ev = resolver.evaluar(decision, contexto)
        self.assertFalse(ev.permitida)
        self.assertIn(
            "O_sku_critico_dos_proveedores",
            ev.obligaciones_pendientes,
        )


class TestVigenciaTemporal(unittest.TestCase):
    """Las normas fuera de [validFrom, validUntil] NO aplican."""

    def test_norma_antes_de_validFrom_no_aplica(self):
        normas = [
            Prohibition(
                norm_id="F_futura",
                applies_when="__test_siempre",
                target="t",
                priority=50,
                valid_from=datetime(2030, 1, 1, tzinfo=timezone.utc),
            ),
        ]
        resolver = DeonticResolver(normas)
        ev = resolver.evaluar(
            {},
            {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        )
        self.assertTrue(ev.permitida)
        rz = " ".join(ev.razonamiento)
        self.assertIn("F_futura", rz)
        self.assertIn("fuera de vigencia", rz)

    def test_norma_despues_de_validUntil_no_aplica(self):
        normas = [
            Prohibition(
                norm_id="F_caducada",
                applies_when="__test_siempre",
                target="t",
                priority=50,
                valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                valid_until=datetime(2021, 12, 31, tzinfo=timezone.utc),
            ),
        ]
        resolver = DeonticResolver(normas)
        ev = resolver.evaluar(
            {},
            {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        )
        self.assertTrue(ev.permitida)

    def test_catalogo_real_P6_solo_aplica_en_temporada_pico(self):
        """P6 (excede budget) tiene vigencia 2026-11-15 / 2027-01-15."""
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        decision = {
            "tipo": "compra",
            "monto_usd": 100.0,
            "lead_time_dias": 5.0,
            "exceso_budget_pct": 10.0,
            "aprobacion_supervisor": True,
            "aprobacion_excepcion": False,
            "validacion_humana": False,
            "justificacion_escrita": False,
            "cantidad": 5.0,
            "descuento_volumen_pct": 0.0,
        }
        ctx_base = {
            "perecedero": False,
            "sku_critico": False,
            "sku_piloto": False,
            "cold_start": False,
            "proveedor_activo": True,
            "proveedor_exterior": False,
            "proveedores_disponibles": 3,
        }

        # En pico: P6 vigente y disparada
        ev_pico = resolver.evaluar(decision, {**ctx_base, "now": _now_pico()})
        self.assertIn(
            "P_excede_budget_categoria_15_temporada_pico",
            ev_pico.normas_aplicadas,
        )

        # Fuera de pico: P6 fuera de vigencia
        ev_no_pico = resolver.evaluar(
            decision, {**ctx_base, "now": _now_no_pico()}
        )
        self.assertNotIn(
            "P_excede_budget_categoria_15_temporada_pico",
            ev_no_pico.normas_aplicadas,
        )
        rz = " ".join(ev_no_pico.razonamiento)
        self.assertIn("P_excede_budget_categoria_15_temporada_pico", rz)


class TestProhibicionEstricta(unittest.TestCase):
    """F_compra_perecedero_sin_viabilidad bloquea (no defeasible)."""

    def test_compra_perecedero_lead_time_excesivo_bloquea(self):
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        decision = {
            "tipo": "compra",
            "monto_usd": 200.0,
            "lead_time_dias": 30.0,  # > shelf life
            "aprobacion_supervisor": True,
            "aprobacion_excepcion": False,
            "validacion_humana": False,
            "justificacion_escrita": False,
            "exceso_budget_pct": 0.0,
            "cantidad": 5.0,
            "descuento_volumen_pct": 0.0,
        }
        contexto = {
            "now": _now_no_pico(),
            "perecedero": True,
            "shelf_life_dias": 14.0,  # 30 > 14 -> dispara
            "sku_critico": False,
            "sku_piloto": False,
            "cold_start": False,
            "proveedor_activo": True,
            "proveedor_exterior": False,
            "proveedores_disponibles": 3,
        }
        ev = resolver.evaluar(decision, contexto)
        self.assertFalse(ev.permitida)
        self.assertIn("F_compra_perecedero_sin_viabilidad", ev.bloqueada_por)


class TestConflictoIrresoluble(unittest.TestCase):
    """Empate de prioridad sin :defeats explicito -> raise."""

    def test_empate_levanta_unresolved(self):
        normas = [
            Obligation(
                norm_id="O_x",
                applies_when="__test_siempre",
                target="z",
                priority=50,
                defeasible=True,
            ),
            Prohibition(
                norm_id="F_y",
                applies_when="__test_siempre",
                target="z",
                priority=50,  # mismo priority, sin :defeats
                defeasible=True,
            ),
        ]
        resolver = DeonticResolver(normas)
        with self.assertRaises(UnresolvedDeonticConflict) as ctx:
            resolver.evaluar({}, {})
        self.assertIn("empate", str(ctx.exception).lower())


class TestRegistryYParsingTTL(unittest.TestCase):
    """Smoke: registry pattern + parsing del catalogo real."""

    def test_predicados_marketplace_estan_registrados(self):
        nombres = list_predicates()
        # Los 11 predicados del catalogo
        esperados = {
            "F_compra_perecedero_sin_viabilidad",
            "F_compra_grande_sin_aprobacion_presupuesto_bajo",
            "F_compra_a_proveedor_desactivado",
            "F_importacion_sin_lead_time_para_evento",
            "O_sku_critico_dos_proveedores",
            "P_compra_sku_critico_unico_proveedor_con_aprobacion",
            "O_validacion_humana_coldstart_low_conf",
            "P_excede_budget_categoria_15_temporada_pico",
            "P_compra_supera_moq_con_descuento_volumen",
            "O_justificacion_proveedor_exterior_nuevo",
            "P_relajar_stock_minimo_sku_piloto",
        }
        faltantes = esperados - set(nombres)
        self.assertFalse(
            faltantes, f"Faltan predicados registrados: {faltantes}"
        )

    def test_catalogo_carga_11_normas(self):
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        self.assertEqual(len(resolver.normas), 11)

    def test_catalogo_balance_modalidades(self):
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        modalidades = [n.modality for n in resolver.normas]
        self.assertEqual(modalidades.count(Modality.PROHIBITION), 4)
        self.assertEqual(modalidades.count(Modality.OBLIGATION), 3)
        self.assertEqual(modalidades.count(Modality.PERMISSION), 4)

    def test_catalogo_par_defeats(self):
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        p5 = next(
            n
            for n in resolver.normas
            if n.norm_id == "P_compra_sku_critico_unico_proveedor_con_aprobacion"
        )
        self.assertIn("O_sku_critico_dos_proveedores", p5.defeats)

    def test_normas_son_inmutables(self):
        resolver = DeonticResolver.from_ttl(CATALOGO_TTL)
        n = resolver.normas[0]
        with self.assertRaises(Exception):
            n.priority = 0  # type: ignore[misc]


class TestValidacionPreFlight(unittest.TestCase):
    """El resolver detecta errores en construccion, no en runtime."""

    def test_norm_id_duplicado_levanta(self):
        normas = [
            Prohibition(
                norm_id="dup", applies_when="__test_siempre",
                target="t", priority=50,
            ),
            Prohibition(
                norm_id="dup", applies_when="__test_siempre",
                target="t", priority=60,
            ),
        ]
        with self.assertRaises(NormaInvalida) as ctx:
            DeonticResolver(normas)
        self.assertIn("duplicados", str(ctx.exception))

    def test_defeats_a_norma_inexistente_levanta(self):
        normas = [
            Permission(
                norm_id="P", applies_when="__test_siempre",
                target="t", priority=50, defeats=("inexistente",),
            ),
        ]
        with self.assertRaises(NormaInvalida) as ctx:
            DeonticResolver(normas)
        self.assertIn("inexistente", str(ctx.exception))

    def test_predicado_no_registrado_levanta(self):
        normas = [
            Permission(
                norm_id="P_x", applies_when="predicado_que_no_existe",
                target="t", priority=50,
            ),
        ]
        with self.assertRaises(NormaInvalida):
            DeonticResolver(normas)

    def test_priority_fuera_de_rango_levanta_en_construccion_norm(self):
        with self.assertRaises(NormaInvalida):
            Prohibition(
                norm_id="x", applies_when="__test_siempre",
                target="t", priority=200,
            )


class TestAuditTrail(unittest.TestCase):
    """Cada evaluar() apenda un JSONL al audit_path."""

    def test_audit_jsonl_se_genera_y_es_parseable(self):
        normas = [
            Prohibition(
                norm_id="F_test",
                applies_when="__test_siempre",
                target="t",
                priority=50,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "deontic_audit.jsonl"
            resolver = DeonticResolver(normas, audit_path=audit_path)
            resolver.evaluar({"k": "v1"}, {})
            resolver.evaluar({"k": "v2"}, {})

            self.assertTrue(audit_path.exists())
            lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                rec = json.loads(line)
                self.assertIn("ts", rec)
                self.assertIn("decision", rec)
                self.assertIn("contexto", rec)
                self.assertIn("result", rec)
                self.assertIn("permitida", rec["result"])

    def test_sin_audit_path_no_falla(self):
        normas = [
            Prohibition(
                norm_id="F_test2",
                applies_when="__test_siempre",
                target="t",
                priority=50,
            ),
        ]
        resolver = DeonticResolver(normas)  # audit_path=None
        ev = resolver.evaluar({}, {})
        self.assertIsInstance(ev, EvaluacionDeontica)


if __name__ == "__main__":
    unittest.main(verbosity=2)
