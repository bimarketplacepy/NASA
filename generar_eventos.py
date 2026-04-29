"""
generar_eventos.py
-------------------
Genera (o regenera) eventos_comerciales.csv con la lista que define este script.
Tarea 1 - Bloque 5.7 (auxiliar).

Estos eventos NO salen de Pegasus: son fechas comerciales relevantes para
Marketplace SA Paraguay. Editar la lista de abajo si querés agregar/sacar.
"""

import pandas as pd
from pathlib import Path

OUTPUT = Path(__file__).parent / "data" / "eventos_comerciales.csv"


# Lista editable de eventos del calendario comercial paraguayo
# Formato: (id, nombre, fecha, tipo)
EVENTOS = [
    ("EVT-ENAMORADOS-2026", "Dia de los Enamorados 2026", "2026-02-14", "ENAMORADOS"),
    ("EVT-MAESTRO-2026",    "Dia del Maestro 2026",       "2026-04-30", "DIA_DEL_MAESTRO"),
    ("EVT-MADRE-2026",      "Dia de la Madre 2026",       "2026-05-15", "DIA_DE_LA_MADRE"),
    ("EVT-NINO-2026",       "Dia del Nino 2026",          "2026-08-16", "DIA_DEL_NINO"),
    ("EVT-BFR-2026",        "Black Friday 2026",          "2026-11-27", "BLACK_FRIDAY"),
    ("EVT-NAV-2026",        "Navidad 2026",               "2026-12-25", "NAVIDAD"),
    ("EVT-ANO-2026",        "Ano Nuevo 2026",             "2026-12-31", "ANO_NUEVO"),
    ("EVT-REYES-2027",      "Reyes Magos 2027",           "2027-01-06", "REYES_MAGOS"),
]


def main():
    df = pd.DataFrame(EVENTOS, columns=["id", "nombre", "fecha", "tipo"])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT, index=False, encoding="utf-8")
    print(f"Generados {len(df)} eventos -> {OUTPUT}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
