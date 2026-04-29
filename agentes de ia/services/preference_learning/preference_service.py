"""Servicio de persistencia y actualizacion de perfil de operador."""

from __future__ import annotations

from pathlib import Path
import json

from schemas.preferencias import FeedbackSignal, PerfilOperador
from services.preference_learning.update_rules import apply_feedback_rules


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PERFILES_DIR = DATA_DIR / "perfiles"
FEEDBACK_LOG_PATH = DATA_DIR / "feedback_log.jsonl"


class PreferenceService:
    """Gestiona ciclo de feedback y aprendizaje del perfil."""

    def registrar_feedback(self, signal: FeedbackSignal) -> PerfilOperador:
        """Registra feedback, actualiza perfil y persiste cambios."""
        perfil = self._load_perfil(signal.operador_id)
        updated = apply_feedback_rules(perfil, signal)
        self._save_perfil_atomic(updated)
        self._append_feedback(signal)
        return updated

    def _load_perfil(self, operador_id: str) -> PerfilOperador:
        path = PERFILES_DIR / f"{operador_id}.json"
        if not path.exists():
            # Fallback a perfil demo inicial.
            demo = PERFILES_DIR / "perfil_operador.json"
            if not demo.exists():
                raise FileNotFoundError(f"No existe perfil para operador {operador_id}")
            return PerfilOperador(**json.loads(demo.read_text(encoding="utf-8")))
        return PerfilOperador(**json.loads(path.read_text(encoding="utf-8")))

    def _save_perfil_atomic(self, perfil: PerfilOperador) -> None:
        PERFILES_DIR.mkdir(parents=True, exist_ok=True)
        final = PERFILES_DIR / f"{perfil.operador_id}.json"
        tmp = final.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(perfil.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(final)

    def _append_feedback(self, signal: FeedbackSignal) -> None:
        FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(signal.model_dump(mode="json"), ensure_ascii=False)
        with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(payload + "\n")
