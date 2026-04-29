"""Generador de CSVs sinteticos para el proyecto NASA."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import random

import numpy as np
import pandas as pd


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
N_WEEKS = 104


@dataclass(frozen=True)
class CategorySpec:
    categoria_id: str
    nombre: str
    peak_multiplier: float
    spread: float
    base_price: float


def _seasonal_pattern(peak_multiplier: float, spread: float) -> list[float]:
    """Construye un patron estacional semanal normalizado (52 semanas)."""
    pattern: list[float] = []
    for week in range(1, 53):
        raw = math.sin((2 * math.pi * (week - 47)) / 52) + 1
        clipped = min(2.0, max(0.0, raw))
        shaped = (clipped * peak_multiplier) * spread + (1 - spread)
        pattern.append(float(max(0.1, shaped)))
    total = sum(pattern)
    return [p / total * 52 for p in pattern]


def _build_categories() -> list[CategorySpec]:
    return [
        CategorySpec("CAT_LUCES", "Luces y Decoracion Luminica", 1.45, 1.0, 24.0),
        CategorySpec("CAT_ARBOL", "Arboles y Guirnaldas", 1.30, 0.9, 38.0),
        CategorySpec("CAT_ORNAMENT", "Ornamentos", 1.20, 0.85, 14.0),
        CategorySpec("CAT_MESA", "Mesa y Vajilla Festiva", 1.10, 0.8, 18.0),
        CategorySpec("CAT_EMPAQUE", "Empaque y Regaleria", 1.00, 0.7, 7.0),
        CategorySpec("CAT_TEXTIL", "Textiles Navidenos", 1.15, 0.8, 21.0),
        CategorySpec("CAT_EXTERIOR", "Decoracion Exterior", 1.35, 0.95, 42.0),
        CategorySpec("CAT_PREMIUM", "Premium Coleccionable", 1.25, 0.75, 58.0),
    ]


def _build_suppliers() -> list[dict]:
    return [
        {
            "proveedor_id": "PROV_NAC_01",
            "nombre": "Norte Festivo SA",
            "pais": "Argentina",
            "region": "nacional",
            "lead_time_dias_min": 7,
            "lead_time_dias_max": 14,
            "confiabilidad": 0.93,
            "reputacion_score": 0.89,
            "moneda": "ARS",
            "permite_negociacion_volumen": True,
            "email": "ventas@nortefestivo.ar",
            "telefono": "+54-11-4000-1001",
            "idioma_preferido": "es",
        },
        {
            "proveedor_id": "PROV_NAC_02",
            "nombre": "Navidad Urbana SRL",
            "pais": "Argentina",
            "region": "nacional",
            "lead_time_dias_min": 10,
            "lead_time_dias_max": 20,
            "confiabilidad": 0.9,
            "reputacion_score": 0.84,
            "moneda": "ARS",
            "permite_negociacion_volumen": True,
            "email": "contacto@navidadurbana.ar",
            "telefono": "+54-11-4000-1002",
            "idioma_preferido": "es",
        },
        {
            "proveedor_id": "PROV_ASIA_01",
            "nombre": "Shenzhen Bright Decor Co.",
            "pais": "China",
            "region": "asia",
            "lead_time_dias_min": 45,
            "lead_time_dias_max": 60,
            "confiabilidad": 0.82,
            "reputacion_score": 0.8,
            "moneda": "USD",
            "permite_negociacion_volumen": True,
            "email": "sales@brightdecor.cn",
            "telefono": "+86-755-1000-2001",
            "idioma_preferido": "en",
        },
        {
            "proveedor_id": "PROV_ASIA_02",
            "nombre": "Yiwu Holiday MegaTrade",
            "pais": "China",
            "region": "asia",
            "lead_time_dias_min": 60,
            "lead_time_dias_max": 75,
            "confiabilidad": 0.78,
            "reputacion_score": 0.75,
            "moneda": "USD",
            "permite_negociacion_volumen": True,
            "email": "biz@holidaymega.cn",
            "telefono": "+86-579-2000-3001",
            "idioma_preferido": "en",
        },
        {
            "proveedor_id": "PROV_EUR_01",
            "nombre": "Milano Natale Premium",
            "pais": "Italia",
            "region": "europa",
            "lead_time_dias_min": 30,
            "lead_time_dias_max": 45,
            "confiabilidad": 0.88,
            "reputacion_score": 0.93,
            "moneda": "EUR",
            "permite_negociacion_volumen": False,
            "email": "sales@milanonatale.it",
            "telefono": "+39-02-7000-5001",
            "idioma_preferido": "it",
        },
        {
            "proveedor_id": "PROV_REG_01",
            "nombre": "Sul Festas Ltda",
            "pais": "Brasil",
            "region": "regional",
            "lead_time_dias_min": 15,
            "lead_time_dias_max": 25,
            "confiabilidad": 0.87,
            "reputacion_score": 0.83,
            "moneda": "USD",
            "permite_negociacion_volumen": True,
            "email": "comercial@sulfestas.br",
            "telefono": "+55-11-5000-7001",
            "idioma_preferido": "pt",
        },
    ]


def _price_multiplier_for_supplier(proveedor_id: str) -> float:
    if proveedor_id == "PROV_ASIA_01":
        return 0.7
    if proveedor_id == "PROV_ASIA_02":
        return 0.6
    if proveedor_id == "PROV_EUR_01":
        return 1.3
    if proveedor_id == "PROV_REG_01":
        return 1.05
    if proveedor_id == "PROV_NAC_02":
        return 1.15
    return 1.2


def _moq_for_supplier(proveedor_id: str) -> tuple[int, int]:
    if proveedor_id == "PROV_ASIA_01":
        return 500, 2000
    if proveedor_id == "PROV_ASIA_02":
        return 1000, 3000
    if proveedor_id == "PROV_NAC_01":
        return 10, 50
    if proveedor_id == "PROV_NAC_02":
        return 30, 120
    if proveedor_id == "PROV_EUR_01":
        return 60, 220
    return 40, 180


def generate_csvs(random_seed: int = 42) -> None:
    """Genera y persiste el dataset sintetico del backend."""
    rng = random.Random(random_seed)
    np_rng = np.random.default_rng(random_seed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    categories = _build_categories()
    category_patterns = {
        c.categoria_id: _seasonal_pattern(c.peak_multiplier, c.spread) for c in categories
    }

    productos: list[dict] = []
    skus_per_category = [6, 6, 6, 6, 6, 6, 7, 7]
    sku_counter = 1
    for cat, n_items in zip(categories, skus_per_category, strict=True):
        for _ in range(n_items):
            sku = f"SKU_{sku_counter:03d}"
            perecedero = rng.random() < 0.15
            vida_util_dias = rng.randint(30, 90) if perecedero else None
            ref_price = float(np_rng.lognormal(mean=math.log(cat.base_price), sigma=0.28))
            productos.append(
                {
                    "sku": sku,
                    "nombre": f"{cat.nombre} {sku}",
                    "categoria_id": cat.categoria_id,
                    "perecedero": perecedero,
                    "vida_util_dias": vida_util_dias,
                    "precio_referencia": round(ref_price, 2),
                    "margen_objetivo": round(rng.uniform(0.25, 0.6), 3),
                    "descripcion": f"Producto navideno sintetico {sku} de {cat.nombre}",
                    "tags": "navidad;retail;temporada",
                }
            )
            sku_counter += 1

    proveedores = _build_suppliers()
    relaciones: list[dict] = []
    for p in productos:
        n_rel = rng.randint(1, 3)
        supplier_pool = [s["proveedor_id"] for s in proveedores]
        if p["categoria_id"] in {"CAT_PREMIUM", "CAT_EXTERIOR"}:
            weights = [2, 2, 3, 2, 5, 3]
        elif p["categoria_id"] in {"CAT_LUCES", "CAT_EMPAQUE"}:
            weights = [3, 3, 5, 4, 1, 4]
        else:
            weights = [4, 4, 2, 1, 2, 3]
        choices = rng.choices(supplier_pool, weights=weights, k=n_rel * 2)
        selected = list(dict.fromkeys(choices))[:n_rel]

        for prov_id in selected:
            multiplier = _price_multiplier_for_supplier(prov_id)
            unit_price = max(0.5, p["precio_referencia"] * (1 - p["margen_objetivo"]) * multiplier)
            moq_min, moq_max = _moq_for_supplier(prov_id)
            moq = rng.randint(moq_min, moq_max)
            if prov_id.startswith("PROV_ASIA"):
                descuentos = "1000:0.03|2000:0.06|3000:0.1"
            elif prov_id == "PROV_NAC_01":
                descuentos = "200:0.02|500:0.04"
            else:
                descuentos = "300:0.015|700:0.035"
            moneda = next(s["moneda"] for s in proveedores if s["proveedor_id"] == prov_id)
            relaciones.append(
                {
                    "proveedor_id": prov_id,
                    "sku": p["sku"],
                    "precio_unitario": round(unit_price, 2),
                    "moq": moq,
                    "descuentos_volumen": descuentos,
                    "moneda": moneda,
                    "activo": True,
                }
            )

    sales_rows: list[dict] = []
    for p in productos:
        cat_pattern = category_patterns[p["categoria_id"]]
        sku_factor = rng.uniform(60, 220)
        trend = rng.uniform(-0.07, 0.1)
        outlier_weeks = set(rng.sample(range(1, N_WEEKS + 1), k=3))
        for week in range(1, N_WEEKS + 1):
            seasonal = cat_pattern[((week - 1) % 52)]
            expected = sku_factor * seasonal * (1 + trend * (week / N_WEEKS))
            noise = np_rng.normal(0, 0.15)
            demand = max(0.0, expected * (1 + noise))
            if week in outlier_weeks:
                demand *= rng.uniform(0.4, 1.8)
            sales_rows.append(
                {
                    "sku": p["sku"],
                    "semana": week,
                    "anio_relativo": 1 if week <= 52 else 2,
                    "ventas_unidades": int(round(demand)),
                }
            )

    ventas_df = pd.DataFrame(sales_rows)
    inv_df = (
        ventas_df.groupby("sku")["ventas_unidades"]
        .mean()
        .reset_index(name="demanda_promedio")
        .assign(
            inventario_actual=lambda df: (
                df["demanda_promedio"] * np_rng.uniform(0, 4, size=len(df))
            ).round().astype(int)
        )
        [["sku", "inventario_actual"]]
    )

    eventos_df = pd.DataFrame(
        [
            {
                "evento_id": "EVT_BLACK_FRIDAY_2026",
                "nombre": "Black Friday 2026",
                "semana_objetivo": 47,
                "boost_demanda": 1.45,
            },
            {
                "evento_id": "EVT_NAVIDAD_2026",
                "nombre": "Navidad 2026",
                "semana_objetivo": 51,
                "boost_demanda": 1.8,
            },
            {
                "evento_id": "EVT_REYES_2027",
                "nombre": "Reyes 2027",
                "semana_objetivo": 1,
                "boost_demanda": 1.25,
            },
        ]
    )

    categorias_df = pd.DataFrame(
        [
            {
                "categoria_id": cat.categoria_id,
                "nombre": cat.nombre,
                "patron_estacional": ",".join(f"{v:.4f}" for v in category_patterns[cat.categoria_id]),
                "elasticidad_precio": round(rng.uniform(-1.6, -0.4), 3),
            }
            for cat in categories
        ]
    )

    productos_df = pd.DataFrame(productos)
    proveedores_df = pd.DataFrame(proveedores)
    relaciones_df = pd.DataFrame(relaciones)

    # Validaciones de integridad basicas.
    sku_set = set(productos_df["sku"])
    prov_set = set(proveedores_df["proveedor_id"])
    if not set(relaciones_df["sku"]).issubset(sku_set):
        raise ValueError("Hay SKUs en relacion_producto_proveedor que no existen en catalogo.")
    if not set(relaciones_df["proveedor_id"]).issubset(prov_set):
        raise ValueError("Hay proveedores en relacion_producto_proveedor que no existen.")

    productos_df.to_csv(DATA_DIR / "catalogo_productos.csv", index=False)
    categorias_df.to_csv(DATA_DIR / "categorias.csv", index=False)
    proveedores_df.to_csv(DATA_DIR / "proveedores.csv", index=False)
    relaciones_df.to_csv(DATA_DIR / "relacion_producto_proveedor.csv", index=False)
    ventas_df.to_csv(DATA_DIR / "ventas_historicas.csv", index=False)
    inv_df.to_csv(DATA_DIR / "inventario_actual.csv", index=False)
    eventos_df.to_csv(DATA_DIR / "eventos_comerciales.csv", index=False)

