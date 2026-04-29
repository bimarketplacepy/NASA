"""Test rapido para verificar que Gemini funciona."""

import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("ERROR: GEMINI_API_KEY no encontrada en .env")
    print("Variables de entorno cargadas:")
    for k, v in os.environ.items():
        if "GEMINI" in k or "API" in k:
            print(f"  {k}: {v[:10]}...")
    exit(1)

print(f"OK: GEMINI_API_KEY cargada (primeros 10 chars): {api_key[:10]}...")
print(f"Largo de la key: {len(api_key)} caracteres")

print("\nProbando llamada a Gemini...")

try:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents="Responde solo con la palabra OK",
    )

    print(f"OK: Gemini respondio: '{response.text.strip()}'")
    print("\n[EXITO] Gemini funciona correctamente.")
except Exception as e:
    print(f"\n[ERROR] Falla al llamar a Gemini: {e}")
    print(f"Tipo de error: {type(e).__name__}")