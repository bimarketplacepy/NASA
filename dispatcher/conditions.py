"""Evaluador de expresiones seguro para condiciones de reglas YAML.

Cada regla del rules.yaml tiene una lista `cuando` con expresiones tipo
Python (`"context.tipo_sku == 'existing'"`, `"context.similar_top_k[0].score > 0.7"`).
Este modulo las parsea, valida que solo usen un subconjunto seguro del AST
(sin acceso a builtins, dunders, imports, etc.) y las evalua sobre un
namespace controlado.

Decision de diseno: NO usamos `eval()` ni siquiera con globals limpios.
Recorremos el AST manualmente con un visitor que solo soporta nodos del
allowlist. Cualquier construccion fuera de allowlist (lambda, comprehension,
asignacion, decorador, llamada a funcion no autorizada, atributo dunder)
levanta `ExpresionInsegura` ANTES de cualquier evaluacion.

Allowlist de nodos:
    Expression, Compare, BoolOp, UnaryOp, IfExp,
    Name (solo en allowed_names o allowed_funcs),
    Constant, Subscript, Slice, Attribute (no dunder),
    Call (solo a allowed_funcs),
    List, Tuple, Dict, Set,
    operadores: And, Or, Not, Eq, NotEq, Lt, LtE, Gt, GtE, In, NotIn,
                USub, UAdd.

Allowlist de funciones llamables:
    len, str, int, float, bool, abs, min, max, sum, any, all, round.

Restriccion adicional: getattr/getitem se ejecutan en Python real pero el
visitor rechaza atributos que empiezan con `_` (no acceso a dunders).
"""

from __future__ import annotations

import ast
import operator as _op
from typing import Any, Mapping


class ExpresionInsegura(ValueError):
    """La expresion contiene constructos no permitidos (dunder, lambda, etc.)."""


class ExpresionInvalida(ValueError):
    """La expresion no parsea o no se evalua (NameError, AttributeError, etc.)."""


# =============================================================================
# Allowlists
# =============================================================================


_ALLOWED_NODES: frozenset[type] = frozenset(
    [
        ast.Expression,
        ast.Compare,
        ast.BoolOp,
        ast.UnaryOp,
        ast.IfExp,
        ast.Name,
        ast.Constant,
        ast.Load,
        ast.Subscript,
        ast.Slice,
        ast.Attribute,
        ast.Call,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Set,
        # Operators
        ast.And,
        ast.Or,
        ast.Not,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.USub,
        ast.UAdd,
        ast.Is,
        ast.IsNot,
    ]
)

_ALLOWED_FUNCS: dict[str, Any] = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "any": any,
    "all": all,
    "round": round,
}

_CMP_OPS = {
    ast.Eq: _op.eq,
    ast.NotEq: _op.ne,
    ast.Lt: _op.lt,
    ast.LtE: _op.le,
    ast.Gt: _op.gt,
    ast.GtE: _op.ge,
    ast.Is: _op.is_,
    ast.IsNot: _op.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


# =============================================================================
# API publica
# =============================================================================


class SafeExpressionEvaluator:
    """Evalua expresiones contra un namespace fijo de nombres permitidos.

    Args:
        allowed_names: nombres de variables que la expresion puede referenciar
            (ej: {"context"}). Cualquier `Name` fuera de este set + las
            funciones del allowlist levanta ExpresionInsegura.

    Uso:
        evaluator = SafeExpressionEvaluator({"context"})
        evaluator.validate("context.tipo_sku == 'existing'")
        result = evaluator.evaluate("context.x > 5", {"context": ctx})
    """

    def __init__(self, allowed_names: set[str]) -> None:
        self.allowed_names = frozenset(allowed_names)

    def validate(self, expr: str) -> ast.Expression:
        """Parsea y valida estructuralmente la expresion. NO la evalua.

        Returns:
            ast.Expression validado, listo para evaluar.

        Raises:
            ExpresionInvalida: si no parsea como expresion Python.
            ExpresionInsegura: si contiene constructos no permitidos.
        """
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise ExpresionInvalida(f"No parsea: {expr!r} ({e.msg})") from e

        for node in ast.walk(tree):
            if type(node) not in _ALLOWED_NODES:
                raise ExpresionInsegura(
                    f"Nodo {type(node).__name__} no permitido en {expr!r}"
                )
            # Atributos dunder bloqueados
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                raise ExpresionInsegura(
                    f"Atributo {node.attr!r} no permitido (dunder/private) en {expr!r}"
                )
            # Calls: solo Name -> allowed_funcs
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name):
                    raise ExpresionInsegura(
                        f"Call con funcion no-Name no permitido en {expr!r}"
                    )
                if node.func.id not in _ALLOWED_FUNCS:
                    raise ExpresionInsegura(
                        f"Call a {node.func.id!r} no permitido en {expr!r}. "
                        f"Permitidos: {sorted(_ALLOWED_FUNCS)}"
                    )
            # Names: deben estar en allowed_names o ser una funcion permitida
            if isinstance(node, ast.Name):
                if node.id not in self.allowed_names and node.id not in _ALLOWED_FUNCS:
                    raise ExpresionInsegura(
                        f"Nombre {node.id!r} no permitido en {expr!r}. "
                        f"Permitidos: {sorted(self.allowed_names)} + funciones"
                    )

        return tree

    def evaluate(self, expr: str, namespace: Mapping[str, Any]) -> Any:
        """Valida y evalua la expresion contra el namespace dado.

        Args:
            expr: la expresion a evaluar.
            namespace: dict con nombres permitidos -> valores.

        Returns:
            resultado de la evaluacion.

        Raises:
            ExpresionInsegura, ExpresionInvalida: en parse/validation.
            ExpresionInvalida: si la evaluacion falla por NameError,
                AttributeError, KeyError, IndexError, TypeError.
        """
        tree = self.validate(expr)
        try:
            return _eval_node(tree.body, namespace)
        except (NameError, AttributeError, KeyError, IndexError, TypeError) as e:
            raise ExpresionInvalida(
                f"Error evaluando {expr!r}: {type(e).__name__}: {e}"
            ) from e


# =============================================================================
# AST walker (sin eval())
# =============================================================================


def _eval_node(node: ast.AST, ns: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in ns:
            return ns[node.id]
        if node.id in _ALLOWED_FUNCS:
            return _ALLOWED_FUNCS[node.id]
        raise NameError(f"Nombre {node.id!r} no disponible")

    if isinstance(node, ast.Attribute):
        target = _eval_node(node.value, ns)
        if node.attr.startswith("_"):
            raise AttributeError(f"Atributo {node.attr!r} bloqueado")
        return getattr(target, node.attr)

    if isinstance(node, ast.Subscript):
        target = _eval_node(node.value, ns)
        key = _eval_node(node.slice, ns)
        return target[key]

    if isinstance(node, ast.Slice):
        lo = _eval_node(node.lower, ns) if node.lower else None
        hi = _eval_node(node.upper, ns) if node.upper else None
        st = _eval_node(node.step, ns) if node.step else None
        return slice(lo, hi, st)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, ns)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise ExpresionInsegura(f"UnaryOp {type(node.op).__name__} no soportado")

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for v in node.values:
                result = _eval_node(v, ns)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            for v in node.values:
                result = _eval_node(v, ns)
                if result:
                    return result
            return result
        raise ExpresionInsegura(f"BoolOp {type(node.op).__name__} no soportado")

    if isinstance(node, ast.Compare):
        # Soporta comparaciones encadenadas: a < b < c
        left = _eval_node(node.left, ns)
        for op_node, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, ns)
            op_fn = _CMP_OPS.get(type(op_node))
            if op_fn is None:
                raise ExpresionInsegura(
                    f"Operador comparacion {type(op_node).__name__} no soportado"
                )
            if not op_fn(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.IfExp):
        cond = _eval_node(node.test, ns)
        return _eval_node(node.body if cond else node.orelse, ns)

    if isinstance(node, ast.Call):
        # Validacion adicional aunque ya filtramos en validate()
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ExpresionInsegura("Call no permitido")
        fn = _ALLOWED_FUNCS[node.func.id]
        args = [_eval_node(a, ns) for a in node.args]
        if node.keywords:
            kwargs = {kw.arg: _eval_node(kw.value, ns) for kw in node.keywords if kw.arg}
            return fn(*args, **kwargs)
        return fn(*args)

    if isinstance(node, ast.List):
        return [_eval_node(e, ns) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, ns) for e in node.elts)
    if isinstance(node, ast.Set):
        return {_eval_node(e, ns) for e in node.elts}
    if isinstance(node, ast.Dict):
        return {
            _eval_node(k, ns): _eval_node(v, ns)
            for k, v in zip(node.keys, node.values)
            if k is not None
        }

    raise ExpresionInsegura(f"Nodo {type(node).__name__} no soportado en evaluacion")
