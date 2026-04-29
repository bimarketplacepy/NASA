"""LLMClient: extraccion de tendencias desde posts crudos.

Auto-pick:
    - Si GEMINI_API_KEY en env (o .env via python-dotenv) -> GeminiLLMClient real.
    - Sino -> HeuristicLLMClient (fallback offline).

GeminiLLMClient usa el SDK `google-genai` (versiones >= 1.x). El
contrato `generate_structured(prompt, raw_posts, ...)` matchea lo que
`trends/trends_service.py` espera. Devuelve dict `{"tendencias": [...]}`.

Heuristico: agrupa posts por keywords navidenos, calcula confianza
desde diversidad de autores + engagement. Funciona offline para CI.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import string
from collections import Counter
from datetime import datetime, timezone
from typing import Any


# Cargar .env desde el ROOT del proyecto (no del cwd del caller). Esto
# garantiza que GEMINI_API_KEY se levante aunque la usuaria corra
# `python -c "..."` desde cualquier directorio.
try:
    from dotenv import load_dotenv
    from pathlib import Path as _Path
    _ENV_PATH = _Path(__file__).resolve().parent.parent / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass


_KEYWORDS_NAVIDENOS = {
    "navidad", "navideno", "navideño", "christmas", "xmas",
    "esfera", "esferas", "arbol", "arbolito", "arboles",
    "decoracion", "luces", "guirnalda", "guirnaldas",
    "santa", "noel", "muneco", "muñeco",
    "led", "wifi", "smart", "bluetooth", "inflable",
    "minimalista", "nordico", "rustico", "boho",
    "regalo", "envoltorio", "pesebre", "corona",
}

_PUNCT_RE = re.compile(rf"[{re.escape(string.punctuation)}]")


def _tokenize(text):
    return [t for t in _PUNCT_RE.sub(" ", text.lower()).split() if t]


def _es_post_navideno(post):
    text = " ".join(
        str(post.get(k, ""))
        for k in ("texto", "text", "caption", "title", "descripcion")
    )
    tokens = _tokenize(text)
    matches = [t for t in tokens if t in _KEYWORDS_NAVIDENOS]
    return (len(matches) > 0, matches)


def _engagement_score(post):
    m = post.get("metricas") or post.get("metrics") or {}
    views = float(m.get("views", 0) or 0)
    likes = float(m.get("likes", 0) or 0)
    shares = float(m.get("shares", 0) or 0)
    comments = float(m.get("comments", 0) or 0)
    return likes * 1.0 + shares * 5.0 + comments * 3.0 + views * 0.01


def _platform_a_fuente(platform):
    p = (platform or "").upper().strip()
    aliases = {
        "TIKTOK": "TIKTOK",
        "TIK_TOK": "TIKTOK",
        "INSTAGRAM": "INSTAGRAM",
        "META": "INSTAGRAM",
        "IG": "INSTAGRAM",
        "PINTEREST": "PINTEREST",
        "PIN": "PINTEREST",
        "GOOGLE": "GOOGLE_TRENDS",
        "GOOGLE_TRENDS": "GOOGLE_TRENDS",
        "TRENDS": "GOOGLE_TRENDS",
    }
    return aliases.get(p, "OTHER")


# =============================================================================
# HeuristicLLMClient (offline fallback)
# =============================================================================


class HeuristicLLMClient:
    """Cliente LLM heuristico que NO llama API. Para CI / smoke offline."""

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.last_request = None
        self.last_response = None

    async def generate_structured(self, prompt, raw_posts=None, temperature=0.2, max_tokens=4000):
        await asyncio.sleep(0)
        if not raw_posts:
            return {"tendencias": []}

        self.last_request = {"prompt_excerpt": prompt[:200], "n_posts": len(raw_posts)}

        clusters = {}
        for post in raw_posts:
            ok, matches = _es_post_navideno(post)
            if not ok:
                continue
            counter = Counter(matches)
            top_kw = counter.most_common(1)[0][0]
            clusters.setdefault(top_kw, []).append(post)

        tendencias = []
        for kw, posts in clusters.items():
            if not posts:
                continue
            top_post = max(posts, key=_engagement_score)
            text_top = " ".join(
                str(top_post.get(k, ""))
                for k in ("texto", "text", "caption", "title", "descripcion")
            ).strip()

            desc = (f"{kw.capitalize()}: " + (text_top[:200] if text_top else f"trend de {kw}")).strip()
            if len(desc) < 10:
                desc = (desc + " - tendencia detectada en posts virales")[:500]
            else:
                desc = desc[:500]

            platforms = Counter(
                _platform_a_fuente(str(p.get("platform", p.get("fuente", ""))))
                for p in posts
            )
            fuente = platforms.most_common(1)[0][0]

            avg_eng = sum(_engagement_score(p) for p in posts) / len(posts)
            velocidad = min(1000.0, max(0.0, avg_eng / 10.0))

            autores = {
                str(p.get("autor", p.get("user_id", p.get("author", ""))))
                for p in posts
            }
            autores.discard("")
            n_autores = len(autores)

            size_score = min(1.0, len(posts) / 3.0)
            diversity_score = min(1.0, n_autores / 3.0)
            engagement_norm = min(1.0, avg_eng / 50000.0)
            confianza = size_score * 0.4 + diversity_score * 0.4 + engagement_norm * 0.2
            confianza = max(0.0, min(1.0, confianza))

            tendencias.append({
                "descripcion": desc,
                "fuente": fuente,
                "velocidad_crecimiento": velocidad,
                "confianza_extraccion": confianza,
                "productos_existentes_similares": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        self.last_response = {"tendencias": tendencias}
        return {"tendencias": tendencias}


# =============================================================================
# GeminiLLMClient (real, requiere GEMINI_API_KEY)
# =============================================================================


class GeminiLLMClient:
    """Cliente real Gemini via google-genai SDK. Lee GEMINI_API_KEY del env."""

    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY no esta seteada. Setear en .env o env var."
            )
        self.model = model or os.environ.get("GEMINI_MODEL", self.DEFAULT_MODEL)
        self.last_request = None
        self.last_response = None

    async def generate_structured(self, prompt, raw_posts=None, temperature=0.2, max_tokens=4000):
        """Llama Gemini con retry exponencial y devuelve dict con 'tendencias'.

        Retries: hasta 3 intentos con backoff 2s/4s/8s para errores
        transitorios (503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED, errores de red).
        Si todos fallan, cae a {"tendencias": []} con error visible en
        last_response.error. Tambien logea via loguru si esta disponible.
        """
        from google import genai
        from google.genai import types as genai_types

        try:
            from loguru import logger as _log
        except ImportError:
            _log = None

        client = genai.Client(api_key=self.api_key)

        def _call_sync():
            return client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                ),
            )

        self.last_request = {
            "prompt_chars": len(prompt),
            "n_posts": len(raw_posts) if raw_posts else 0,
            "model": self.model,
        }

        # Retry con backoff exponencial para errores transitorios
        max_retries = int(os.environ.get("GEMINI_MAX_RETRIES", "3"))
        backoff_base = float(os.environ.get("GEMINI_BACKOFF_S", "2.0"))
        last_exc = None
        response = None
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(_call_sync)
                break
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                # Detectar errores transitorios que justifican retry
                is_transient = any(
                    code in err_str
                    for code in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
                                  "DEADLINE_EXCEEDED", "INTERNAL")
                )
                if is_transient and attempt < max_retries - 1:
                    wait_s = backoff_base * (2 ** attempt)
                    msg = f"Gemini {type(exc).__name__} (intento {attempt+1}/{max_retries}), retry en {wait_s}s"
                    if _log: _log.warning(msg)
                    else: print(f"  [llm_client] {msg}")
                    await asyncio.sleep(wait_s)
                    continue
                # No transient o sin retries: rendirse
                self.last_response = {"error": f"{type(exc).__name__}: {exc}"}
                if _log:
                    _log.error(f"Gemini fallo definitivamente: {exc}")
                return {"tendencias": []}

        if response is None:
            self.last_response = {"error": f"Sin response post-retry: {last_exc}"}
            return {"tendencias": []}

        text = ""
        try:
            text = response.text if hasattr(response, "text") else ""
        except Exception:
            text = ""

        if not text:
            self.last_response = {"error": "respuesta vacia de Gemini"}
            return {"tendencias": []}

        # Limpiar markdown code fences si los agrego
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            self.last_response = {"error": f"JSON invalido: {exc}", "raw": text[:500]}
            return {"tendencias": []}

        if isinstance(data, dict) and "tendencias" in data:
            tendencias = data["tendencias"]
        elif isinstance(data, list):
            tendencias = data
        else:
            tendencias = []

        # Asegurar timestamp en cada item
        for t in tendencias:
            if isinstance(t, dict):
                if not t.get("timestamp"):
                    t["timestamp"] = datetime.now(timezone.utc).isoformat()

        self.last_response = {"tendencias_count": len(tendencias)}
        return {"tendencias": tendencias}


# =============================================================================
# Auto-pick LLMClient
# =============================================================================


def _autoselect_llm_client():
    """Devuelve la clase del cliente segun env."""
    if os.environ.get("GEMINI_API_KEY"):
        try:
            from google import genai  # noqa: F401
            return GeminiLLMClient
        except ImportError:
            pass  # SDK no instalado, cae a heuristico
    return HeuristicLLMClient


# Alias publico que trends_service.py espera. Auto-selecciona en runtime.
LLMClient = _autoselect_llm_client()
