"""Safe template expressions: ``{{ input.items[0].name | upper }}``.

There is deliberately no eval. An expression is a dotted path over plain JSON
values (dict/list only, never attribute access) or a literal, optionally piped
through allow-listed filters. Unknown filters raise ``ExpressionError``.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

TEMPLATE_RE = re.compile(r"\{\{\s*((?:(?!\}\}).)*?)\s*\}\}", re.DOTALL)
_PATH_TOKEN_RE = re.compile(r"""\s*(?:([A-Za-z_][\w-]*)|\[\s*(-?\d+)\s*\]|\[\s*(?:"([^"]*)"|'([^']*)')\s*\]|(\.))""")
_MAX_EXPRESSION_LENGTH = 500


class ExpressionError(ValueError):
    pass


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _to_number(value: Any) -> float | int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        cleaned = str(value).strip().replace(",", "")
        cleaned = re.sub(r"^[£$€]", "", cleaned)
        number = float(cleaned)
    except (TypeError, ValueError) as exc:
        raise ExpressionError(f"Cannot convert {value!r} to a number") from exc
    return int(number) if number.is_integer() else number


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _numeric_list(value: Any) -> list[float]:
    return [_to_number(v) for v in _as_list(value) if v not in (None, "")]


FILTERS: dict[str, Callable[..., Any]] = {
    "upper": lambda v: _stringify(v).upper(),
    "lower": lambda v: _stringify(v).lower(),
    "trim": lambda v: _stringify(v).strip(),
    "length": lambda v: len(v) if isinstance(v, (list, dict, str)) else (0 if v is None else 1),
    "default": lambda v, d="": d if v in (None, "", [], {}) else v,
    "json": lambda v: json.dumps(v, ensure_ascii=False, default=str),
    "string": _stringify,
    "number": _to_number,
    "round": lambda v, n=0: round(_to_number(v), int(n)),
    "first": lambda v: (_as_list(v) or [None])[0],
    "last": lambda v: (_as_list(v) or [None])[-1],
    "join": lambda v, sep=", ": str(sep).join(_stringify(i) for i in _as_list(v)),
    "split": lambda v, sep=",": _stringify(v).split(str(sep)),
    "sum": lambda v: sum(_numeric_list(v)),
    "avg": lambda v: (sum(n) / len(n)) if (n := _numeric_list(v)) else 0,
    "min": lambda v: min(_numeric_list(v), default=None),
    "max": lambda v: max(_numeric_list(v), default=None),
    "keys": lambda v: list(v.keys()) if isinstance(v, dict) else [],
    "values": lambda v: list(v.values()) if isinstance(v, dict) else [],
    "pluck": lambda v, k: [i.get(k) if isinstance(i, dict) else None for i in _as_list(v)],
    "truncate": lambda v, n=100: _stringify(v)[: int(n)],
    "replace": lambda v, a, b="": _stringify(v).replace(str(a), str(b)),
}


def _split_top(text: str, sep: str) -> list[str]:
    """Split on ``sep`` outside quotes and brackets."""
    parts, buf, quote, depth = [], [], None, 0
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts]


def _literal(token: str) -> tuple[bool, Any]:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return True, token[1:-1]
    if token in ("true", "false"):
        return True, token == "true"
    if token in ("null", "none"):
        return True, None
    if re.fullmatch(r"-?\d+", token):
        return True, int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return True, float(token)
    return False, None


def parse_path(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    pos = 0
    while pos < len(path):
        m = _PATH_TOKEN_RE.match(path, pos)
        if not m or m.end() == pos:
            raise ExpressionError(f"Invalid expression path: {path!r}")
        pos = m.end()
        if m.group(1) is not None:
            tokens.append(m.group(1))
        elif m.group(2) is not None:
            tokens.append(int(m.group(2)))
        elif m.group(3) is not None or m.group(4) is not None:
            tokens.append(m.group(3) if m.group(3) is not None else m.group(4))
    return tokens


def resolve_path(path: str, scope: dict[str, Any]) -> Any:
    current: Any = scope
    for token in parse_path(path):
        if isinstance(current, dict):
            current = current.get(token) if isinstance(token, str) else current.get(str(token))
        elif isinstance(current, list) and isinstance(token, int):
            current = current[token] if -len(current) <= token < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def evaluate(expression: str, scope: dict[str, Any]) -> Any:
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ExpressionError("Expression is too long")
    parts = _split_top(expression, "|")
    is_lit, value = _literal(parts[0])
    if not is_lit:
        value = resolve_path(parts[0], scope)
    for flt in parts[1:]:
        name, _, raw_args = flt.partition(":")
        name = name.strip()
        func = FILTERS.get(name)
        if func is None:
            raise ExpressionError(f"Unknown filter '{name}'. Allowed: {', '.join(sorted(FILTERS))}")
        args = []
        if raw_args.strip():
            for arg in _split_top(raw_args, ","):
                arg_lit, arg_val = _literal(arg)
                args.append(arg_val if arg_lit else resolve_path(arg, scope))
        try:
            value = func(value, *args)
        except ExpressionError:
            raise
        except (TypeError, ValueError, AttributeError) as exc:
            raise ExpressionError(f"Filter '{name}' failed: {exc}") from exc
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def render(value: Any, scope: dict[str, Any]) -> Any:
    """Render templates in any JSON value. A string that is exactly one
    expression keeps the value's type; embedded expressions are stringified."""
    if isinstance(value, str):
        if "{{" not in value:
            return value
        whole = TEMPLATE_RE.fullmatch(value.strip())
        if whole:
            return evaluate(whole.group(1), scope)
        return TEMPLATE_RE.sub(lambda m: _stringify(evaluate(m.group(1), scope)), value)
    if isinstance(value, dict):
        return {k: render(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, scope) for v in value]
    return value


def find_expressions(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.extend(TEMPLATE_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found.extend(find_expressions(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(find_expressions(v))
    return found


# --------------------------------------------------------------- conditions
def _cmp_pair(left: Any, right: Any) -> tuple[Any, Any]:
    try:
        return _to_number(left), _to_number(right)
    except ExpressionError:
        return _stringify(left), _stringify(right)


def _is_empty(v: Any) -> bool:
    return v in (None, "", [], {})


def _contains(left: Any, right: Any) -> bool:
    if isinstance(left, (list, dict)):
        return right in left
    return _stringify(right).lower() in _stringify(left).lower()


def _loose_equal(left: Any, right: Any) -> bool:
    a, b = _cmp_pair(left, right)
    if isinstance(a, str):
        return a.strip().lower() == b.strip().lower()
    return a == b


def _matches(left: Any, right: Any) -> bool:
    import regex  # local: third-party regex supports a hard timeout (ReDoS guard)

    try:
        return bool(regex.search(_stringify(right), _stringify(left)[:100_000], timeout=1))
    except TimeoutError as exc:
        raise ExpressionError("Regular expression timed out") from exc
    except regex.error as exc:
        raise ExpressionError(f"Invalid regular expression: {exc}") from exc


def _ordered(op: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    def compare(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return False
        a, b = _cmp_pair(left, right)
        return op(a, b)

    return compare


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "equals": _loose_equal,
    "not_equals": lambda l, r: not _loose_equal(l, r),
    "contains": _contains,
    "not_contains": lambda l, r: not _contains(l, r),
    "starts_with": lambda l, r: _stringify(l).lower().startswith(_stringify(r).lower()),
    "ends_with": lambda l, r: _stringify(l).lower().endswith(_stringify(r).lower()),
    "gt": _ordered(lambda a, b: a > b),
    "gte": _ordered(lambda a, b: a >= b),
    "lt": _ordered(lambda a, b: a < b),
    "lte": _ordered(lambda a, b: a <= b),
    "is_empty": lambda l, _r: _is_empty(l),
    "is_not_empty": lambda l, _r: not _is_empty(l),
    "is_true": lambda l, _r: l is True or _stringify(l).lower() == "true",
    "is_false": lambda l, _r: l is False or _stringify(l).lower() == "false",
    "matches": _matches,
}


def evaluate_conditions(conditions: list[dict], combine: str, scope: dict[str, Any]) -> tuple[bool, list[dict]]:
    """Render and evaluate condition rows. Returns (result, per-row details)."""
    details = []
    for row in conditions:
        op = row.get("operator", "equals")
        func = OPERATORS.get(op)
        if func is None:
            raise ExpressionError(f"Unknown operator '{op}'")
        left = render(row.get("left"), scope)
        right = render(row.get("right"), scope)
        details.append({"left": left, "operator": op, "right": right, "result": bool(func(left, right))})
    results = [d["result"] for d in details]
    outcome = any(results) if combine == "any" else all(results)
    return outcome, details
