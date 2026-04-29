================================================================
SECCIÓN 5.1 — CONTRATOS DE DATOS: EXPANSIÓN ROBUSTA Y FINANCIERA
================================================================
# schemas/simulacion.py (AÑADIR A LO EXISTENTE)
class AffinePolicyParams(BaseModel):
    y_0: float                          # Coeficiente de corrección corto plazo
    y_i: float                          # Coeficiente de corrección integral
    ewma_alpha: float                   # Factor de decaimiento exponencial (0 < alpha < 1)
    ewma_k: float                       # Ganancia del filtro K

class FinancialConstraints(BaseModel):
    min_turnover_ratio_psi: float       # ψ: Rotación mínima exigida
    min_revenue_target_phi: float       # R_φ: Ingreso mínimo esperado
    initial_cash_Zt: float              # Caja inicial
    holding_cost_rate_h: float          # Costo de inmovilizar capital por SKU
    stockout_penalty_rate_c: float      # Costo de oportunidad / penalidad

================================================================
SECCIÓN 6.6 — MÓDULO services/optimizer/robust_affine_policy.py (NUEVO)
================================================================
PROPÓSITO: Implementar la formulación de Optimización Estocástica Robusta con 
Política Afín Exponencial (PI-like controller).
ESTADO: Cutting-edge / Paper Implementation.

FORMULACIÓN MATEMÁTICA ESTRICTA (Para traducir a código PuLP/SciPy):

1. POLÍTICA AFÍN (Affine Ordering Policy):
   La variable de decisión principal se transforma de un escalar `x` a una función afín 
   de los errores de forecast `e_t = d_t - d_hat_t`.
   x_tilde[t,i,w] = x_base[t,i,w] + y0 * e_{t-1} + yi * sum(e_tau)

2. PONDERACIÓN EXPONENCIAL (EWMA):
   Calcular matriz de pesos W donde cada celda es:
   W[t,u] = K * exp(-alpha * (t - u - 1))
   Esto asigna mayor importancia a shocks recientes de demanda.

3. COEFICIENTE DE SENSIBILIDAD NETA (A_uiw):
   Calcular para cada SKU/proveedor:
   A[u,i,w] = -r[u,i,w] + K * (1 - rho**(t - L - u)) / (1 - rho)
   donde rho = exp(-alpha). Este coeficiente es el shadow price del error.

4. RESTRICCIÓN ROBUSTA (Caso Acotado / Bounded Deviations):
   Construir el uncertainty set D_hat donde |d_hat| <= epsilon.
   Imponer la restricción agregada sobre el buffer de inventario:
   sum(epsilon[u,i,w] * max(0, abs(A[u,i,w]) - (k**2 / sigma[u,i,w]))) <= C_t
   donde C_t es el baseline determinístico de inventario.

5. RESTRICCIONES FINANCIERAS OBLIGATORIAS:
   A. Turnover Constraint:
      sum(c * d_hat * r) >= psi * c * sum(x_tilde_pasado - r * d_hat)
   B. Revenue Level Constraint:
      sum(p * d_hat * r) >= R_phi
   C. End-of-Period Cash Constraint:
      Z_t + sum(Ingresos_esperados) - sum(holding_cost + purchase_cost)*x_tilde >= penalidad_riesgo

ALGORITMO DE RESOLUCIÓN RECOMENDADO:
1. Recibir forecasts, matriz de covarianza (para heteroscedasticidad) y FinancialConstraints.
2. Inicializar variables `x_base`, `y0`, `yi` continuas.
3. Pre-computar coeficientes constantes `A_uiw` y matriz EWMA.
4. Añadir restricciones robustas iterativamente (cutting-plane method) si el solver 
   MILP estándar colapsa por tamaño, o inyectar la forma agregada cerrada si es pequeña.
5. Devolver los coeficientes `x_base`, `y0`, `yi` y evaluar el `x_tilde` esperado.