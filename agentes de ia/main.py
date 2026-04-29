"""Entrypoint HTTP del backend NASA."""

from fastapi import FastAPI

from config import get_settings
from routers.contrafactual import router as contrafactual_router
from routers.eventos import router as eventos_router
from routers.feedback import router as feedback_router
from routers.negociacion import router as negociacion_router
from routers.grafo import router as grafo_router
from routers.health import router as health_router
from routers.inventario import router as inventario_router
from routers.chat import router as chat_router
from routers.agentes import router as agentes_router
from routers.perfil import router as perfil_router
from routers.productos import router as productos_router
from routers.proveedores import router as proveedores_router
from routers.recomendaciones import router as recomendaciones_router
from routers.simulacion import router as simulacion_router
from routers.traces import router as traces_router


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(recomendaciones_router, prefix=settings.api_prefix)
app.include_router(contrafactual_router, prefix=settings.api_prefix)
app.include_router(grafo_router, prefix=settings.api_prefix)
app.include_router(perfil_router, prefix=settings.api_prefix)
app.include_router(productos_router, prefix=settings.api_prefix)
app.include_router(proveedores_router, prefix=settings.api_prefix)
app.include_router(inventario_router, prefix=settings.api_prefix)
app.include_router(eventos_router, prefix=settings.api_prefix)
app.include_router(chat_router, prefix=settings.api_prefix)
app.include_router(agentes_router, prefix=settings.api_prefix)
app.include_router(feedback_router, prefix=settings.api_prefix)
app.include_router(negociacion_router, prefix=settings.api_prefix)
app.include_router(simulacion_router, prefix=settings.api_prefix)
app.include_router(traces_router, prefix=settings.api_prefix)
