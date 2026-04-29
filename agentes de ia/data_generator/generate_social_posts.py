"""Generador basico de posts simulados de redes."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import random


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def generate_social_posts(random_seed: int = 42) -> None:
    """Genera posts simulados para pruebas de tendencias."""
    rng = random.Random(random_seed)
    now = datetime.utcnow()
    plataformas = ["TIKTOK", "INSTAGRAM", "PINTEREST", "REDDIT"]
    emergentes = ["Proyector Aurora LED", "Mini Aldea Nevada", "Lazo Holografico"]
    base_catalogo = ["Guirnalda Clasica", "Arbol PVC 1.8m", "Esferas Rojas"]
    ruido = ["receta navidena", "viaje de verano", "oferta tecnologia"]

    posts: list[dict] = []
    for i in range(80):
        delta = timedelta(hours=rng.randint(1, 24 * 30))
        plataforma = rng.choice(plataformas)
        if i < 28:
            producto = rng.choice(emergentes)
            texto = f"No paro de ver {producto} esta temporada"
            likes = rng.randint(400, 4200)
            shares = rng.randint(60, 900)
        elif i < 60:
            producto = rng.choice(base_catalogo)
            texto = f"Me gusto {producto} para decorar"
            likes = rng.randint(80, 900)
            shares = rng.randint(5, 120)
        else:
            texto = f"Hoy hablamos de {rng.choice(ruido)}"
            likes = rng.randint(5, 120)
            shares = rng.randint(0, 20)

        posts.append(
            {
                "plataforma": plataforma,
                "autor": f"user_{i:03d}",
                "texto": texto,
                "fecha": (now - delta).isoformat(),
                "likes": likes,
                "shares": shares,
                "hashtags": ["#navidad", "#decoracion"],
            }
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "posts_simulados.json").write_text(
        json.dumps(posts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
