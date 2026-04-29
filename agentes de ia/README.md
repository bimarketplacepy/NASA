# Proyecto NASA Backend

Base inicial del backend para soporte de decisiones de compras estacionales.

## Estado actual

- Estructura inicial creada.
- Aplicacion FastAPI con endpoint `GET /api/v1/health`.
- Configuracion centralizada con `pydantic-settings`.
- Contratos de datos (`schemas`) en progreso segun `design.md`.

## Ejecutar localmente

1. Crear entorno virtual e instalar dependencias:
   - `pip install -r requirements.txt`
2. Copiar variables:
   - `copy .env.example .env`
3. Levantar API:
   - `uvicorn main:app --reload`
