"""Test con debug del NegotiatorService."""

import os
import traceback
from datetime import date
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("DIAGNOSTICO 1: GEMINI_API_KEY")
print("=" * 80)
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    print(f"OK: API key cargada (primeros 10 chars): {api_key[:10]}...")
else:
    print("ERROR: GEMINI_API_KEY no esta en .env")
    exit(1)

print("\n" + "=" * 80)
print("DIAGNOSTICO 2: importar el servicio")
print("=" * 80)
try:
    from services.negotiator.negotiator_service import NegotiatorService, _client
    print(f"OK: NegotiatorService importado")
    print(f"_client es None? {_client is None}")
    if _client is None:
        print("PROBLEMA: el cliente Gemini no se inicializo")
        exit(1)
except Exception as e:
    print(f"ERROR al importar: {e}")
    traceback.print_exc()
    exit(1)

print("\n" + "=" * 80)
print("DIAGNOSTICO 3: llamada directa a Gemini desde el servicio")
print("=" * 80)
try:
    from google.genai import types
    response = _client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents="Responde solo con la palabra OK",
    )
    print(f"OK: Gemini respondio: '{response.text.strip()}'")
except Exception as e:
    print(f"ERROR llamando a Gemini: {e}")
    traceback.print_exc()
    exit(1)

print("\n" + "=" * 80)
print("DIAGNOSTICO 4: ejecutar redactar() y ver donde cae")
print("=" * 80)

from schemas.proveedores import Proveedor
from schemas.recomendaciones import ItemCompra

proveedor = Proveedor(
    proveedor_id="PROV_ASIA_01",
    nombre="Shenzhen Bright Decor Co.",
    pais="China",
    region="asia",
    lead_time_dias_min=45,
    lead_time_dias_max=60,
    confiabilidad=0.82,
    reputacion_score=0.80,
    moneda="USD",
    permite_negociacion_volumen=True,
    contacto={"email": "sales@brightdecor.cn"},
)

items = [
    ItemCompra(
        sku="SKU_001",
        proveedor_id="PROV_ASIA_01",
        cantidad=762,
        costo_unitario=13.1532,
        descuento_aplicado=0.03,
        costo_total=10022.74,
        fecha_pedido_estimada=date(2026, 4, 28),
        fecha_arribo_estimada=date(2026, 6, 19),
        semanas_buffer_pre_evento=21.86,
    ),
]

historial = {"volumen_acumulado_usd": 85000, "frecuencia_anual": 5}
perfil = {"operador_id": "demo"}

service = NegotiatorService()

# Intentar la llamada manualmente capturando errores
print("\nIntentando construir contexto...")
try:
    contexto = service._construir_contexto(proveedor, items, historial, perfil)
    print("OK: contexto construido")
    print(f"Largo del contexto: {len(contexto)} chars")
except Exception as e:
    print(f"ERROR construyendo contexto: {e}")
    traceback.print_exc()
    exit(1)

print("\nIntentando llamada a Gemini con system_instruction...")
try:
    from services.negotiator.negotiator_service import SYSTEM_INSTRUCTION
    response = _client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=contexto,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )
    email = response.text.strip()
    print(f"OK: Gemini devolvio email")
    print(f"Largo del email: {len(email)} chars")
    print(f"Contiene 'Asunto:'? {'Asunto:' in email}")
    print(f"\nPRIMERAS 500 CHARS DEL EMAIL:")
    print(email[:500])
except Exception as e:
    print(f"ERROR llamando a Gemini con system_instruction: {e}")
    traceback.print_exc()

print("\n" + "=" * 80)
print("DIAGNOSTICO 5: ahora si llamar a redactar() del servicio")
print("=" * 80)
email_final = service.redactar(proveedor, items, historial, perfil)
print("Email final devuelto por redactar():")
print(email_final[:500])
print("\nEs el template? (busca 'tono cercano profesional' o similar)")
print("Es del template" if "para avanzar una nueva orden" in email_final else "Parece de Gemini")