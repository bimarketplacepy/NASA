"""Smoke test de simulacion, negociacion y traces."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_ops_endpoints_flow() -> None:
    client = TestClient(app)

    rec_resp = client.post(
        "/api/v1/recomendaciones/generar",
        json={"evento_id": "EVT_BLACK_FRIDAY_2026", "semanas_hasta_evento": 1, "presupuesto": 55000.0},
    )
    assert rec_resp.status_code == 200
    rec = rec_resp.json()
    rec_id = rec["recomendacion_id"]
    proveedor_id = rec["items"][0]["proveedor_id"]

    sim = client.post("/api/v1/simulacion/montecarlo", json={"n_sims": 1200})
    assert sim.status_code == 200
    assert sim.json()["n_simulaciones"] == 1200

    neg = client.post(
        "/api/v1/negociacion/borrador",
        json={"recomendacion_id": rec_id, "proveedor_id": proveedor_id},
    )
    assert neg.status_code == 200
    assert "borrador" in neg.json()

    tr = client.get(f"/api/v1/traces/{rec_id}")
    assert tr.status_code == 200
    assert len(tr.json()["traces"]) >= 1
