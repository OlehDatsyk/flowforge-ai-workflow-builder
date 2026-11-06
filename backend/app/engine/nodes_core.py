"""Trigger, logic and data nodes. All pure application logic: no external services."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

import regex

from .expressions import (
    ExpressionError,
    OPERATORS,
    _stringify,
    _to_number,
    evaluate_conditions,
    render,
)
from .registry import FieldSpec as F
from .registry import NodeError, NodeResult, NodeSpec, PortSpec, register

_OPERATOR_OPTIONS = [
    {"value": k, "label": v}
    for k, v in {
        "equals": "equals",
        "not_equals": "does not equal",
        "contains": "contains",
        "not_contains": "does not contain",
        "starts_with": "starts with",
        "ends_with": "ends with",
        "gt": "greater than",
        "gte": "greater or equal",
        "lt": "less than",
        "lte": "less or equal",
        "is_empty": "is empty",
        "is_not_empty": "is not empty",
        "is_true": "is true",
        "is_false": "is false",
        "matches": "matches regex",
    }.items()
]
assert {o["value"] for o in _OPERATOR_OPTIONS} == set(OPERATORS)

CONDITION_COLUMNS = [
    F("left", "Value", "expression", required=True, placeholder="{{ input.amount }}"),
    F("operator", "Operator", "select", required=True, default="equals", options=_OPERATOR_OPTIONS),
    F("right", "Compare to", "expression", placeholder="500"),
]
COMBINE_FIELD = F(
    "combine",
    "Match",
    "select",
    default="all",
    options=[{"value": "all", "label": "All conditions (AND)"}, {"value": "any", "label": "Any condition (OR)"}],
)


# ------------------------------------------------------------------ triggers
def _manual_trigger(ctx) -> NodeResult:
    if ctx.trigger_data not in (None, {}, ""):
        return NodeResult.main(ctx.trigger_data)
    return NodeResult.main(ctx.config.get("sample_data") or {})


def _webhook_trigger(ctx) -> NodeResult:
    if ctx.trigger_data not in (None, {}, ""):
        return NodeResult.main(ctx.trigger_data)
    return NodeResult.main({"body": ctx.config.get("sample_body") or {}, "headers": {}, "query": {}, "method": "POST"})


def _schedule_trigger(ctx) -> NodeResult:
    data = ctx.trigger_data if ctx.trigger_data not in (None, {}, "") else {}
    return NodeResult.main({"scheduled": True, "triggered_at": datetime.utcnow().isoformat() + "Z", **data})


register(
    NodeSpec(
        type="trigger.manual",
        label="Manual Trigger",
        category="trigger",
        description="Starts the workflow when you press Run or Test. Needs no external setup.",
        icon="play",
        handler=_manual_trigger,
        inputs=[],
        outputs=[PortSpec("main", "Data", "object")],
        is_trigger=True,
        fields=[
            F(
                "sample_data",
                "Input data",
                "json",
                default={},
                help="JSON passed to the next node on a manual run. Reference it as {{ trigger.field }}.",
                no_expressions=True,
            )
        ],
        output_schema={"type": "object", "description": "The input data as configured"},
        planner_hint="Use for on-demand runs. Put realistic example input in sample_data.",
    )
)

register(
    NodeSpec(
        type="trigger.webhook",
        label="Webhook Trigger",
        category="trigger",
        description="Starts the workflow when an authenticated HTTP request reaches its generated endpoint.",
        icon="webhook",
        handler=_webhook_trigger,
        inputs=[],
        outputs=[PortSpec("main", "Request", "object")],
        is_trigger=True,
        fields=[
            F(
                "auth_mode",
                "Request authentication",
                "select",
                default="hmac",
                options=[
                    {"value": "hmac", "label": "HMAC SHA-256 signature (recommended)"},
                    {"value": "token", "label": "Secret token header"},
                    {"value": "none", "label": "None (blocked in production)"},
                ],
                no_expressions=True,
            ),
            F(
                "required_fields",
                "Required body fields",
                "string_list",
                default=[],
                help="Requests whose JSON body is missing any of these are rejected with HTTP 422.",
                no_expressions=True,
            ),
            F(
                "sample_body",
                "Sample body for tests",
                "json",
                default={},
                help="Used when you run or test the workflow from the editor.",
                no_expressions=True,
            ),
        ],
        output_schema={
            "type": "object",
            "properties": {"body": {}, "headers": {"type": "object"}, "query": {"type": "object"}, "method": {"type": "string"}},
        },
        planner_hint="Reference the payload as {{ trigger.body.field }}. Put an example in sample_body.",
    )
)

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
register(
    NodeSpec(
        type="trigger.schedule",
        label="Scheduled Trigger",
        category="trigger",
        description="Runs the workflow once, hourly, daily or weekly. Schedules live in the database and survive restarts.",
        icon="clock",
        handler=_schedule_trigger,
        inputs=[],
        outputs=[PortSpec("main", "Tick", "object")],
        is_trigger=True,
        fields=[
            F(
                "schedule_type",
                "Repeat",
                "select",
                required=True,
                default="daily",
                options=[
                    {"value": "once", "label": "One time"},
                    {"value": "hourly", "label": "Every hour"},
                    {"value": "daily", "label": "Every day"},
                    {"value": "weekly", "label": "Every week"},
                ],
                no_expressions=True,
            ),
            F("run_at", "Run at (ISO date-time)", "string", placeholder="2027-01-15T09:00", visible_if={"schedule_type": ["once"]}, required=True, no_expressions=True),
            F("weekday", "Day", "select", default=0, options=[{"value": i, "label": d} for i, d in enumerate(_WEEKDAYS)], visible_if={"schedule_type": ["weekly"]}, no_expressions=True),
            F("hour", "Hour (0-23)", "number", default=9, min=0, max=23, visible_if={"schedule_type": ["daily", "weekly"]}, no_expressions=True),
            F("minute", "Minute (0-59)", "number", default=0, min=0, max=59, no_expressions=True, visible_if={"schedule_type": ["hourly", "daily", "weekly"]}),
            F("timezone", "Time zone", "string", default="UTC", placeholder="Europe/London", no_expressions=True),
        ],
        output_schema={"type": "object", "properties": {"scheduled": {"type": "boolean"}, "triggered_at": {"type": "string"}}},
    )
)


# --------------------------------------------------------------------- logic
def _if(ctx) -> NodeResult:
    try:
        outcome, details = evaluate_conditions(ctx.config.get("conditions") or [], ctx.config.get("combine", "all"), ctx.scope)
    except ExpressionError as exc:
        raise NodeError(str(exc), "expression") from exc
    ctx.log("conditions", details)
    return NodeResult(outputs={"true" if outcome else "false": ctx.input})


register(
    NodeSpec(
        type="logic.if",
        label="IF Condition",
        category="logic",
        description="Routes data down the True or False branch.",
        icon="git-branch",
        handler=_if,
        outputs=[PortSpec("true", "True"), PortSpec("false", "False")],
        fields=[
            F("conditions", "Conditions", "rows", required=True, default=[{"left": "", "operator": "equals", "right": ""}], columns=CONDITION_COLUMNS, raw=True),
            COMBINE_FIELD,
        ],
        output_schema={"description": "The unchanged input, on the matching port"},
        planner_hint='config.conditions: [{"left":"{{ input.amount }}","operator":"gt","right":"500"}]. Output ports: "true", "false".',
    )
)


def _switch_ports(config: dict) -> list[PortSpec]:
    ports = []
    for i, case in enumerate(config.get("cases") or []):
        label = str((case or {}).get("label") or (case or {}).get("equals") or f"Case {i + 1}")
        ports.append(PortSpec(f"case_{i}", label[:40]))
    ports.append(PortSpec("default", "Default"))
    return ports


def _switch(ctx) -> NodeResult:
    value = ctx.config.get("value")
    for i, case in enumerate(ctx.config.get("cases") or []):
        if OPERATORS["equals"](value, (case or {}).get("equals")):
            return NodeResult(outputs={f"case_{i}": ctx.input})
    return NodeResult(outputs={"default": ctx.input})


register(
    NodeSpec(
        type="logic.switch",
        label="Switch",
        category="logic",
        description="Routes data to the first case that matches a value.",
        icon="split",
        handler=_switch,
        dynamic_outputs=_switch_ports,
        outputs=[PortSpec("default", "Default")],
        fields=[
            F("value", "Value to test", "expression", required=True, placeholder="{{ input.priority }}"),
            F(
                "cases",
                "Cases",
                "rows",
                required=True,
                default=[{"equals": "", "label": ""}],
                columns=[F("equals", "Equals", "expression", required=True), F("label", "Label", "string")],
            ),
        ],
        planner_hint='config.cases: [{"equals":"high","label":"High"}]. Output ports are case_0, case_1, ... and default.',
    )
)


def _filter(ctx) -> NodeResult:
    items = render(ctx.raw_config.get("items", "{{ input }}"), ctx.scope)
    if isinstance(items, dict) and isinstance(items.get("rows"), list):
        items = items["rows"]
    if not isinstance(items, list):
        raise NodeError(f"Filter expected a list but received {type(items).__name__}", "validation")
    kept = []
    try:
        for index, item in enumerate(items):
            scope = {**ctx.scope, "item": item, "index": index}
            ok, _ = evaluate_conditions(ctx.raw_config.get("conditions") or [], ctx.config.get("combine", "all"), scope)
            if ok:
                kept.append(item)
    except ExpressionError as exc:
        raise NodeError(str(exc), "expression") from exc
    ctx.log("filtered", {"received": len(items), "kept": len(kept)})
    return NodeResult.main(kept)


register(
    NodeSpec(
        type="logic.filter",
        label="Filter",
        category="logic",
        description="Keeps only the list items that match your conditions.",
        icon="filter",
        handler=_filter,
        outputs=[PortSpec("main", "Kept items", "array")],
        fields=[
            F("items", "List to filter", "expression", required=True, default="{{ input }}", raw=True),
            F("conditions", "Keep items where", "rows", required=True, default=[{"left": "{{ item.status }}", "operator": "equals", "right": ""}], columns=CONDITION_COLUMNS, raw=True, help="Use {{ item.field }} for the current item."),
            COMBINE_FIELD,
        ],
        output_schema={"type": "array"},
        planner_hint="Use {{ item.field }} inside conditions. Output is an array, so it cannot connect directly to object-only inputs like Map Fields.",
    )
)


def _merge(ctx) -> NodeResult:
    inputs = ctx.inputs
    mode = ctx.config.get("mode", "append")
    if mode == "combine":
        merged: dict = {}
        for value in inputs:
            if isinstance(value, dict):
                merged.update(value)
            else:
                raise NodeError("Merge in Combine mode needs objects on every input", "validation")
        return NodeResult.main(merged)
    if mode == "first":
        return NodeResult.main(inputs[0] if inputs else None)
    out: list = []
    for value in inputs:
        out.extend(value if isinstance(value, list) else [value])
    return NodeResult.main(out)


register(
    NodeSpec(
        type="logic.merge",
        label="Merge",
        category="logic",
        description="Waits for all incoming branches, then combines whatever they produced.",
        icon="merge",
        handler=_merge,
        multi_input=True,
        fields=[
            F(
                "mode",
                "Mode",
                "select",
                default="append",
                options=[
                    {"value": "append", "label": "Append into a list"},
                    {"value": "combine", "label": "Combine objects"},
                    {"value": "first", "label": "Use first branch that ran"},
                ],
                no_expressions=True,
            )
        ],
        planner_hint="Connect 2+ edges into it.",
    )
)


def _delay(ctx) -> NodeResult:
    try:
        seconds = float(ctx.config.get("seconds") or 0)
    except (TypeError, ValueError) as exc:
        raise NodeError("Delay must be a number of seconds", "config") from exc
    limit = ctx.settings.max_delay_seconds
    if seconds < 0 or seconds > limit:
        raise NodeError(f"Delay must be between 0 and {limit} seconds", "config")
    ctx.wait(seconds)
    return NodeResult.main(ctx.input)


register(
    NodeSpec(
        type="logic.delay",
        label="Delay",
        category="logic",
        description="Pauses the execution (status: Waiting). Can be cancelled while waiting.",
        icon="hourglass",
        handler=_delay,
        fields=[F("seconds", "Seconds", "number", required=True, default=5, min=0, max=300)],
        output_schema={"description": "The unchanged input"},
    )
)


def _loop_placeholder(ctx) -> NodeResult:  # executed by the engine itself
    raise NodeError("Loop nodes are driven by the executor", "internal")


register(
    NodeSpec(
        type="logic.loop",
        label="Loop",
        category="logic",
        description="Runs the Each Item branch once per list item (up to a limit), then continues from Done with all results.",
        icon="repeat",
        handler=_loop_placeholder,
        outputs=[PortSpec("body", "Each item", "any"), PortSpec("done", "Done", "array")],
        fields=[
            F("items", "List", "expression", required=True, default="{{ input }}"),
            F("max_iterations", "Maximum iterations", "number", required=True, default=100, min=1, max=1000),
        ],
        output_schema={"type": "array", "description": "On Done: one entry per iteration (the last body node's output)"},
        planner_hint='Output ports: "body" (use {{ item }} and {{ index }}) and "done". Nodes after "body" must not also be reachable from "done".',
    )
)


# ---------------------------------------------------------------------- data
def _set(ctx) -> NodeResult:
    values: dict[str, Any] = {}
    for row in ctx.config.get("assignments") or []:
        key = str((row or {}).get("key") or "").strip()
        if not key:
            raise NodeError("Every variable needs a name", "config")
        values[key] = row.get("value")
    ctx.variables.update(values)
    if ctx.config.get("include_input", True) and isinstance(ctx.input, dict):
        return NodeResult.main({**ctx.input, **values})
    return NodeResult.main(values)


register(
    NodeSpec(
        type="data.set",
        label="Set Variables",
        category="data",
        description="Defines named values. Readable later as {{ vars.name }}.",
        icon="variable",
        handler=_set,
        fields=[
            F("assignments", "Variables", "rows", required=True, default=[{"key": "", "value": ""}], columns=[F("key", "Name", "string", required=True), F("value", "Value", "expression")]),
            F("include_input", "Keep input fields", "boolean", default=True, no_expressions=True),
        ],
        output_schema={"type": "object"},
    )
)

_TRANSFORM_OPS = [
    ("pick", "Keep fields (comma separated)"),
    ("omit", "Remove fields (comma separated)"),
    ("rename", "Rename field -> value"),
    ("set", "Set field = value"),
    ("uppercase", "Uppercase field"),
    ("lowercase", "Lowercase field"),
    ("trim", "Trim field"),
    ("to_number", "Convert field to number"),
    ("to_string", "Convert field to text"),
    ("sort", "Sort list by field (value: asc/desc)"),
    ("limit", "Limit list to value items"),
    ("unique", "Unique list items by field"),
    ("flatten", "Flatten nested lists"),
    ("count", "Count list items"),
    ("sum", "Sum of field"),
    ("avg", "Average of field"),
    ("min", "Minimum of field"),
    ("max", "Maximum of field"),
    ("group_count", "Count list items grouped by field"),
]


def _item_op(item: Any, op: str, fields: list[str], value: Any) -> Any:
    if not isinstance(item, dict):
        raise NodeError(f"'{op}' works on objects, received {type(item).__name__}", "validation")
    out = dict(item)
    if op == "pick":
        return {k: out[k] for k in fields if k in out}
    if op == "omit":
        return {k: v for k, v in out.items() if k not in fields}
    field = fields[0] if fields else ""
    if not field:
        raise NodeError(f"'{op}' needs a field name", "config")
    if op == "rename":
        if field in out:
            out[str(value)] = out.pop(field)
    elif op == "set":
        out[field] = value
    elif field in out:
        current = out[field]
        if op == "uppercase":
            out[field] = _stringify(current).upper()
        elif op == "lowercase":
            out[field] = _stringify(current).lower()
        elif op == "trim":
            out[field] = _stringify(current).strip()
        elif op == "to_string":
            out[field] = _stringify(current)
        elif op == "to_number":
            try:
                out[field] = _to_number(current)
            except ExpressionError as exc:
                raise NodeError(f"Field '{field}': {exc}", "validation") from exc
    return out


def _numbers(data: list, field: str) -> list[float]:
    values = []
    for row in data:
        raw = row.get(field) if isinstance(row, dict) and field else row
        if raw in (None, ""):
            continue
        try:
            values.append(_to_number(raw))
        except ExpressionError:
            continue
    return values


def _apply_transform(data: Any, op: str, field_text: str, value: Any) -> Any:
    fields = [f.strip() for f in field_text.split(",") if f.strip()]
    field = fields[0] if fields else ""
    if op in ("sort", "limit", "unique", "flatten", "count", "sum", "avg", "min", "max", "group_count"):
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            data = data["rows"]
        if not isinstance(data, list):
            raise NodeError(f"'{op}' needs a list, received {type(data).__name__}", "validation")
        if op == "sort":
            def key(row: Any) -> tuple:
                raw = row.get(field) if isinstance(row, dict) else row
                try:
                    return (0, _to_number(raw), "")
                except ExpressionError:
                    return (1, 0, _stringify(raw).lower())

            return sorted(data, key=key, reverse=str(value).lower() == "desc")
        if op == "limit":
            try:
                return data[: max(0, int(value))]
            except (TypeError, ValueError) as exc:
                raise NodeError("'limit' needs a whole number value", "config") from exc
        if op == "unique":
            seen, out = set(), []
            for row in data:
                marker = json.dumps(row.get(field) if isinstance(row, dict) and field else row, sort_keys=True, default=str)
                if marker not in seen:
                    seen.add(marker)
                    out.append(row)
            return out
        if op == "flatten":
            out = []
            for row in data:
                out.extend(row if isinstance(row, list) else [row])
            return out
        if op == "count":
            return {"count": len(data)}
        if op == "group_count":
            groups: dict[str, int] = {}
            for row in data:
                label = _stringify(row.get(field) if isinstance(row, dict) else row) or "(empty)"
                groups[label] = groups.get(label, 0) + 1
            return {"groups": groups, "total": len(data)}
        numbers = _numbers(data, field)
        if op == "sum":
            return {"sum": sum(numbers), "count": len(numbers)}
        if op == "avg":
            return {"avg": (sum(numbers) / len(numbers)) if numbers else None, "count": len(numbers)}
        if op == "min":
            return {"min": min(numbers, default=None), "count": len(numbers)}
        return {"max": max(numbers, default=None), "count": len(numbers)}
    if isinstance(data, list):
        return [_item_op(item, op, fields, value) for item in data]
    return _item_op(data, op, fields, value)


def _transform(ctx) -> NodeResult:
    data = ctx.config.get("source")
    for row in ctx.config.get("operations") or []:
        op = (row or {}).get("operation")
        if op not in dict(_TRANSFORM_OPS):
            raise NodeError(f"Unknown transform operation '{op}'", "config")
        data = _apply_transform(data, op, str(row.get("field") or ""), row.get("value"))
    return NodeResult.main(data)


register(
    NodeSpec(
        type="data.transform",
        label="Transform Data",
        category="data",
        description="Applies a safe, declarative pipeline of operations. No custom code runs.",
        icon="wand",
        handler=_transform,
        fields=[
            F("source", "Source data", "expression", required=True, default="{{ input }}"),
            F(
                "operations",
                "Operations (applied in order)",
                "rows",
                required=True,
                default=[{"operation": "pick", "field": "", "value": ""}],
                columns=[
                    F("operation", "Operation", "select", required=True, default="pick", options=[{"value": k, "label": v} for k, v in _TRANSFORM_OPS]),
                    F("field", "Field", "string"),
                    F("value", "Value", "expression"),
                ],
            ),
        ],
        planner_hint=f"operations[].operation is one of: {', '.join(k for k, _ in _TRANSFORM_OPS)}.",
    )
)


def _parse_json(ctx) -> NodeResult:
    source = ctx.config.get("source")
    if isinstance(source, (dict, list)):
        return NodeResult.main(source)
    if source in (None, ""):
        raise NodeError("Parse JSON received empty input", "validation")
    if len(str(source)) > 5_000_000:
        raise NodeError("JSON text is larger than the 5 MB limit", "validation")
    try:
        return NodeResult.main(json.loads(str(source)))
    except json.JSONDecodeError as exc:
        raise NodeError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}", "validation") from exc


register(
    NodeSpec(
        type="data.parse_json",
        label="Parse JSON",
        category="data",
        description="Turns JSON text into structured data.",
        icon="braces",
        handler=_parse_json,
        fields=[F("source", "JSON text", "expression", required=True, default="{{ input.body }}")],
    )
)


def _parse_csv(ctx) -> NodeResult:
    text = ctx.config.get("source")
    if not isinstance(text, str) or not text.strip():
        raise NodeError("Parse CSV expected CSV text", "validation")
    if len(text) > 5_000_000:
        raise NodeError("CSV text is larger than the 5 MB limit", "validation")
    delimiter = str(ctx.config.get("delimiter") or ",")
    if delimiter == "\\t":
        delimiter = "\t"
    if len(delimiter) != 1:
        raise NodeError("Delimiter must be a single character", "config")
    max_rows = 20_000
    try:
        reader = csv.reader(io.StringIO(text.strip()), delimiter=delimiter)
        table = [row for _, row in zip(range(max_rows + 1), reader)]
    except csv.Error as exc:
        raise NodeError(f"Could not read CSV: {exc}", "validation") from exc
    columns = [c.strip() for c in table[0]]
    rows, missing = [], []
    for number, raw in enumerate(table[1:], start=1):
        row = {col: (raw[i].strip() if i < len(raw) else "") for i, col in enumerate(columns)}
        rows.append(row)
        for col, val in row.items():
            if val == "":
                missing.append({"row": number, "column": col})
    return NodeResult.main(
        {"rows": rows, "columns": columns, "row_count": len(rows), "missing": missing, "missing_count": len(missing)}
    )


register(
    NodeSpec(
        type="data.parse_csv",
        label="Parse CSV",
        category="data",
        description="Reads CSV text into rows and reports missing values.",
        icon="table",
        handler=_parse_csv,
        outputs=[PortSpec("main", "Table", "object")],
        fields=[
            F("source", "CSV text", "expression", required=True, default="{{ input.csv }}"),
            F("delimiter", "Delimiter", "string", default=",", no_expressions=True),
        ],
        output_schema={
            "type": "object",
            "properties": {
                "rows": {"type": "array"},
                "columns": {"type": "array"},
                "row_count": {"type": "number"},
                "missing": {"type": "array"},
                "missing_count": {"type": "number"},
            },
        },
    )
)

_EXTRACT_PATTERNS = {
    "email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "url": r"https?://[^\s<>\"')]+",
    "number": r"-?\d+(?:[.,]\d+)*",
    "date": r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4})\b",
}


def _extract_text(ctx) -> NodeResult:
    text = _stringify(ctx.config.get("source"))[:200_000]
    mode = ctx.config.get("mode", "regex")
    try:
        if mode == "key_value":
            fields = {}
            for line in text.splitlines():
                key, sep, value = line.partition(":")
                if sep and key.strip() and len(key) < 80:
                    fields[regex.sub(r"\s+", "_", key.strip().lower())] = value.strip()
            return NodeResult.main({"fields": fields, "count": len(fields)})
        if mode == "lines":
            matches = [line.strip() for line in text.splitlines() if line.strip()]
        elif mode == "between":
            start, end = ctx.config.get("start") or "", ctx.config.get("end") or ""
            if not start or not end:
                raise NodeError("'Between' mode needs start and end text", "config")
            matches = regex.findall(regex.escape(start) + r"(.*?)" + regex.escape(end), text, regex.DOTALL, timeout=2)
        elif mode == "regex":
            pattern = ctx.config.get("pattern")
            if not pattern:
                raise NodeError("Regex mode needs a pattern", "config")
            if len(pattern) > 500:
                raise NodeError("Pattern is longer than 500 characters", "config")
            found = regex.findall(pattern, text, timeout=2)
            matches = [m if isinstance(m, str) else list(m) for m in found]
        else:
            matches = regex.findall(_EXTRACT_PATTERNS[mode], text, timeout=2)
    except TimeoutError as exc:
        raise NodeError("Text extraction timed out; simplify the pattern", "timeout") from exc
    except regex.error as exc:
        raise NodeError(f"Invalid regular expression: {exc}", "config") from exc
    return NodeResult.main({"matches": matches, "first": matches[0] if matches else None, "count": len(matches)})


register(
    NodeSpec(
        type="data.extract_text",
        label="Extract Text",
        category="data",
        description="Finds emails, URLs, numbers, dates, key: value pairs or regex matches in text.",
        icon="text-search",
        handler=_extract_text,
        outputs=[PortSpec("main", "Matches", "object")],
        fields=[
            F("source", "Text", "expression", required=True, default="{{ input.text }}"),
            F(
                "mode",
                "Extract",
                "select",
                default="regex",
                options=[
                    {"value": "regex", "label": "Regular expression"},
                    {"value": "email", "label": "Email addresses"},
                    {"value": "url", "label": "URLs"},
                    {"value": "number", "label": "Numbers"},
                    {"value": "date", "label": "Dates"},
                    {"value": "key_value", "label": "Key: value lines"},
                    {"value": "between", "label": "Text between markers"},
                    {"value": "lines", "label": "Non-empty lines"},
                ],
                no_expressions=True,
            ),
            F("pattern", "Pattern", "string", visible_if={"mode": ["regex"]}, placeholder=r"INV-\d+", required=True),
            F("start", "Start marker", "string", visible_if={"mode": ["between"]}),
            F("end", "End marker", "string", visible_if={"mode": ["between"]}),
        ],
        output_schema={"type": "object", "properties": {"matches": {"type": "array"}, "first": {}, "count": {"type": "number"}}},
    )
)


def _map_fields(ctx) -> NodeResult:
    source = ctx.input if isinstance(ctx.input, dict) else {}
    out = dict(source) if ctx.config.get("keep_unmapped") else {}
    for row in ctx.config.get("mappings") or []:
        target = str((row or {}).get("target") or "").strip()
        if not target:
            raise NodeError("Every mapping needs a target field", "config")
        out[target] = row.get("source")
    return NodeResult.main(out)


register(
    NodeSpec(
        type="data.map_fields",
        label="Map Fields",
        category="data",
        description="Builds a new object by mapping source values to target field names.",
        icon="arrow-right-left",
        handler=_map_fields,
        inputs=[PortSpec("main", "Object", "object")],
        outputs=[PortSpec("main", "Mapped", "object")],
        fields=[
            F("mappings", "Mappings", "rows", required=True, default=[{"target": "", "source": ""}], columns=[F("target", "Target field", "string", required=True), F("source", "Source value", "expression", placeholder="{{ input.name }}")]),
            F("keep_unmapped", "Keep other input fields", "boolean", default=False, no_expressions=True),
        ],
    )
)

_VALUE_TYPES = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "email": lambda v: isinstance(v, str) and bool(regex.fullmatch(_EXTRACT_PATTERNS["email"], v)),
    "any": lambda _v: True,
}


def _validate(ctx) -> NodeResult:
    data = ctx.config.get("source")
    problems: list[dict] = []
    if not isinstance(data, dict):
        problems.append({"field": "", "problem": f"Expected an object, received {type(data).__name__}"})
        data = {}
    for rule in ctx.config.get("rules") or []:
        name = str((rule or {}).get("field") or "").strip()
        if not name:
            continue
        value = data.get(name)
        if value in (None, ""):
            if rule.get("required", True):
                problems.append({"field": name, "problem": "is required"})
            continue
        kind = rule.get("type") or "any"
        if not _VALUE_TYPES.get(kind, _VALUE_TYPES["any"])(value):
            problems.append({"field": name, "problem": f"must be of type {kind}"})
            continue
        size = len(value) if isinstance(value, (str, list)) else value if not isinstance(value, (dict, bool)) else None
        for bound, label, cmp in (("min", "at least", lambda a, b: a >= b), ("max", "at most", lambda a, b: a <= b)):
            raw = rule.get(bound)
            if raw not in (None, "") and size is not None:
                try:
                    if not cmp(size, float(raw)):
                        problems.append({"field": name, "problem": f"must be {label} {raw}"})
                except (TypeError, ValueError):
                    raise NodeError(f"Rule for '{name}': {bound} must be a number", "config") from None
        pattern = rule.get("pattern")
        if pattern:
            try:
                if not regex.search(str(pattern), _stringify(value), timeout=1):
                    problems.append({"field": name, "problem": "does not match the required pattern"})
            except (TimeoutError, regex.error) as exc:
                raise NodeError(f"Rule for '{name}': bad pattern ({exc})", "config") from exc
    if problems:
        return NodeResult(outputs={"invalid": {"valid": False, "errors": problems, "data": data}})
    return NodeResult(outputs={"valid": data})


register(
    NodeSpec(
        type="data.validate",
        label="Validate Data",
        category="data",
        description="Checks fields against rules and routes to the Valid or Invalid branch.",
        icon="shield-check",
        handler=_validate,
        outputs=[PortSpec("valid", "Valid", "object"), PortSpec("invalid", "Invalid", "object")],
        fields=[
            F("source", "Data to validate", "expression", required=True, default="{{ input }}"),
            F(
                "rules",
                "Rules",
                "rows",
                required=True,
                default=[{"field": "", "type": "string", "required": True}],
                columns=[
                    F("field", "Field", "string", required=True),
                    F("type", "Type", "select", default="string", options=[{"value": k, "label": k} for k in _VALUE_TYPES]),
                    F("required", "Required", "boolean", default=True),
                    F("min", "Min", "string"),
                    F("max", "Max", "string"),
                    F("pattern", "Pattern", "string"),
                ],
            ),
        ],
        output_schema={"description": "valid: the data. invalid: {valid:false, errors:[{field,problem}], data}"},
        planner_hint='Output ports: "valid" and "invalid". rules[].type is string|number|boolean|array|object|email|any.',
    )
)
