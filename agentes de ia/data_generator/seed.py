"""Entrypoint para poblar datos sinteticos del proyecto."""

from __future__ import annotations

import argparse

from data_generator.generate_csvs import generate_csvs


def main() -> None:
    """Ejecuta la generacion de datos iniciales."""
    parser = argparse.ArgumentParser(description="Generador de datos NASA backend")
    parser.add_argument("--seed", type=int, default=42, help="Seed aleatoria reproducible")
    args = parser.parse_args()

    generate_csvs(random_seed=args.seed)
    print("Datos sinteticos generados en ./data")


if __name__ == "__main__":
    main()
