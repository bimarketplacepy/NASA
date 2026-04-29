"""Smoke test de endpoints principales."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_health_and_generate_recommendation_flow() -> None:
    client = TestClient(app)
    h = client.get("/api/v1/health")
    assert h.status_code == 200

    payload = {"evento_id": "EVT_BLACK_FRIDAY_2026", "semanas_hasta_evento": 1, "presupuesto": 45000.0}
    r = client.post("/api/v1/recomendaciones/generar", json=payload)
    assert r.status_code == 200
    rec = r.json()
    assert rec["recomendacion_id"]

    g = client.get(f"/api/v1/grafo/causal/{rec['recomendacion_id']}")
    assert g.status_code == 200
