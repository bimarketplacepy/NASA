"""Servicio unificado de optimizacion.

En esta iteracion implementa la ruta heuristica end-to-end:
- Seleccion de cantidades/proveedor por SKU.
- Simulacion Monte Carlo para metricas de riesgo.
- Construccion de `Recomendacion` serializable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from datetime import date, time, timedelta
import json
from pathlib import Path
import uuid

from clients.data_loader import DataLoader, get_data_loader
from schemas.eventos import EventoComercial
from schemas.preferencias import PerfilOperador
from schemas.recomendaciones import ItemCompra, Recomendacion
from schemas.simulacion import ForecastResult
from services.monte_carlo.simulator import MonteCarloSimulator
from services.optimizer.heuristic_fallback import HeuristicOptimizer
from services.optimizer.robust_affine_policy import (
    AffinePolicyParams,
    FinancialConstraints,
    RobustAffinePolicyOptimizer,
    build_inputs_from_domain,
    solution_to_items,
)
from optimization.dispatcher_ref import DispatcherReferencia
from optimization.integrations import DeonticResolver
from optimization.schemas import (
    CaracteristicasSerie,
    DecisionContext as OptDecisionContext,
    EventoProximo as OptEventoProximo,
    ForecastResult as OptForecastResult,
    ProveedorCandidato as OptProveedorCandidato,
)


RECOMMENDATION_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "recomendaciones"


class OptimizerService:
    """Orquestador de optimizacion y post-analisis."""

    def __init__(self, data_loader: DataLoader | None = None) -> None:
        self.data_loader = data_loader or get_data_loader()
        self.heuristic = HeuristicOptimizer(self.data_loader)
        self.simulator = MonteCarloSimulator(self.data_loader)
        self.robust_affine = RobustAffinePolicyOptimizer()
        self.dispatcher = DispatcherReferencia()
        self.deontic = DeonticResolver()

    def optimizar(
        self,
        skus_objetivo: list[str],
        forecasts: dict[str, ForecastResult],
        evento: EventoComercial,
        perfil: PerfilOperador,
        presupuesto: float | None = None,
        proveedores_excluidos: list[str] | None = None,
        metodo: str = "saa",
        timeout_segundos: int = 30,
    ) -> Recomendacion:
        """Genera una recomendacion de compra.

        Args:
            skus_objetivo: Lista de SKUs objetivo.
            forecasts: Forecast por SKU.
            evento: Evento comercial.
            perfil: Perfil del operador.
            presupuesto: Restriccion de gasto opcional.
            proveedores_excluidos: Proveedores a evitar.
            metodo: Metodo solicitado (se registra, pero en esta fase cae a heuristica).
            timeout_segundos: Timeout nominal (reservado para solver exacto).

        Returns:
            Recomendacion lista para persistir y mostrar.
        """
        if metodo in {"dispatcher", "biblioteca", "tarea4"}:
            items, notes = self._optimizar_con_biblioteca(
                skus_objetivo=skus_objetivo,
                forecasts=forecasts,
                evento=evento,
                presupuesto=presupuesto,
                proveedores_excluidos=proveedores_excluidos or [],
            )
            if not items:
                raise ValueError("La biblioteca optimization no genero items viables.")
            mc = self.simulator.simular(
                items=items,
                forecasts=forecasts,
                n_sims=2500,
                correlaciones=self.simulator.estimate_correlations_from_history([i.sku for i in items]),
                seed=42,
            )
            rec_id = f"REC_{uuid.uuid4().hex[:12].upper()}"
            presupuesto_consumido = float(sum(i.costo_total for i in items))
            confianza = self._compute_confidence(mc.metricas.probabilidad_perdida, notes)
            justificacion = self._build_justification("dispatcher", timeout_segundos, notes, mc.metricas.var_95)
            recomendacion = Recomendacion(
                recomendacion_id=rec_id,
                timestamp=datetime.now(timezone.utc),
                operador_id=perfil.operador_id,
                evento_objetivo_id=evento.evento_id,
                items=items,
                metricas=mc.metricas,
                vulnerabilidades=[],
                grafo_causal_id=f"GRAFO_{rec_id}",
                justificacion_texto=justificacion,
                nivel_confianza_global=confianza,
                perfil_operador_aplicado=f"{perfil.operador_id}:v{perfil.version}",
                estado="BORRADOR",
                presupuesto_consumido=presupuesto_consumido,
                presupuesto_total=presupuesto,
            )
            self._cache_recommendation(recomendacion)
            return recomendacion

        notes: list[str] = []
        if metodo in {"robust_affine", "robusto_afin"}:
            affine_params = AffinePolicyParams(
                y_0=0.15,
                y_i=0.05,
                ewma_alpha=0.25,
                ewma_k=0.8,
            )
            financial_constraints = FinancialConstraints(
                min_turnover_ratio_psi=0.45,
                min_revenue_target_phi=5000.0,
                initial_cash_Zt=presupuesto if presupuesto is not None else 250000.0,
                holding_cost_rate_h=0.03,
                stockout_penalty_rate_c=0.25,
            )
            try:
                dias_hasta_evento = max(1, (evento.fecha_objetivo - datetime.now(timezone.utc).date()).days)
                inputs, sku_order, provider_order = build_inputs_from_domain(
                    data_loader=self.data_loader,
                    skus_objetivo=skus_objetivo,
                    forecasts=forecasts,
                    proveedores_excluidos=proveedores_excluidos or [],
                    purchase_budget=presupuesto,
                    buffer_seguridad_dias=5,
                    dias_hasta_evento=dias_hasta_evento,
                )
                solution = self.robust_affine.solve(
                    inputs=inputs,
                    affine_params=affine_params,
                    financial_constraints=financial_constraints,
                )
                items = solution_to_items(
                    solution=solution,
                    sku_order=sku_order,
                    provider_order=provider_order,
                    unit_cost=inputs.unit_cost,
                    evento=evento,
                )
                notes.append(
                    f"robust_affine status={solution.status} obj={solution.objective_value:.2f} "
                    f"y0={solution.y0:.4f} yi={solution.yi:.4f}"
                )
                notes.append(
                    f"coverage={solution.coverage_ratio:.4f} budget_used_pct={solution.budget_used_pct:.2f} "
                    f"uncovered_count={len(solution.uncovered_sku_indices)}"
                )
                if not items:
                    raise ValueError("Robust affine devolvio plan vacio.")
            except Exception as exc:
                notes.append(f"fallback_heuristica_por_error_robust_affine={exc}")
                heuristic_result = self.heuristic.build_plan(
                    skus_objetivo=skus_objetivo,
                    forecasts=forecasts,
                    evento=evento,
                    presupuesto=presupuesto,
                    aversion_stockout=float(perfil.aversion_stockout),
                    proveedores_excluidos=proveedores_excluidos or [],
                )
                items = heuristic_result.items
                notes.extend(heuristic_result.notes)
        else:
            heuristic_result = self.heuristic.build_plan(
                skus_objetivo=skus_objetivo,
                forecasts=forecasts,
                evento=evento,
                presupuesto=presupuesto,
                aversion_stockout=float(perfil.aversion_stockout),
                proveedores_excluidos=proveedores_excluidos or [],
            )
            items = heuristic_result.items
            notes.extend(heuristic_result.notes)

        if not items:
            raise ValueError("No se pudo construir ningun item de compra viable.")

        corr = self.simulator.estimate_correlations_from_history([i.sku for i in items])
        mc = self.simulator.simular(
            items=items,
            forecasts=forecasts,
            n_sims=2500,
            correlaciones=corr,
            seed=42,
        )

        rec_id = f"REC_{uuid.uuid4().hex[:12].upper()}"
        presupuesto_consumido = float(sum(i.costo_total for i in items))
        confianza = self._compute_confidence(mc.metricas.probabilidad_perdida, notes)
        justificacion = self._build_justification(metodo, timeout_segundos, notes, mc.metricas.var_95)

        recomendacion = Recomendacion(
            recomendacion_id=rec_id,
            timestamp=datetime.now(timezone.utc),
            operador_id=perfil.operador_id,
            evento_objetivo_id=evento.evento_id,
            items=items,
            metricas=mc.metricas,
            vulnerabilidades=[],
            grafo_causal_id=f"GRAFO_{rec_id}",
            justificacion_texto=justificacion,
            nivel_confianza_global=confianza,
            perfil_operador_aplicado=f"{perfil.operador_id}:v{perfil.version}",
            estado="BORRADOR",
            presupuesto_consumido=presupuesto_consumido,
            presupuesto_total=presupuesto,
        )
        self._cache_recommendation(recomendacion)
        return recomendacion

    def _compute_confidence(self, prob_perdida: float, notes: list[str]) -> float:
        base = max(0.1, 1.0 - prob_perdida)
        penalty = min(0.3, 0.05 * len(notes))
        return round(max(0.05, base - penalty), 3)

    def _build_justification(self, metodo: str, timeout_segundos: int, notes: list[str], var_95: float) -> str:
        note_text = " | ".join(notes[:3]) if notes else "Sin incidencias relevantes."
        return (
            f"Plan generado con ruta heuristica (metodo solicitado={metodo}, timeout={timeout_segundos}s). "
            f"Se priorizo factibilidad y costo con evaluacion Monte Carlo. VaR95 estimado={var_95:.2f}. "
            f"Observaciones: {note_text}"
        )

    def _cache_recommendation(self, rec: Recomendacion) -> None:
        RECOMMENDATION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = RECOMMENDATION_CACHE_DIR / f"{rec.recomendacion_id}.json"
        path.write_text(json.dumps(rec.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")

    def _optimizar_con_biblioteca(
        self,
        skus_objetivo: list[str],
        forecasts: dict[str, ForecastResult],
        evento: EventoComercial,
        presupuesto: float | None,
        proveedores_excluidos: list[str],
    ) -> tuple[list, list[str]]:
        """Ruta Tarea 4: ejecuta la biblioteca optimization via dispatcher."""
        relaciones = self.data_loader.load_relaciones()
        proveedores = self.data_loader.load_proveedores()
        notes: list[str] = []
        items = []
        presupuesto_restante = float(presupuesto) if presupuesto is not None else None
        hoy = date.today()

        for sku in skus_objetivo:
            f_legacy = forecasts.get(sku)
            if f_legacy is None:
                notes.append(f"SKU {sku} omitido: sin forecast legacy.")
                continue

            candidatos = []
            relaciones_sku = [
                r
                for r in relaciones
                if r.sku == sku and r.activo and r.proveedor_id not in set(proveedores_excluidos)
            ]
            for r in relaciones_sku:
                prov = proveedores.get(r.proveedor_id)
                if prov is None:
                    continue
                candidatos.append(
                    OptProveedorCandidato(
                        proveedor_id=prov.proveedor_id,
                        nombre=prov.nombre,
                        precio_unitario=float(r.precio_unitario),
                        moq=int(r.moq),
                        lead_time_dias=int((prov.lead_time_dias_min + prov.lead_time_dias_max) / 2),
                        confiabilidad=float(prov.confiabilidad),
                        region=prov.region,
                    )
                )
            if not candidatos:
                notes.append(f"SKU {sku} omitido: sin proveedores candidatos.")
                continue

            budget_ctx = presupuesto_restante if presupuesto_restante is not None else 1e12
            ctx = OptDecisionContext(
                sku=sku,
                forecast=self._to_opt_forecast(f_legacy),
                proveedores_candidatos=candidatos,
                presupuesto_disponible=float(max(0.0, budget_ctx)),
                eventos_proximos=[
                    OptEventoProximo(
                        nombre=evento.nombre,
                        fecha=datetime.combine(
                            evento.fecha_objetivo, time.min, tzinfo=timezone.utc
                        ),
                        factor_demanda=float(evento.boost_demanda),
                    )
                ],
            )

            try:
                bloqueada, razon = self.deontic.accion_bloqueada(ctx)
            except Exception:
                bloqueada, razon = False, "deontic no disponible"
            if bloqueada:
                notes.append(f"SKU {sku} bloqueado por deontica: {razon}")
                continue

            try:
                restricciones = self.deontic.evaluar_restricciones(ctx)
            except Exception:
                restricciones = []

            rec_opt = self.dispatcher.decidir(ctx, restricciones=restricciones)
            rel = next((r for r in relaciones_sku if r.proveedor_id == rec_opt.proveedor_sugerido), None)
            if rel is None:
                rel = relaciones_sku[0]
            prov = proveedores[rel.proveedor_id]
            descuento = 0.0
            for tramo in rel.descuentos_volumen:
                if rec_opt.cantidad_central >= tramo.cantidad_minima:
                    descuento = max(descuento, float(tramo.descuento_porcentaje))
            costo_unitario = float(rel.precio_unitario) * (1.0 - descuento)
            costo_total = round(costo_unitario * rec_opt.cantidad_central, 2)
            lead = int((prov.lead_time_dias_min + prov.lead_time_dias_max) / 2)
            llegada = hoy + timedelta(days=lead)
            buffer = round(max(0.0, (evento.fecha_objetivo - llegada).days / 7.0), 2)

            items.append(
                ItemCompra(
                    sku=sku,
                    proveedor_id=rel.proveedor_id,
                    cantidad=int(rec_opt.cantidad_central),
                    costo_unitario=round(costo_unitario, 4),
                    descuento_aplicado=round(descuento, 4),
                    costo_total=costo_total,
                    fecha_pedido_estimada=hoy,
                    fecha_arribo_estimada=llegada,
                    semanas_buffer_pre_evento=buffer,
                )
            )
            notes.append(f"{sku}: {rec_opt.algoritmo_id} -> {rel.proveedor_id} ({rec_opt.cantidad_central} u.)")
            if presupuesto_restante is not None:
                presupuesto_restante = max(0.0, presupuesto_restante - costo_total)

        return items, notes

    def _to_opt_forecast(self, f: ForecastResult) -> OptForecastResult:
        """Adapta ForecastResult legacy al contrato de optimization."""
        media = max(1.0, float(f.media))
        std = max(0.0, float(f.std))
        volatilidad = min(1.0, std / media) if media > 0 else 0.0
        semanas = 0 if f.metodo == "categoria_cold_start" else (60 if f.metodo in {"ets", "prophet"} else 12)
        fuente = "category_default" if f.metodo == "categoria_cold_start" else ("trend_only" if f.metodo == "tendencia" else "own")
        return OptForecastResult(
            sku=f.sku,
            media=[float(f.media)],
            std=[float(f.std)],
            p5=[float(f.p5)],
            p50=[float(f.p50)],
            p95=[float(f.p95)],
            fuente=fuente,
            semanas_de_historia_propia=max(0, semanas),
            confianza_global=0.85 if f.intervalo_confianza_calibrado else 0.65,
            caracteristicas_serie=CaracteristicasSerie(
                volatilidad=float(volatilidad),
                ciclicidad=0.0,
                tendencia_local=0.0,
                autocorrelacion_lag1=0.0,
                semanas_efectivas=max(0, semanas),
            ),
        )
