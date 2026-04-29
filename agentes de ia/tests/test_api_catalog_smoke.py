"""Smoke test de endpoints de catalogo."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_catalog_endpoints() -> None:
    client = TestClient(app)

    p = client.get("/api/v1/productos?page=1&size=5")
    assert p.status_code == 200
    productos = p.json()
    assert len(productos) > 0
    sku = productos[0]["sku"]

    d = client.get(f"/api/v1/productos/{sku}")
    assert d.status_code == 200

    f = client.get(f"/api/v1/productos/{sku}/forecast?semanas=1")
    assert f.status_code == 200
    assert f.json()["sku"] == sku

    provs = client.get("/api/v1/proveedores")
    assert provs.status_code == 200
    assert len(provs.json()) > 0

    inv = client.get("/api/v1/inventario")
    assert inv.status_code == 200

    eventos = client.get("/api/v1/eventos")
    assert eventos.status_code == 200
    assert len(eventos.json()) >= 1
