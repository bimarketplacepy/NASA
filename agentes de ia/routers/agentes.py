"""Router de endpoints vinculados a agentes."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from schemas.tendencias import NodoProvisional
from services.runtime import runtime

router = APIRouter(prefix="/agentes", tags=["agentes"])


class WebResearchRequest(BaseModel):
    query: str


@router.post("/web-research", response_model=NodoProvisional)
async def web_research(payload: WebResearchRequest) -> NodoProvisional:
    """Crea nodo provisional desde query (mock inicial)."""
    nodo = NodoProvisional(
        nodo_id=f"NODO_{uuid.uuid4().hex[:10].upper()}",
        tipo="producto",
        datos={"query": payload.query, "estado": "pendiente_validacion"},
        origen="web_research",
        confianza=0.55,
        fuentes=["mock://web-search"],
        fecha_creacion=datetime.now(timezone.utc),
        requiere_revision=True,
    )
    from clients.ontologia_client import OntologiaClient

    OntologiaClient().inyectar_nodo_provisional(nodo)
    return nodo


@router.post("/tendencias", response_model=list[NodoProvisional])
async def detectar_tendencias() -> list[NodoProvisional]:
    """Detecta tendencias mock desde cache de posts simulados."""
    nodos: list[NodoProvisional] = []
    for nombre in ["Proyector Aurora LED", "Mini Aldea Nevada"]:
        nodo = NodoProvisional(
            nodo_id=f"TREND_{uuid.uuid4().hex[:8].upper()}",
            tipo="tendencia",
            datos={"producto_emergente": nombre, "velocidad_crecimiento": 0.22},
            origen="tendencia",
            confianza=0.68,
            fuentes=["data/posts_simulados.json"],
            fecha_creacion=datetime.now(timezone.utc),
            requiere_revision=True,
        )
        nodos.append(nodo)
    return nodos


class CriticRequest(BaseModel):
    recomendacion_id: str


@router.post("/critico/atacar")
async def critico_atacar(payload: CriticRequest) -> dict:
    """Ejecuta critic sobre recomendacion en memoria."""
    rec = runtime.last_recomendacion
    if rec is None or rec.recomendacion_id != payload.recomendacion_id:
        return {"ok": False, "error": "Recomendacion no encontrada en memoria"}
    vulns = runtime.critic_service.atacar(rec)
    return {"ok": True, "count": len(vulns), "vulnerabilidades": [v.model_dump(mode="json") for v in vulns]}
