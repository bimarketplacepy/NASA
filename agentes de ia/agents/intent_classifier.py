"""Clasificador de intenciones con Gemini."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.agentes import IntentClassification


load_dotenv()
_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_client = genai.Client(api_key=_GEMINI_API_KEY) if _GEMINI_API_KEY else None


SYSTEM_INSTRUCTION = (
    "Eres un clasificador de intenciones para un asistente de compras de retail navideno. "
    "Recibes un mensaje del usuario en espanol y debes clasificarlo en UNA de estas intenciones:\n\n"
    "- SOLICITAR_RECOMENDACION: el usuario quiere generar/obtener un plan de compra. "
    "Ejemplos: 'recomendame que comprar', 'dame una recomendacion', 'que conviene pedir esta semana', "
    "'genera plan', 'necesito comprar para Navidad', 'que productos pido'.\n"
    "- CONTRAFACTUAL: el usuario plantea un escenario hipotetico. "
    "Ejemplos: 'que pasa si...', 'y si...', 'imagina que el proveedor X quiebra', "
    "'si Black Friday se adelanta', 'si bajo el presupuesto'.\n"
    "- CONSULTA_PRODUCTO: el usuario pregunta sobre productos del catalogo. "
    "Ejemplos: 'que productos tengo', 'mostrame el catalogo', 'cuales son las luces LED'.\n"
    "- CONSULTAR_TENDENCIAS: el usuario pregunta sobre tendencias virales o nuevos productos populares.\n"
    "- APROBAR_RECOMENDACION: el usuario confirma una recomendacion. "
    "Ejemplos: 'apruebo', 'dale', 'ok comprame eso', 'confirmo la compra'.\n"
    "- MODIFICAR_RECOMENDACION: el usuario quiere cambiar algo del plan. "
    "Ejemplos: 'cambia el proveedor', 'compra menos', 'aumenta la cantidad'.\n"
    "- RECHAZAR_RECOMENDACION: el usuario rechaza el plan. "
    "Ejemplos: 'no me gusta', 'rechazo', 'esa recomendacion no sirve'.\n"
    "- PEDIR_BORRADOR_NEGOCIACION: el usuario pide redactar un email al proveedor. "
    "Ejemplos: 'arma el correo', 'redacta el email', 'mensaje al proveedor'.\n"
    "- INVESTIGAR_NUEVO: el usuario pregunta sobre un proveedor o producto que el sistema no conoce.\n"
    "- EXPLICAR_DECISION: el usuario pregunta el por que de una recomendacion. "
    "Ejemplos: 'por que esto', 'explicame', 'fundamenta', 'razon'.\n"
    "- SALUDO: el usuario solo saluda.\n"
    "- OTRO: ninguna de las anteriores.\n\n"
    "Tambien debes extraer entidades relevantes del mensaje:\n"
    "- Si el usuario menciona un proveedor por nombre, extrae proveedor_nombre y proveedor_id "
    "(IDs disponibles: PROV-A=Importadora Asiatica, PROV-B=Distribuidora Local, PROV-C=Mayorista Premium).\n"
    "- Si menciona un SKU especifico, extraelo en sku.\n"
    "- Si menciona dias, presupuesto, cantidades: extraelos.\n\n"
    "Devuelve SOLO un JSON valido (sin texto antes ni despues) con esta estructura exacta:\n"
    "{\n"
    '  "intent": "SOLICITAR_RECOMENDACION",\n'
    '  "confianza": 0.95,\n'
    '  "entidades_extraidas": {"proveedor_id": "PROV-A"},\n'
    '  "requiere_confirmacion": false\n'
    "}\n"
    "El campo 'requiere_confirmacion' debe ser true SOLO para APROBAR_RECOMENDACION o "
    "RECHAZAR_RECOMENDACION (acciones irreversibles)."
)


class IntentClassifier:
    """Clasificador de intenciones usando Gemini con fallback robusto."""

    def __init__(self) -> None:
        self._client = _client

    def classify(self, texto: str) -> IntentClassification:
        """Clasifica intencion usando Gemini. Si falla, devuelve OTRO."""
        if self._client is None:
            return self._fallback_keywords(texto)
        try:
            response = self._client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=texto,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(response.text)
            return IntentClassification(
                intent=data.get("intent", "OTRO"),
                confianza=float(data.get("confianza", 0.5)),
                entidades_extraidas=data.get("entidades_extraidas", {}),
                requiere_confirmacion=bool(data.get("requiere_confirmacion", False)),
            )
        except Exception:
            return self._fallback_keywords(texto)

    def _fallback_keywords(self, texto: str) -> IntentClassification:
        """Fallback simple por keywords si Gemini no esta disponible."""
        t = texto.lower().strip()
        if "hola" in t or "buenas" in t:
            return IntentClassification(
                intent="SALUDO", confianza=0.7, entidades_extraidas={}, requiere_confirmacion=False
            )
        if "recomend" in t or "comprar" in t or "plan" in t:
            return IntentClassification(
                intent="SOLICITAR_RECOMENDACION", confianza=0.6, entidades_extraidas={}, requiere_confirmacion=False
            )
        if "que pasa" in t or "qué pasa" in t or "y si" in t:
            return IntentClassification(
                intent="CONTRAFACTUAL", confianza=0.6, entidades_extraidas={}, requiere_confirmacion=False
            )
        return IntentClassification(
            intent="OTRO", confianza=0.3, entidades_extraidas={}, requiere_confirmacion=False
        )


if __name__ == "__main__":
    clasificador = IntentClassifier()
    casos = [
        "Dame una recomendacion de compra para Navidad",
        "Que pasa si la importadora china quiebra?",
        "Mostrame los productos disponibles",
        "Hola, como estas?",
        "Por que recomendaste comprar tanto a la asiatica?",
        "Apruebo el plan",
        "Redacta un email al proveedor PROV-A",
    ]
    for caso in casos:
        resultado = clasificador.classify(caso)
        print(f"\nMensaje: {caso}")
        print(f"  Intent: {resultado.intent}")
        print(f"  Confianza: {resultado.confianza}")
        print(f"  Entidades: {resultado.entidades_extraidas}")
        print(f"  Requiere confirmacion: {resultado.requiere_confirmacion}")
