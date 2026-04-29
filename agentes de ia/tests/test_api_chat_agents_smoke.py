"""Smoke test para chat, agentes y feedback."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_chat_agents_feedback_flow() -> None:
    client = TestClient(app)

    chat_resp = client.post(
        "/api/v1/chat",
        json={"operador_id": "operador_demo", "mensaje": "genera recomendacion para black friday"},
    )
    assert chat_resp.status_code == 200
    sesion = chat_resp.json()
    assert sesion["sesion_id"]
    assert len(sesion["mensajes"]) >= 2
    rec_id = sesion["mensajes"][-1].get("objetos_adjuntos", {}).get("recomendacion_id")
    assert rec_id

    critic = client.post("/api/v1/agentes/critico/atacar", json={"recomendacion_id": rec_id})
    assert critic.status_code == 200
    assert critic.json()["ok"] is True

    research = client.post("/api/v1/agentes/web-research", json={"query": "arbol led navideno"})
    assert research.status_code == 200
    assert research.json()["nodo_id"]

    fb = client.post(
        "/api/v1/feedback",
        json={
            "recomendacion_id": rec_id,
            "operador_id": "operador_demo",
            "accion": "APROBAR",
            "razones_texto": "ok",
        },
    )
    assert fb.status_code == 200
    assert fb.json()["operador_id"] == "operador_demo"
