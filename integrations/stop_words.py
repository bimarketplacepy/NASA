"""Stop-words para validacion de descripciones de TrendSignals.

Una descripcion es 'stop-words solamente' si TODOS sus tokens (post split,
lowercased, despuntuados) caen en el set de aca o son menos de 2 chars.

El check es deliberadamente CONSERVADOR: no nos rompe que pase un
falso negativo (descripcion levemente generica que pasa el filtro);
nos rompe descartar trends legitimos (falso positivo). Por eso la
lista es minima — solo articulos, preposiciones y los sufijos
'navideno' aislados que el equipo de Mateo identifico como ruido en
sus pruebas con Gemini.

Editable sin tocar Python: si querés agregar/quitar stops, modifica el
set y rerun los tests.
"""

from __future__ import annotations

import re
import string


# Articulos, preposiciones, conjunciones, pronombres ES + EN
STOP_WORDS_ES: frozenset[str] = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "al", "a", "en", "y", "o", "u", "que", "es", "son",
    "con", "por", "para", "pero", "sin", "sobre", "tras", "ante",
    "se", "su", "sus", "le", "les", "lo", "yo", "tu", "el", "ella",
    "esta", "este", "estas", "estos", "ese", "esa", "esos", "esas",
    "aquel", "aquella", "aquellos", "aquellas",
    "muy", "mas", "menos", "mucho", "poco",
})

STOP_WORDS_EN: frozenset[str] = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "by",
    "with", "from", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "this", "that", "these", "those",
})

# Tokens que solos no agregan info: si la descripcion entera es solo
# 'navidad' / 'christmas' / 'navideño', es ruido.
TOKENS_GENERICOS_NAVIDENOS: frozenset[str] = frozenset({
    "navidad", "navideno", "navidena", "navidenos", "navidenas",
    "christmas", "xmas", "noel", "santa",
})

ALL_STOP: frozenset[str] = (
    STOP_WORDS_ES | STOP_WORDS_EN | TOKENS_GENERICOS_NAVIDENOS
)


_PUNCT_RE = re.compile(rf"[{re.escape(string.punctuation + '¡¿')}]")


def tokenize(text: str) -> list[str]:
    """Tokeniza removiendo puntuacion y normalizando a minusculas.

    No elimina acentos para no perder "navideño" vs "navideno" — la
    detencion lo acepta (ambos estan en el set).
    """
    cleaned = _PUNCT_RE.sub(" ", text.lower())
    return [t for t in cleaned.split() if t]


def es_stopword_o_corta(token: str) -> bool:
    """True sii el token es stop-word o tiene menos de 2 chars."""
    return len(token) < 2 or token in ALL_STOP


def es_descripcion_vacia_o_stops(text: str, min_tokens_utiles: int = 2) -> bool:
    """True sii la descripcion es vacia o todos sus tokens utiles son stops.

    Args:
        text: la descripcion del TrendSignal.
        min_tokens_utiles: cantidad minima de tokens NO-stop para
            considerar la descripcion valida. Default 2.

    Returns:
        True si la descripcion debe ser RECHAZADA.
    """
    if not text or not text.strip():
        return True
    tokens = tokenize(text)
    utiles = [t for t in tokens if not es_stopword_o_corta(t)]
    return len(utiles) < min_tokens_utiles
