"""Servicio de redaccion de borradores de negociacion con Gemini."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.proveedores import Proveedor
from schemas.recomendaciones import ItemCompra


load_dotenv()
_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_client = genai.Client(api_key=_GEMINI_API_KEY) if _GEMINI_API_KEY else None


SYSTEM_INSTRUCTION = (
    "Eres un especialista en compras B2B redactando emails a proveedores. "
    "Tu trabajo es producir emails profesionales, persuasivos y especificos basados "
    "en los datos reales de la relacion comercial.\n\n"
    "REGLAS DE TONO segun el historial:\n"
    "- Si volumen_acumulado_usd > 50000 y frecuencia_anual >= 3: usa tono CERCANO PROFESIONAL "
    "(referencia la relacion existente, agradeci la colaboracion previa).\n"
    "- Si volumen_acumulado_usd entre 10000 y 50000: tono PROFESIONAL CORDIAL.\n"
    "- Si volumen_acumulado_usd < 10000 o frecuencia 0: tono FORMAL DE PRIMER CONTACTO.\n\n"
    "REGLAS DE CONTENIDO (obligatorias):\n"
    "1. Asunto: una linea clara y orientada a la accion (ej: 'Solicitud de cotizacion - Pedido N - "
    "Black Friday 2026').\n"
    "2. Saludo apropiado al tono.\n"
    "3. Si hay historial relevante (volumen > 10000), citarlo en numeros concretos.\n"
    "4. Listar items con SKU, cantidad y costo unitario objetivo.\n"
    "5. Si permite_negociacion_volumen=True, solicitar descuento por volumen con justificacion "
    "concreta basada en el monto total del pedido.\n"
    "6. Mencionar fechas: pedido en fecha_pedido_estimada del primer item, arribo deseado en "
    "fecha_arribo_estimada del primer item.\n"
    "7. Cerrar con proxima accion clara (cotizacion, confirmacion, llamada).\n"
    "8. Firma: 'Equipo de Compras'.\n\n"
    "FORMATO DE SALIDA (importante):\n"
    "Devuelve el email COMPLETO en texto plano (no JSON, no markdown). Empieza por la linea "
    "'Asunto: ...' y luego el cuerpo. Separa con saltos de linea normales. Maximo 250 palabras. "
    "Escribi en espanol natural, sin emojis."
)


class NegotiatorService:
    """Redactor de borradores de negociacion impulsado por Gemini con fallback a template."""

    def redactar(
        self,
        proveedor: Proveedor,
        items: list[ItemCompra],
        historial: dict,
        perfil_operador: dict,
    ) -> str:
        """Redacta borrador de email. Usa Gemini si esta disponible, fallback a template."""
        if _client is None:
            return self._fallback_template(proveedor, items, historial)
        try:
            contexto = self._construir_contexto(proveedor, items, historial, perfil_operador)
            response = _client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=contexto,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
            )
            email = response.text.strip()
            if not email or "Asunto:" not in email:
                return self._fallback_template(proveedor, items, historial)
            return email
        except Exception:
            return self._fallback_template(proveedor, items, historial)

    def _construir_contexto(
        self,
        proveedor: Proveedor,
        items: list[ItemCompra],
        historial: dict,
        perfil_operador: dict,
    ) -> str:
        """Arma el prompt enviado a Gemini con los datos relevantes."""
        items_lineas = []
        costo_total_pedido = 0.0
        for item in items:
            costo_total_pedido += item.costo_total
            items_lineas.append(
                f"  - SKU {item.sku}: {item.cantidad} unidades, "
                f"costo unitario objetivo {item.costo_unitario:.2f} {proveedor.moneda}, "
                f"costo total linea {item.costo_total:.2f}"
            )
        items_str = "\n".join(items_lineas)
        primer_item = items[0] if items else None
        fecha_pedido = primer_item.fecha_pedido_estimada if primer_item else "por definir"
        fecha_arribo = primer_item.fecha_arribo_estimada if primer_item else "por definir"
        volumen = float(historial.get("volumen_acumulado_usd", 0.0))
        frecuencia = int(historial.get("frecuencia_anual", 0))
        return (
            f"Datos del proveedor:\n"
            f"- Nombre: {proveedor.nombre}\n"
            f"- Pais: {proveedor.pais}\n"
            f"- Region: {proveedor.region}\n"
            f"- Moneda: {proveedor.moneda}\n"
            f"- Lead time: {proveedor.lead_time_dias_min}-{proveedor.lead_time_dias_max} dias\n"
            f"- Confiabilidad historica: {proveedor.confiabilidad:.2f}\n"
            f"- Permite negociacion por volumen: {proveedor.permite_negociacion_volumen}\n\n"
            f"Historial comercial:\n"
            f"- Volumen acumulado historico: {volumen:.2f} USD\n"
            f"- Frecuencia anual de compras: {frecuencia} ordenes\n\n"
            f"Pedido propuesto:\n"
            f"- Total de items: {len(items)}\n"
            f"- Costo total del pedido: {costo_total_pedido:.2f} {proveedor.moneda}\n"
            f"- Fecha pedido estimada: {fecha_pedido}\n"
            f"- Fecha arribo deseada: {fecha_arribo}\n"
            f"- Items detallados:\n{items_str}\n\n"
            f"Genera el email de negociacion siguiendo las reglas del system instruction."
        )

    def _fallback_template(
        self,
        proveedor: Proveedor,
        items: list[ItemCompra],
        historial: dict,
    ) -> str:
        """Fallback simple si Gemini falla."""
        volumen = float(historial.get("volumen_acumulado_usd", 0.0))
        frecuencia = int(historial.get("frecuencia_anual", 0))
        if volumen > 50000 and frecuencia >= 3:
            tono = "cercano profesional"
        elif volumen > 10000:
            tono = "profesional cordial"
        else:
            tono = "formal"
        lineas_items = "\n".join(
            f"- SKU {i.sku}: {i.cantidad} u. | costo unitario objetivo {i.costo_unitario:.2f}"
            for i in items
        )
        return (
            f"Asunto: Propuesta de compra - {proveedor.nombre}\n\n"
            f"Hola equipo de {proveedor.nombre},\n\n"
            f"Les escribimos en tono {tono} para avanzar una nueva orden.\n"
            f"Items solicitados:\n{lineas_items}\n\n"
            f"Nos interesa validar condiciones de volumen, plazo y mejora comercial.\n"
            f"Quedamos atentos a su propuesta.\n\n"
            f"Saludos,\nEquipo de Compras"
        )
