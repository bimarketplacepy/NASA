"""Optimizacion estocastica robusta con politica afin exponencial."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math

import numpy as np
import pulp
from scipy.sparse import csr_matrix

from clients.data_loader import DataLoader
from schemas.eventos import EventoComercial
from schemas.recomendaciones import ItemCompra
from schemas.simulacion import ForecastResult


@dataclass(frozen=True)
class AffinePolicyParams:
    y_0: float
    y_i: float
    ewma_alpha: float
    ewma_k: float


@dataclass(frozen=True)
class FinancialConstraints:
    min_turnover_ratio_psi: float
    min_revenue_target_phi: float
    initial_cash_Zt: float
    holding_cost_rate_h: float
    stockout_penalty_rate_c: float


@dataclass(frozen=True)
class RobustAffineInputs:
    demand_hat: np.ndarray
    unit_cost: np.ndarray
    sell_price: np.ndarray
    service_rate_r: np.ndarray
    epsilon: np.ndarray
    sigma: np.ndarray
    lead_time: np.ndarray
    moq: np.ndarray
    capacity_ct: np.ndarray
    error_history: np.ndarray
    risk_penalty: float = 0.0
    purchase_budget: float | None = None
    coverage_target: float = 0.95
    weight_cost: float = 1.0
    weight_stockout: float = 1.0
    stockout_penalty_per_sku: np.ndarray | None = None


@dataclass(frozen=True)
class RobustAffineSolution:
    status: str
    objective_value: float
    x_base: np.ndarray
    x_tilde: np.ndarray
    y0: float
    yi: float
    ewma_matrix: np.ndarray
    a_uiw: np.ndarray
    robust_lhs: np.ndarray
    shortfall: np.ndarray
    coverage_ratio: float
    budget_used_pct: float
    uncovered_sku_indices: list[int]


def _select_solver() -> pulp.LpSolver:
    highs = pulp.HiGHS_CMD(msg=False)
    if highs.available():
        return highs
    return pulp.PULP_CBC_CMD(msg=False)


def precompute_ewma_matrix(T: int, alpha: float, k_gain: float) -> np.ndarray:
    t_idx = np.arange(T)[:, None]
    u_idx = np.arange(T)[None, :]
    lag = t_idx - u_idx - 1
    w = k_gain * np.exp(-alpha * lag)
    w[lag < 0] = 0.0
    np.fill_diagonal(w, 0.0)
    _ = csr_matrix(w)
    return w


def precompute_affine_sensitivity_coefficients(
    service_rate_r: np.ndarray,
    k_gain: float,
    alpha: float,
    lead_time: np.ndarray,
    t_eval: int,
) -> np.ndarray:
    rho = math.exp(-alpha)
    u = np.arange(service_rate_r.shape[0], dtype=float)[:, None, None]
    l = lead_time[None, :, :]
    exp_power = np.maximum(t_eval - l - u, 0.0)
    if np.isclose(1.0 - rho, 0.0):
        geometric_sum = exp_power
    else:
        geometric_sum = (1.0 - np.power(rho, exp_power)) / (1.0 - rho)
    return -service_rate_r + (k_gain * geometric_sum)


def precompute_robust_lhs(a_uiw: np.ndarray, epsilon: np.ndarray, sigma: np.ndarray, k_gain: float) -> np.ndarray:
    sigma_safe = np.maximum(sigma, 1e-9)
    threshold = (k_gain**2) / sigma_safe
    positive_part = np.maximum(0.0, np.abs(a_uiw) - threshold)
    return np.sum(epsilon * positive_part, axis=0)


class RobustAffinePolicyOptimizer:
    def solve(
        self,
        inputs: RobustAffineInputs,
        affine_params: AffinePolicyParams,
        financial_constraints: FinancialConstraints,
        t_eval: int | None = None,
    ) -> RobustAffineSolution:
        demand_hat = np.asarray(inputs.demand_hat, dtype=float)
        unit_cost = np.asarray(inputs.unit_cost, dtype=float)
        sell_price = np.asarray(inputs.sell_price, dtype=float)
        service_rate_r = np.asarray(inputs.service_rate_r, dtype=float)
        epsilon = np.asarray(inputs.epsilon, dtype=float)
        sigma = np.asarray(inputs.sigma, dtype=float)
        lead_time = np.asarray(inputs.lead_time, dtype=float)
        moq = np.asarray(inputs.moq, dtype=float)
        capacity_ct = np.asarray(inputs.capacity_ct, dtype=float)
        error_history = np.asarray(inputs.error_history, dtype=float)

        I, W = unit_cost.shape
        T = error_history.shape[0]
        t_eval_eff = t_eval if t_eval is not None else T
        ewma_matrix = precompute_ewma_matrix(T=T, alpha=affine_params.ewma_alpha, k_gain=affine_params.ewma_k)
        a_uiw = precompute_affine_sensitivity_coefficients(
            service_rate_r=service_rate_r,
            k_gain=affine_params.ewma_k,
            alpha=affine_params.ewma_alpha,
            lead_time=lead_time,
            t_eval=t_eval_eff,
        )
        robust_lhs = precompute_robust_lhs(a_uiw=a_uiw, epsilon=epsilon, sigma=sigma, k_gain=affine_params.ewma_k)
        e_last = error_history[-1, :]
        e_integral = np.sum(error_history, axis=0)
        stockout_penalty = (
            np.asarray(inputs.stockout_penalty_per_sku, dtype=float)
            if inputs.stockout_penalty_per_sku is not None
            else np.maximum(1.0, sell_price * 0.25)
        )

        model = pulp.LpProblem("robust_affine_policy", pulp.LpMinimize)
        x_base = {(i, w): pulp.LpVariable(f"x_base_{i}_{w}", lowBound=0, cat="Continuous") for i in range(I) for w in range(W)}
        z_use = {(i, w): pulp.LpVariable(f"z_use_{i}_{w}", lowBound=0, upBound=1, cat="Binary") for i in range(I) for w in range(W)}
        x_tilde = {(i, w): pulp.LpVariable(f"x_tilde_{i}_{w}", lowBound=0, cat="Continuous") for i in range(I) for w in range(W)}
        shortfall = {i: pulp.LpVariable(f"shortfall_{i}", lowBound=0, cat="Continuous") for i in range(I)}

        y0 = pulp.LpVariable("y0", lowBound=-2.0, upBound=2.0, cat="Continuous")
        yi = pulp.LpVariable("yi", lowBound=-2.0, upBound=2.0, cat="Continuous")
        y0_dev_pos = pulp.LpVariable("y0_dev_pos", lowBound=0, cat="Continuous")
        y0_dev_neg = pulp.LpVariable("y0_dev_neg", lowBound=0, cat="Continuous")
        yi_dev_pos = pulp.LpVariable("yi_dev_pos", lowBound=0, cat="Continuous")
        yi_dev_neg = pulp.LpVariable("yi_dev_neg", lowBound=0, cat="Continuous")
        model += y0 - affine_params.y_0 == y0_dev_pos - y0_dev_neg
        model += yi - affine_params.y_i == yi_dev_pos - yi_dev_neg

        for i in range(I):
            affine_shift = y0 * float(e_last[i]) + yi * float(e_integral[i])
            for w in range(W):
                model += x_tilde[(i, w)] == x_base[(i, w)] + affine_shift
                model += x_base[(i, w)] >= moq[i, w] * z_use[(i, w)]
                model += x_base[(i, w)] <= capacity_ct[i, w] * z_use[(i, w)]
                model += robust_lhs[i, w] <= capacity_ct[i, w], f"robust_bound_{i}_{w}"
            model += pulp.lpSum(x_tilde[(i, w)] for w in range(W)) + shortfall[i] >= inputs.coverage_target * demand_hat[i]

        r_bar = np.mean(service_rate_r, axis=0)
        turnover_lhs = pulp.lpSum(float(unit_cost[i, w] * r_bar[i, w]) * (demand_hat[i] - shortfall[i]) for i in range(I) for w in range(W))
        turnover_rhs = financial_constraints.min_turnover_ratio_psi * pulp.lpSum(
            float(unit_cost[i, w]) * (x_tilde[(i, w)] - float(r_bar[i, w] * demand_hat[i])) for i in range(I) for w in range(W)
        )
        model += turnover_lhs >= turnover_rhs
        revenue_lhs = pulp.lpSum(float(sell_price[i] * r_bar[i, w]) * (demand_hat[i] - shortfall[i]) for i in range(I) for w in range(W))
        model += revenue_lhs >= financial_constraints.min_revenue_target_phi
        ingresos_esperados = pulp.lpSum(
            float(sell_price[i] * r_bar[i, w]) * (demand_hat[i] - shortfall[i]) for i in range(I) for w in range(W)
        )
        costos_holding_y_compra = pulp.lpSum(
            (financial_constraints.holding_cost_rate_h + float(unit_cost[i, w])) * x_tilde[(i, w)] for i in range(I) for w in range(W)
        )
        model += financial_constraints.initial_cash_Zt + ingresos_esperados - costos_holding_y_compra >= inputs.risk_penalty
        if inputs.purchase_budget is not None:
            model += pulp.lpSum(float(unit_cost[i, w]) * x_tilde[(i, w)] for i in range(I) for w in range(W)) <= float(
                inputs.purchase_budget
            )

        purchase_cost_obj = pulp.lpSum(float(unit_cost[i, w]) * x_tilde[(i, w)] for i in range(I) for w in range(W))
        stockout_obj = pulp.lpSum(
            financial_constraints.stockout_penalty_rate_c * float(stockout_penalty[i]) * shortfall[i] for i in range(I)
        )
        regularization_obj = 0.01 * (y0_dev_pos + y0_dev_neg + yi_dev_pos + yi_dev_neg)
        model += float(inputs.weight_cost) * purchase_cost_obj + float(inputs.weight_stockout) * stockout_obj + regularization_obj
        model.solve(_select_solver())

        x_base_out = np.zeros((I, W), dtype=float)
        x_tilde_out = np.zeros((I, W), dtype=float)
        shortfall_out = np.zeros(I, dtype=float)
        for i in range(I):
            shortfall_out[i] = float(pulp.value(shortfall[i]) or 0.0)
            for w in range(W):
                x_base_out[i, w] = float(pulp.value(x_base[(i, w)]) or 0.0)
                x_tilde_out[i, w] = float(pulp.value(x_tilde[(i, w)]) or 0.0)

        target_total = float(np.sum(inputs.coverage_target * demand_hat))
        shortfall_total = float(np.sum(shortfall_out))
        coverage_ratio = 1.0 if target_total <= 0 else max(0.0, 1.0 - (shortfall_total / target_total))
        spend = float(np.sum(x_tilde_out * unit_cost))
        budget_used_pct = (
            0.0 if not inputs.purchase_budget or inputs.purchase_budget <= 0 else float((spend / inputs.purchase_budget) * 100.0)
        )
        uncovered = [i for i in range(I) if shortfall_out[i] > 1e-6]

        return RobustAffineSolution(
            status=pulp.LpStatus[model.status],
            objective_value=float(pulp.value(model.objective) or 0.0),
            x_base=x_base_out,
            x_tilde=x_tilde_out,
            y0=float(pulp.value(y0) or 0.0),
            yi=float(pulp.value(yi) or 0.0),
            ewma_matrix=ewma_matrix,
            a_uiw=a_uiw,
            robust_lhs=robust_lhs,
            shortfall=shortfall_out,
            coverage_ratio=coverage_ratio,
            budget_used_pct=budget_used_pct,
            uncovered_sku_indices=uncovered,
        )


def build_inputs_from_domain(
    data_loader: DataLoader,
    skus_objetivo: list[str],
    forecasts: dict[str, ForecastResult],
    proveedores_excluidos: list[str] | None = None,
    purchase_budget: float | None = None,
    buffer_seguridad_dias: int = 5,
    dias_hasta_evento: int | None = None,
) -> tuple[RobustAffineInputs, list[str], list[str]]:
    excluded = set(proveedores_excluidos or [])
    providers = data_loader.load_proveedores()
    rels = []
    for r in data_loader.load_relaciones():
        if r.sku not in skus_objetivo or (not r.activo) or r.proveedor_id in excluded:
            continue
        if dias_hasta_evento is not None and r.proveedor_id in providers:
            if providers[r.proveedor_id].lead_time_dias_max + buffer_seguridad_dias > dias_hasta_evento:
                continue
        rels.append(r)
    if not rels:
        raise ValueError("No hay relaciones comerciales viables para robust affine.")

    sku_order = sorted({r.sku for r in rels})
    provider_order = sorted({r.proveedor_id for r in rels})
    I, W = len(sku_order), len(provider_order)
    U = max(4, min(12, len(data_loader.load_ventas_historicas()["semana"].unique()) // 10))
    T = U
    sku_idx = {s: i for i, s in enumerate(sku_order)}
    prov_idx = {p: w for w, p in enumerate(provider_order)}
    prod_map = data_loader.load_productos()

    demand_hat = np.array([max(1.0, forecasts[s].p50) for s in sku_order], dtype=float)
    sell_price = np.array([float(prod_map[s].precio_referencia) for s in sku_order], dtype=float)
    unit_cost = np.full((I, W), 1e4, dtype=float)
    lead_time = np.full((I, W), 90.0, dtype=float)
    moq = np.full((I, W), 0.0, dtype=float)
    capacity_ct = np.full((I, W), 1e6, dtype=float)
    service_rate_r = np.zeros((U, I, W), dtype=float)
    epsilon = np.zeros((U, I, W), dtype=float)
    sigma = np.ones((U, I, W), dtype=float)

    for rel in rels:
        i, w = sku_idx[rel.sku], prov_idx[rel.proveedor_id]
        prov = providers[rel.proveedor_id]
        unit_cost[i, w] = float(rel.precio_unitario)
        lead_time[i, w] = float((prov.lead_time_dias_min + prov.lead_time_dias_max) / 2.0 / 7.0)
        moq[i, w] = float(rel.moq)
        capacity_ct[i, w] = float(max(rel.moq * 20, demand_hat[i] * 3.0))
        for u in range(U):
            service_rate_r[u, i, w] = max(0.2, min(1.0, float(prov.confiabilidad)))
            epsilon[u, i, w] = max(1.0, forecasts[rel.sku].std * 0.5)
            sigma[u, i, w] = max(1.0, forecasts[rel.sku].std)

    error_history = np.zeros((T, I), dtype=float)
    for i, sku in enumerate(sku_order):
        f = forecasts[sku]
        if f.samples and len(f.samples) >= T:
            samples = np.asarray(f.samples[:T], dtype=float)
        else:
            rng = np.random.default_rng(42 + i)
            samples = rng.normal(loc=f.media, scale=max(1e-6, f.std), size=T)
        error_history[:, i] = samples - f.media

    inputs = RobustAffineInputs(
        demand_hat=demand_hat,
        unit_cost=unit_cost,
        sell_price=sell_price,
        service_rate_r=service_rate_r,
        epsilon=epsilon,
        sigma=sigma,
        lead_time=lead_time,
        moq=moq,
        capacity_ct=capacity_ct,
        error_history=error_history,
        risk_penalty=0.0,
        purchase_budget=purchase_budget,
        coverage_target=0.95,
        weight_cost=1.0,
        weight_stockout=1.0,
        stockout_penalty_per_sku=np.maximum(1.0, sell_price * 0.35),
    )
    return inputs, sku_order, provider_order


def solution_to_items(
    solution: RobustAffineSolution,
    sku_order: list[str],
    provider_order: list[str],
    unit_cost: np.ndarray,
    evento: EventoComercial,
) -> list[ItemCompra]:
    items: list[ItemCompra] = []
    today = date.today()
    I, W = solution.x_tilde.shape
    for i in range(I):
        for w in range(W):
            qty = int(round(max(0.0, solution.x_tilde[i, w])))
            if qty <= 0:
                continue
            cost = float(unit_cost[i, w])
            lead_days = 14 + (w * 7)
            arrival = today + timedelta(days=lead_days)
            items.append(
                ItemCompra(
                    sku=sku_order[i],
                    proveedor_id=provider_order[w],
                    cantidad=qty,
                    costo_unitario=round(cost, 4),
                    descuento_aplicado=0.0,
                    costo_total=round(qty * cost, 2),
                    fecha_pedido_estimada=today,
                    fecha_arribo_estimada=arrival,
                    semanas_buffer_pre_evento=round(max(0.0, (evento.fecha_objetivo - arrival).days / 7.0), 2),
                )
            )
    return items
