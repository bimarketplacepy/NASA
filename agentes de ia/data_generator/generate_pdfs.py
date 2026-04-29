"""Placeholder para generacion de PDFs de catalogos."""

from __future__ import annotations

from pathlib import Path


def generate_pdfs() -> None:
    """Crea placeholders de catalogos mientras se integra reportlab."""
    out_dir = Path(__file__).resolve().parent.parent / "data" / "catalogos_proveedor"
    out_dir.mkdir(parents=True, exist_ok=True)
    placeholder = out_dir / "README.txt"
    if not placeholder.exists():
        placeholder.write_text(
            "Catalogos PDF pendientes de implementacion con reportlab.\n",
            encoding="utf-8",
        )
