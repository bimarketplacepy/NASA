"""Servicio de critica adversarial con Gemini."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.recomendaciones import Recomendacion, Vulnerabilidad


load_dotenv()
_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_client = genai.Client(api_key=_GEMINI_API_KEY) if _GEMINI_API_KEY else None


SEVERITY_ORDER = {"CRITICA": 4, "ALTA": 3, "MEDIA": 2, "BAJA": 1}

TIPOS_VALIDOS = {
    "RETRASO_ADUANERO",
    "CAIDA_DEMANDA",
    "QUIEBRE_PROVEEDOR",
    "OBSOLESCENCIA_POST_EVENTO",
    "TIPO_CAMBIO_ADVERSO",
    "COMPETIDOR_DESCUENTO",
    "FALLA_CALIDAD",
}

SEVERIDADES_VALIDAS = {"BAJA", "MEDIA", "ALTA", "CRITICA"}


SYSTEM_INSTRUCTION = (
    "Eres un AUDITOR ADVERSARIAL experto en cadena de suministro y compras de retail navideno. "
    "Tu unico trabajo es ATACAR los planes de compra que te presenten, buscando vulnerabilidades "
    "realistas que podrian costar dinero al negocio.\n\n"
    "Para cada plan que recibas, identifica entre 3 y 5 vulnerabilidades concretas y plausibles. "
    "NO inventes ataques absurdos. Enfocate en categorias reales aplicables al plan especifico.\n\n"
    "TIPOS DE VULNERABILIDAD VALIDOS (debes usar exactamente uno de estos strings):\n"
    "- RETRASO_ADUANERO: aplica si hay items de proveedores externos (IDs con ASIA, EUR, o lead times altos).\n"
    "- CAIDA_DEMANDA: aplica si stock_muerto_p95 es alto o cobertura es muy alta (sobrestock probable).\n"
    "- QUIEBRE_PROVEEDOR: aplica si mas del 60 por ciento del costo total esta en un solo proveedor.\n"
    "- OBSOLESCENCIA_POST_EVENTO: aplica si hay productos altamente estacionales (navidad) que pierden valor luego.\n"
    "- TIPO_CAMBIO_ADVERSO: aplica si hay items de proveedores externos sensibles a divisas.\n"
    "- COMPETIDOR_DESCUENTO: aplica si los margenes son ajustados y la competencia podria forzar baja de precios.\n"
    "- FALLA_CALIDAD: aplica si hay proveedores con poca historia o productos con altas exigencias tecnicas.\n\n"
    "SEVERIDAD VALIDA: BAJA | MEDIA | ALTA | CRITICA. Asignar segun impacto_usd_esperado:\n"
    "- BAJA: < 5000 USD\n"
    "- MEDIA: 5000-20000 USD\n"
    "- ALTA: 20000-50000 USD\n"
    "- CRITICA: > 50000 USD\n\n"
    "Devuelve SOLO un JSON valido con esta estructura exacta (sin texto antes ni despues):\n"
    "{\n"
    '  "vulnerabilidades": [\n'
    "    {\n"
    '      "tipo": "QUIEBRE_PROVEEDOR",\n'
    '      "descripcion": "El 78 por ciento del costo se concentra en PROV-A...",\n'
    '      "probabilidad_estimada": 0.15,\n'
    '      "impacto_usd_esperado": 8500.0,\n'
    '      "impacto_usd_p95": 14000.0,\n'
    '      "severidad": "MEDIA",\n'
    '      "items_afectados": ["LED-001", "ARB-001"],\n'
    '      "mitigacion_sugerida": "Diversificar 30 por ciento del volumen con PROV-B."\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Se especifico con numeros reales del plan. No uses placeholders. items_afectados debe contener "
    "SKUs reales del plan. Responde en espanol."
)


class CriticService:
    """Critica adversarial impulsada por Gemini con fallback a fórmulas."""

    def atacar(self, rec: Recomendacion) -> list[Vulnerabilidad]:
        """Ataca recomendacion con Gemini y devuelve vulnerabilidades ordenadas por severidad."""
        if _client is None:
            return self._fallback_simple(rec)
        try:
            plan_serializado = self._serializar_plan(rec)
            response = _client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=f"Audita este plan de compra:\n\n{plan_serializado}",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(response.text)
            vulns_raw = data.get("vulnerabilidades", [])
            vulns: list[Vulnerabilidad] = []
            for v in vulns_raw:
                vuln = self._construir_vulnerabilidad(v)
                if vuln is not None:
                    vulns.append(vuln)
            if not vulns:
                return self._fallback_simple(rec)
            vulns.sort(
                key=lambda v: (SEVERITY_ORDER.get(v.severidad, 0), v.impacto_usd_p95),
                reverse=True,
            )
            return vulns
        except Exception:
            return self._fallback_simple(rec)

    def _serializar_plan(self, rec: Recomendacion) -> str:
        """Convierte la recomendacion a un texto legible para el LLM."""
        items_text = []
        for item in rec.items:
            items_text.append(
                f"- SKU {item.sku}: {item.cantidad} unidades a proveedor {item.proveedor_id}, "
                f"costo unitario {item.costo_unitario}, costo total {item.costo_total}"
            )
        items_str = "\n".join(items_text)
        metricas = rec.metricas
        return (
            f"Recomendacion ID: {rec.recomendacion_id}\n"
            f"Presupuesto consumido: {rec.presupuesto_consumido}\n"
            f"Presupuesto total: {rec.presupuesto_total}\n"
            f"Items ({len(rec.items)}):\n{items_str}\n\n"
            f"Metricas de riesgo:\n"
            f"- VaR 95: {metricas.var_95 if hasattr(metricas, 'var_95') else 'N/A'}\n"
            f"- Stock muerto P95: {metricas.stock_muerto_p95 if hasattr(metricas, 'stock_muerto_p95') else 'N/A'}\n"
            f"- Cobertura objetivo: {metricas.cobertura_objetivo if hasattr(metricas, 'cobertura_objetivo') else 'N/A'}\n"
            f"Confianza global: {rec.nivel_confianza_global}\n"
        )

    def _construir_vulnerabilidad(self, data: dict) -> Vulnerabilidad | None:
        """Construye una Vulnerabilidad validando tipos. Si falla, devuelve None."""
        try:
            tipo = data.get("tipo", "")
            if tipo not in TIPOS_VALIDOS:
                return None
            severidad = data.get("severidad", "")
            if severidad not in SEVERIDADES_VALIDAS:
                return None
            return Vulnerabilidad(
                tipo=tipo,
                descripcion=str(data.get("descripcion", "Sin descripcion")),
                probabilidad_estimada=float(data.get("probabilidad_estimada", 0.2)),
                impacto_usd_esperado=float(data.get("impacto_usd_esperado", 0.0)),
                impacto_usd_p95=float(data.get("impacto_usd_p95", 0.0)),
                severidad=severidad,
                items_afectados=list(data.get("items_afectados", [])),
                mitigacion_sugerida=data.get("mitigacion_sugerida"),
            )
        except Exception:
            return None

    def _fallback_simple(self, rec: Recomendacion) -> list[Vulnerabilidad]:
        """Fallback si Gemini falla: una vulnerabilidad generica de quiebre por concentracion."""
        if not rec.items:
            return []
        proveedores_costo: dict[str, float] = {}
        for item in rec.items:
            proveedores_costo[item.proveedor_id] = (
                proveedores_costo.get(item.proveedor_id, 0.0) + item.costo_total
            )
        if not proveedores_costo:
            return []
        total = sum(proveedores_costo.values())
        prov_max = max(proveedores_costo.items(), key=lambda kv: kv[1])
        pct_max = (prov_max[1] / total) if total > 0 else 0.0
        if pct_max < 0.4:
            return []
        impacto = prov_max[1] * 0.15
        return [
            Vulnerabilidad(
                tipo="QUIEBRE_PROVEEDOR",
                descripcion=f"Concentracion del {pct_max*100:.1f}% del costo en {prov_max[0]}.",
                probabilidad_estimada=0.20,
                impacto_usd_esperado=round(impacto, 2),
                impacto_usd_p95=round(impacto * 1.6, 2),
                severidad="MEDIA" if impacto < 20000 else "ALTA",
                items_afectados=[i.sku for i in rec.items if i.proveedor_id == prov_max[0]],
                mitigacion_sugerida="Diversificar volumen con proveedor secundario.",
            )
        ]
