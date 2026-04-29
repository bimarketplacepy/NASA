"""OntologiaClient mock: persiste NodoProvisional a JSON.

Replica el contrato esperado por trend_injector.py. La version real
deberia conectarse a Neo4j v1, pero este mock alcanza para que el
pipeline corra end-to-end. La inyeccion canonica de TrendSignals al
grafo Neo4j real se hace via el bridge del Bloque 3 (cuando esta
disponible, trend_injector lo dereferencia automaticamente).

Idempotencia: dos llamadas con el mismo `nodo_id` reemplazan en lugar
de duplicar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from schemas.tendencias import NodoProvisional


_PROYECTO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_GRAFO_PATH = _PROYECTO_ROOT / "data" / "grafo_provisional.json"


class OntologiaClient:
    """Mock que persiste a `data/grafo_provisional.json`."""

    def __init__(self, grafo_path: Path | str | None = None) -> None:
        self.grafo_path = Path(grafo_path) if grafo_path else _DEFAULT_GRAFO_PATH

    def inyectar_nodo_provisional(self, nodo: NodoProvisional) -> bool:
        """Persiste o reemplaza un nodo. Idempotente por nodo_id.

        Returns:
            True si se persistio (o reemplazo) correctamente.
        """
        try:
            self.grafo_path.parent.mkdir(parents=True, exist_ok=True)
            grafo = self._read()
            grafo[nodo.nodo_id] = nodo.model_dump(mode="json")
            self.grafo_path.write_text(
                json.dumps(grafo, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

    def listar_nodos(self) -> list[dict[str, Any]]:
        """Devuelve todos los nodos persistidos."""
        return list(self._read().values())

    def get_nodo(self, nodo_id: str) -> dict[str, Any] | None:
        return self._read().get(nodo_id)

    def _read(self) -> dict[str, Any]:
        if not self.grafo_path.exists():
            return {}
        try:
            return json.loads(self.grafo_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
