"""Servicio de reoptimizacion contrafactual."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from schemas.contrafactual import EscenarioContrafactual, Perturbacion
from schemas.preferencias import PerfilOperador
from schemas.recomendaciones import Recomendacion
from schemas.simulacion import ForecastResult
from services.contrafactual.diff_engine import compute_diff
from services.contrafactual.perturbations import (
    apply_demand_multipliers,
    apply_perturbation,
    create_base_context,
)
from services.optimizer.optimizer_service import OptimizerService


class ContrafactualService:
    """Aplica perturbaciones y genera plan alterno con diff."""

    def __init__(self, optimizer_service: OptimizerService) -> None:
        self.optimizer_service = optimizer_service

    def reoptimizar(
        self,
        rec_base: Recomendacion,
        perturbacion: Perturbacion,
        forecasts_base: dict[str, ForecastResult],
        perfil: PerfilOperador,
    ) -> EscenarioContrafactual:
        """Reoptimiza bajo perturbacion y retorna escenario completo."""
        ctx = apply_perturbation(create_base_context(), perturbacion)
        alt_forecasts = apply_demand_multipliers(forecasts_base, ctx)

        skus = sorted({i.sku for i in rec_base.items})
        evento_id = rec_base.evento_objetivo_id
        eventos = self.optimizer_service.data_loader.load_eventos()
        evento = next((e for e in eventos if e.evento_id == evento_id), eventos[0])

        rec_alterna = self.optimizer_service.optimizar(
            skus_objetivo=skus,
            forecasts={k: v for k, v in alt_forecasts.items() if k in skus},
            evento=evento,
            perfil=perfil,
            presupuesto=ctx.budget_override if ctx.budget_override is not None else rec_base.presupuesto_total,
            proveedores_excluidos=ctx.excluded_suppliers,
            metodo="dispatcher",
            timeout_segundos=30,
        )
        # Fuerza lineage temporal.
        rec_alterna = rec_alterna.model_copy(update={"timestamp": datetime.now(timezone.utc)})

        diff = compute_diff(rec_base, rec_alterna)
        factibilidad = "FACTIBLE" if rec_alterna.items else "INFACTIBLE"
        explicacion = (
            f"Se aplico perturbacion {perturbacion.tipo}. "
            f"Delta costo={diff.delta_costo_total:.2f}, delta retorno={diff.delta_retorno_esperado:.2f}, "
            f"delta VaR={diff.delta_var:.2f}."
        )
        return EscenarioContrafactual(
            escenario_id=f"ESC_{uuid.uuid4().hex[:12].upper()}",
            recomendacion_base_id=rec_base.recomendacion_id,
            perturbacion=perturbacion,
            recomendacion_alterna=rec_alterna,
            diff=diff,
            factibilidad=factibilidad,
            explicacion_natural=explicacion,
        )
