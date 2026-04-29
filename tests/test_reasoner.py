"""Tests del razonador HermiT (ontology_semantic/reasoner.py).

NO requieren Neo4j corriendo. La ABox se inyecta como string Turtle.
HermiT corre con el JAR bundled de owlready2.
"""

from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ontology_semantic.reasoner import (  # noqa: E402
    DERIVED_CLASSES,
    cargar_onto_con_abox,
    listar_inferencias,
    run_hermit,
)


NS = "http://marketplace.com.py/onto/v1#"


def _abox_5_productos_criticos() -> str:
    """5 productos: 2 perecederos puros, 2 alta rotacion puros, 1 ambos."""
    return f"""
    @prefix :    <{NS}> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    :p_perec_1 a :Producto ; :sku "PERE-001" ;
        :perecedero "true"^^xsd:boolean ; :altaRotacion "false"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    :p_perec_2 a :Producto ; :sku "PERE-002" ;
        :perecedero "true"^^xsd:boolean ; :altaRotacion "false"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    :p_rot_1 a :Producto ; :sku "ROT-001" ;
        :perecedero "false"^^xsd:boolean ; :altaRotacion "true"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    :p_rot_2 a :Producto ; :sku "ROT-002" ;
        :perecedero "false"^^xsd:boolean ; :altaRotacion "true"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    :p_ambos a :Producto ; :sku "AMBOS-001" ;
        :perecedero "true"^^xsd:boolean ; :altaRotacion "true"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    """


def _abox_1_coldstart_y_3_normales() -> str:
    """1 producto sin historial + 3 con historial."""
    return f"""
    @prefix :    <{NS}> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    :p_cold a :Producto ; :sku "COLD-001" ;
        :perecedero "false"^^xsd:boolean ; :altaRotacion "false"^^xsd:boolean ;
        :tieneHistorial "false"^^xsd:boolean .
    :p_normal_1 a :Producto ; :sku "NORM-001" ;
        :perecedero "false"^^xsd:boolean ; :altaRotacion "false"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    :p_normal_2 a :Producto ; :sku "NORM-002" ;
        :perecedero "false"^^xsd:boolean ; :altaRotacion "false"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    :p_normal_3 a :Producto ; :sku "NORM-003" ;
        :perecedero "false"^^xsd:boolean ; :altaRotacion "false"^^xsd:boolean ;
        :tieneHistorial "true"^^xsd:boolean .
    """


def _abox_proveedor_inconsistente() -> str:
    """Proveedor con esExterior=true Y declaracion explicita de :ProveedorLocal.

    :ProveedorLocal y :ProveedorExterior son disjuntas. esExterior=true
    fuerza ProveedorExterior, declaracion explicita fuerza ProveedorLocal,
    por ende inconsistencia.
    """
    return f"""
    @prefix :    <{NS}> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    :prov_inconsistente a :Proveedor, :ProveedorLocal ;
        :proveedorId "PROV-X" ; :pais "CN" ;
        :esExterior "true"^^xsd:boolean .
    """


class CincoProductosCriticosTest(unittest.TestCase):
    def test_clasificacion_critico(self):
        onto, world = cargar_onto_con_abox(abox_data=_abox_5_productos_criticos())
        result = run_hermit(world)
        self.assertTrue(result.consistent,
            f"Esperaba consistente. Inc msg: {result.inconsistency_message}")
        report = listar_inferencias(world)
        self.assertEqual(report.counts["ProductoCritico"], 5,
            f"Esperaba 5 ProductoCritico, hubo {report.counts['ProductoCritico']}")

    def test_perecedero_y_altarotacion_subclases(self):
        onto, world = cargar_onto_con_abox(abox_data=_abox_5_productos_criticos())
        run_hermit(world)
        report = listar_inferencias(world)
        self.assertEqual(report.counts["ProductoPerecedero"], 3)
        self.assertEqual(report.counts["ProductoAltaRotacion"], 3)


class ProductoColdStartTest(unittest.TestCase):
    def test_solo_uno_classifica_como_coldstart(self):
        onto, world = cargar_onto_con_abox(abox_data=_abox_1_coldstart_y_3_normales())
        result = run_hermit(world)
        self.assertTrue(result.consistent)
        report = listar_inferencias(world)
        self.assertEqual(report.counts["ProductoColdStart"], 1)

    def test_los_otros_3_no_son_coldstart(self):
        onto, world = cargar_onto_con_abox(abox_data=_abox_1_coldstart_y_3_normales())
        run_hermit(world)
        report = listar_inferencias(world)
        self.assertEqual(report.counts["ProductoColdStart"], 1)


class InconsistenciaProveedorTest(unittest.TestCase):
    def test_hermit_detecta_inconsistencia(self):
        onto, world = cargar_onto_con_abox(abox_data=_abox_proveedor_inconsistente())
        result = run_hermit(world)
        # El criterio de aceptacion es consistent=False. El message puede
        # quedar vacio segun la quirk del wrapper owlready2.
        self.assertFalse(result.consistent,
            "HermiT debio detectar la inconsistencia entre "
            ":ProveedorLocal y esExterior=true (disjoint).")


class TimingTest(unittest.TestCase):
    def test_razonamiento_termina_rapido(self):
        onto, world = cargar_onto_con_abox(abox_data=_abox_5_productos_criticos())
        result = run_hermit(world)
        self.assertLess(result.elapsed_s, 30.0)
        self.assertTrue(result.consistent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
