"""Rule-based stand-in for the AI planner, used when no provider key is configured.

It is a keyword matcher, not a model, and the UI labels its proposals as such. It
produces the same plan shape as a real provider, so proposals go through the same
validator and review flow.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from ..engine.registry import get_spec

UNSUPPORTED = {
    "slack": "Slack",
    "microsoft teams": "Microsoft Teams",
    "discord": "Discord",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "sms": "SMS",
    "twilio": "Twilio",
    "salesforce": "Salesforce",
    "hubspot": "HubSpot",
    "stripe": "Stripe",
    "shopify": "Shopify",
    "jira": "Jira",
    "notion": "Notion",
    "google sheets": "Google Sheets",
    "google drive": "Google Drive",
    "dropbox": "Dropbox",
    "airtable": "Airtable",
    "excel": "Excel files",
    "pdf": "PDF parsing",
    "s3": "Amazon S3",
}
_SAMPLE_INVOICE = (
    "Invoice number: INV-2041\nSupplier name: Northwind Traders\nAmount: £1,240.50\nDue date: 2027-02-14\n"
    "Please remit payment by the due date."
)


class _Plan:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.tail: tuple[str, str] | None = None
        self.setup: list[str] = []
        self.notes: list[str] = []

    def add(self, node_id: str, node_type: str, name: str, config: dict, description: str = "", port: str | None = None) -> str:
        self.nodes.append({"id": node_id, "type": node_type, "name": name, "description": description or get_spec(node_type).description, "config": config, "on_error": "stop"})
        if self.tail:
            self.edges.append({"source": self.tail[0], "source_port": port or self.tail[1], "target": node_id})
        default_port = {"logic.if": "true", "data.validate": "valid"}.get(node_type, "main")
        self.tail = (node_id, default_port)
        return node_id


def _extract_fields(prompt: str) -> list[str]:
    match = re.search(r"\bextract(?:s|ing)?\s+(?:the\s+|their\s+|all\s+)?(.+?)(?:,\s*(?:save|store|and\s+(?:save|store|notify|send))|\s+and\s+(?:save|store|notify|send)|\s+then\b|[.;]|$)", prompt, re.IGNORECASE)
    if not match:
        return []
    fields = []
    for part in re.split(r",|\band\b", match.group(1)):
        words = re.sub(r"[^a-zA-Z0-9 ]", "", part).strip().lower().split()
        words = [w for w in words if w not in ("the", "their", "its", "a", "an", "from", "of")]
        if words and len(words) <= 4:
            fields.append("_".join(words))
    return fields[:12]


def _threshold(prompt: str) -> tuple[str, str] | None:
    match = re.search(r"(?:exceed|exceeds|over|above|greater than|more than|at least)\s+[£$€]?\s?(\d[\d,]*(?:\.\d+)?)", prompt, re.IGNORECASE)
    if match:
        return ("gt", match.group(1).replace(",", ""))
    match = re.search(r"(?:below|under|less than)\s+[£$€]?\s?(\d[\d,]*(?:\.\d+)?)", prompt, re.IGNORECASE)
    if match:
        return ("lt", match.group(1).replace(",", ""))
    return None


def _collection(prompt: str) -> str:
    for word, name in (("invoice", "invoices"), ("ticket", "tickets"), ("customer", "customers"), ("order", "orders"), ("lead", "leads")):
        if word in prompt:
            return name
    return "records"


def _labels(prompt: str) -> list[str]:
    if "priorit" in prompt:
        return ["low", "medium", "high"]
    if "account type" in prompt or "customer" in prompt:
        return ["personal", "business", "enterprise"]
    if "sentiment" in prompt:
        return ["positive", "neutral", "negative"]
    if "support" in prompt or "ticket" in prompt:
        return ["billing", "technical", "general"]
    return ["category_a", "category_b", "other"]


def plan_from_prompt(prompt: str) -> dict[str, Any]:
    text = prompt.lower()
    plan = _Plan()
    unsupported: list[str] = []
    for key, label in UNSUPPORTED.items():
        if re.search(rf"\b{re.escape(key)}\b", text):
            unsupported.append(f"{label} has no built-in integration. If it has a public API, you could call it with an HTTP Request node.")

    # ------- trigger
    is_schedule = bool(re.search(r"\b(every (day|hour|week|morning|night|monday|minute)|daily|hourly|weekly|on a schedule|scheduled)\b", text))
    is_webhook = bool(re.search(r"\b(webhook|receives?|incoming|when a|when an|whenever|arrives?|registered|new (\w+ )?(customers?|tickets?|orders?|leads?|emails?|users?))\b", text))
    wants_email_in = bool(re.search(r"\b(email|e-mail|mail)\b.{0,30}\b(arrives?|received|comes in|inbox)\b|\b(new|incoming) (email|e-mail)\b", text))
    wants_upload = bool(re.search(r"\bupload", text))
    sample_text = "Customer reports they cannot log in to their account and needs help urgently."
    if "invoice" in text:
        sample_text = _SAMPLE_INVOICE
    wants_csv = "csv" in text
    wants_json = bool(re.search(r"\b(json|payload|validat)", text))
    sample: dict[str, Any] = {"text": sample_text}
    if wants_csv:
        sample = {"csv": "name,email,amount\nAda,ada@example.com,120\nGrace,,75\nAlan,alan@example.com,"}
    elif wants_json:
        sample = {"name": "Ada Lovelace", "email": "ada@example.com", "text": sample_text}
    elif "customer" in text and "regist" in text:
        sample = {"name": "Ada Lovelace", "email": "ada@analytical.co.uk", "company": "Analytical Engines Ltd", "text": "Ada Lovelace registered from Analytical Engines Ltd, a company of 40 employees."}

    if wants_email_in:
        unsupported.append("FlowForge has no inbound email trigger. This plan uses a Webhook Trigger; point your email provider's inbound-parse webhook at it.")
    if wants_upload:
        unsupported.append("File uploads are not supported. This plan accepts CSV text in the request instead.")

    if is_schedule:
        schedule = "hourly" if re.search(r"hour", text) else "weekly" if re.search(r"week|monday", text) else "daily"
        plan.add("schedule", "trigger.schedule", "Schedule", {"schedule_type": schedule, "hour": 9, "minute": 0, "timezone": "UTC"})
        src, root = "{{ input }}", "trigger"
    elif is_webhook or wants_email_in or wants_upload:
        plan.add("webhook", "trigger.webhook", "Incoming Webhook", {"auth_mode": "hmac", "required_fields": [], "sample_body": sample})
        src, root = "{{ trigger.body }}", "trigger.body"
    else:
        plan.add("manual", "trigger.manual", "Manual Start", {"sample_data": sample})
        src, root = "{{ trigger }}", "trigger"
    text_expr = "{{ " + root + ".text }}"
    processing: list[str] = []
    conditions: list[str] = []
    integrations: list[str] = []
    recognised = False

    # ------- fetch
    monitor = bool(re.search(r"\b(monitor|availability|uptime|is .* (up|down)|check (the |a |my )?(website|site|url))\b", text))
    url_match = re.search(r"https?://[^\s,]+", prompt)
    if monitor or re.search(r"\b(http request|call (an |the )?api|fetch|get data from)\b", text) or url_match:
        recognised = True
        plan.add("http", "integration.http", "Fetch URL", {"method": "GET", "url": url_match.group(0) if url_match else "https://example.com", "fail_on_error_status": False, "timeout_seconds": 15, "query": [], "headers": []})
        processing.append("Make an HTTP GET request")
        integrations.append("HTTP Request (built in)")
        if monitor:
            conditions.append("Is the response status below 400?")
            plan.add("is_up", "logic.if", "Site is down?", {"conditions": [{"left": "{{ input.status }}", "operator": "gte", "right": "400"}], "combine": "all"})

    # ------- parse
    if wants_csv:
        recognised = True
        plan.add("parse_csv", "data.parse_csv", "Parse CSV", {"source": "{{ " + root + ".csv }}", "delimiter": ","})
        processing.append("Parse CSV text and detect missing values")
    if wants_json:
        recognised = True
        plan.add(
            "validate",
            "data.validate",
            "Validate Payload",
            {"source": src, "rules": [{"field": "name", "type": "string", "required": True}, {"field": "email", "type": "email", "required": True}]},
        )
        processing.append("Validate the JSON payload")
        conditions.append("Is the payload valid? Invalid payloads stop on the Invalid branch.")

    # ------- AI
    fields = _extract_fields(prompt)
    if "extract" in text:
        recognised = True
        fields = fields or ["title", "date", "amount"]
        plan.add("extract", "ai.extract", "Extract Fields", {"text": text_expr, "fields": fields})
        processing.append(f"Extract fields: {', '.join(fields)}")
        integrations.append("AI provider (demo mode until configured)")
    if re.search(r"\b(classif|categori[sz]e|assign (a )?priority|priority|sentiment|account type|triage)", text):
        recognised = True
        labels = _labels(text)
        plan.add("classify", "ai.classify", "Classify", {"text": text_expr, "labels": labels})
        processing.append(f"Classify as {', '.join(labels)}")
        integrations.append("AI provider (demo mode until configured)")
    if re.search(r"\bsummar", text):
        recognised = True
        summarize_source = text_expr if not wants_csv else '{{ nodes["Parse CSV"].rows | json }}'
        plan.add("summarize", "ai.summarize", "Summarise", {"text": summarize_source, "max_sentences": 3})
        processing.append("Summarise the text")
        integrations.append("AI provider (demo mode until configured)")
    if re.search(r"\b(generate|write|draft|create)\b.{0,40}\b(message|report|reply|response|email|welcome|text)\b", text):
        recognised = True
        if wants_csv:
            prompt_text = 'Write a short data quality report. Rows: {{ nodes["Parse CSV"].row_count }}. Missing values: {{ nodes["Parse CSV"].missing_count }}. Details: {{ nodes["Parse CSV"].missing | json }}'
        elif "welcome" in text:
            prompt_text = "Write a short, friendly welcome message for {{ " + root + ".name }}."
        else:
            prompt_text = "Write a short message based on this: " + text_expr
        plan.add("generate", "ai.generate", "Generate Text", {"prompt": prompt_text, "max_tokens": 1024})
        processing.append("Generate a message with AI")
        integrations.append("AI provider (demo mode until configured)")

    # ------- condition
    threshold = _threshold(prompt)
    if threshold:
        recognised = True
        op, value = threshold
        field = "{{ input.data.amount }}" if "extract" in text else "{{ input.amount }}"
        plan.add("check_threshold", "logic.if", "Check Threshold", {"conditions": [{"left": field, "operator": op, "right": value}], "combine": "all"})
        conditions.append(f"Is the amount {'above' if op == 'gt' else 'below'} {value}?")

    # ------- store
    if re.search(r"\b(save|store|database|persist|record it|insert)\b", text):
        recognised = True
        data_expr = "{{ input.data }}" if "extract" in text else "{{ input }}"
        plan.add("store", "integration.database", "Save Record", {"operation": "insert", "collection": _collection(text), "data": data_expr})
        processing.append(f"Save to the '{_collection(text)}' collection")
        integrations.append("Built-in data store")

    # ------- notify
    if re.search(r"\b(notify|notification|alert|send (me |an? )?(email|mail|message)|email me|e-mail me)\b", text):
        recognised = True
        plan.add(
            "notify",
            "integration.email",
            "Send Notification",
            {"to": "you@example.com", "subject": "FlowForge: {{ workflow.name }}", "body": "A workflow step completed.\n\n{{ input | json }}"},
        )
        processing.append("Send an email notification")
        integrations.append("SMTP email (needs a credential)")
        plan.setup.append("Create an SMTP credential and select it on 'Send Notification', then set the recipient address.")

    feasible = recognised
    if not recognised:
        unsupported.append("Demo mode could not map this request onto supported nodes. Configure an AI provider for full natural-language understanding, or start from a template.")
    name_words = re.sub(r"[^\w\s]", "", prompt).split()[:6]
    trigger_label = plan.nodes[0]["name"]
    return {
        "feasible": feasible,
        "analysis": {
            "summary": "Rule-based demo analysis of your request. No AI model was called.",
            "triggers": [trigger_label],
            "processing": processing,
            "conditions": conditions,
            "integrations": sorted(set(integrations)),
        },
        "unsupported_requirements": unsupported,
        "required_setup": plan.setup,
        "workflow_name": " ".join(name_words).capitalize() or "Generated workflow",
        "workflow_description": prompt[:500],
        "changes": [],
        "nodes": plan.nodes if feasible else [],
        "edges": plan.edges if feasible else [],
    }


def _terminal_nodes(definition: dict) -> list[str]:
    sources = {e["source"] for e in definition.get("edges", [])}
    return [n["id"] for n in definition.get("nodes", []) if n["id"] not in sources]


def _unique_id(definition: dict, base: str) -> str:
    ids = {n["id"] for n in definition.get("nodes", [])}
    if base not in ids:
        return base
    i = 2
    while f"{base}_{i}" in ids:
        i += 1
    return f"{base}_{i}"


def _default_port(definition: dict, node_id: str) -> str:
    node = next(n for n in definition["nodes"] if n["id"] == node_id)
    spec = get_spec(node["type"])
    ports = spec.output_ports(node.get("config", {})) if spec else []
    return ports[0].id if ports else "main"


def _as_plan(definition: dict, name: str, changes: list[str], feasible: bool = True, unsupported: list[str] | None = None, setup: list[str] | None = None) -> dict:
    return {
        "feasible": feasible,
        "analysis": {"summary": "Rule-based demo edit. No AI model was called.", "triggers": [], "processing": [], "conditions": [], "integrations": []},
        "unsupported_requirements": unsupported or [],
        "required_setup": setup or [],
        "workflow_name": name,
        "workflow_description": "",
        "changes": changes,
        "nodes": definition["nodes"],
        "edges": definition["edges"],
    }


def modify_plan(instruction: str, definition: dict, name: str) -> dict:
    text = instruction.lower()
    d = copy.deepcopy(definition)
    d.setdefault("nodes", [])
    d.setdefault("edges", [])
    for n in d["nodes"]:
        n.setdefault("config", {})

    for key, label in UNSUPPORTED.items():
        if re.search(rf"\b{re.escape(key)}\b", text):
            return _as_plan(d, name, [], unsupported=[f"{label} has no built-in integration."])

    if re.search(r"\b(email|notification|notify|alert)\b", text):
        new_id = _unique_id(d, "notify")
        terminals = _terminal_nodes(d)
        d["nodes"].append({"id": new_id, "type": "integration.email", "name": "Send Notification", "description": "Emails you when the workflow reaches this point.", "config": {"to": "you@example.com", "subject": "FlowForge: {{ workflow.name }}", "body": "The workflow finished this step.\n\n{{ input | json }}"}, "settings": {"on_error": "stop"}, "position": {"x": 0, "y": 0}})
        for t in terminals:
            d["edges"].append({"id": f"e_{t}_{new_id}", "source": t, "source_port": _default_port(d, t), "target": new_id, "target_port": "main"})
        return _as_plan(d, name, [f"Added a Send Notification email step after: {', '.join(terminals)}"], setup=["Create an SMTP credential and select it on 'Send Notification'."])

    threshold = _threshold(instruction)
    if threshold or re.search(r"\b(condition|check whether|if the)\b", text):
        op, value = threshold or ("gt", "0")
        field = re.search(r"\b(amount|total|price|score|count|status)\b", text)
        field_name = field.group(1) if field else "amount"
        non_triggers = [n for n in d["nodes"] if not (get_spec(n["type"]) and get_spec(n["type"]).is_trigger)]
        if not non_triggers:
            return _as_plan(d, name, [], unsupported=["Add at least one step after the trigger first."])
        # Insert before the last step so the existing action is what the condition guards.
        target = next((n for n in reversed(non_triggers) if n["id"] in _terminal_nodes(d)), non_triggers[-1])
        new_id = _unique_id(d, "check_condition")
        has_extract = any(n["type"] == "ai.extract" for n in d["nodes"])
        left = f'{{{{ nodes["{next(n["name"] for n in d["nodes"] if n["type"] == "ai.extract")}"].data.{field_name} }}}}' if has_extract else f"{{{{ input.{field_name} }}}}"
        d["nodes"].append({"id": new_id, "type": "logic.if", "name": f"Check {field_name}", "description": "Only continues when the condition holds.", "config": {"conditions": [{"left": left, "operator": op, "right": value}], "combine": "all"}, "settings": {"on_error": "stop"}, "position": {"x": 0, "y": 0}})
        for e in d["edges"]:
            if e["target"] == target["id"]:
                e["target"] = new_id
        d["edges"].append({"id": f"e_{new_id}_{target['id']}", "source": new_id, "source_port": "true", "target": target["id"], "target_port": "main"})
        return _as_plan(d, name, [f"Added an IF condition on {field_name} ({op} {value}) before '{target['name']}'"])

    if re.search(r"\berror\b|\bfailure\b|\bfallback\b", text):
        risky = [n for n in d["nodes"] if n["type"].startswith(("integration.", "ai."))]
        if not risky:
            return _as_plan(d, name, [], unsupported=["This workflow has no external or AI steps that need an error branch."])
        handler_id = _unique_id(d, "handle_error")
        d["nodes"].append({"id": handler_id, "type": "integration.database", "name": "Log Failure", "description": "Stores failure details in the data store.", "config": {"operation": "insert", "collection": "workflow_errors", "data": "{{ input }}"}, "settings": {"on_error": "continue"}, "position": {"x": 0, "y": 0}})
        for n in risky:
            n.setdefault("settings", {})["on_error"] = "error_branch"
            d["edges"].append({"id": f"e_{n['id']}_err", "source": n["id"], "source_port": "error", "target": handler_id, "target_port": "main"})
        return _as_plan(d, name, [f"Added an error branch from {len(risky)} step(s) that stores failures in the 'workflow_errors' collection"])

    if re.search(r"\bsimplif|\bremove (unneeded|unnecessary|redundant)|\bclean ?up\b", text):
        removable = [n for n in d["nodes"] if n["type"] == "logic.delay" or (n["type"] == "data.set" and not n["config"].get("assignments"))]
        changes = []
        for node in removable:
            in_edges = [e for e in d["edges"] if e["target"] == node["id"]]
            out_edges = [e for e in d["edges"] if e["source"] == node["id"]]
            d["edges"] = [e for e in d["edges"] if e not in in_edges and e not in out_edges]
            for i in in_edges:
                for o in out_edges:
                    d["edges"].append({"id": f"e_{i['source']}_{o['target']}", "source": i["source"], "source_port": i.get("source_port", "main"), "target": o["target"], "target_port": "main"})
            d["nodes"] = [n for n in d["nodes"] if n["id"] != node["id"]]
            changes.append(f"Removed '{node['name']}' (it does not change the data)")
        if not changes:
            return _as_plan(d, name, ["Demo mode found no pass-through steps to remove."])
        return _as_plan(d, name, changes)

    return _as_plan(
        d,
        name,
        [],
        unsupported=["Demo mode understands: add an email notification, add a condition with a threshold, add an error branch, and simplify. Configure an AI provider for other changes."],
    )


def explain(definition: dict, name: str) -> dict:
    """A structural walkthrough derived from the graph itself."""
    nodes = {n["id"]: n for n in definition.get("nodes", [])}
    outgoing: dict[str, list[dict]] = {}
    incoming: dict[str, int] = {i: 0 for i in nodes}
    for e in definition.get("edges", []):
        outgoing.setdefault(e["source"], []).append(e)
        if e["target"] in incoming:
            incoming[e["target"]] += 1
    order, seen = [], set()
    queue = [i for i, c in incoming.items() if c == 0]
    while queue:
        cur = queue.pop(0)
        if cur in seen or cur not in nodes:
            continue
        seen.add(cur)
        order.append(cur)
        queue.extend(e["target"] for e in outgoing.get(cur, []))
    steps, risks = [], []
    for nid in order:
        node = nodes[nid]
        spec = get_spec(node["type"])
        label = spec.label if spec else node["type"]
        branches = [f"{e.get('source_port', 'main')} -> {nodes[e['target']]['name']}" for e in outgoing.get(nid, []) if e.get("source_port", "main") != "main" and e["target"] in nodes]
        step = f"{node['name']} ({label}): {spec.description if spec else ''}"
        if branches:
            step += " Branches: " + ", ".join(branches) + "."
        steps.append(step)
        if spec and spec.has_side_effects({**spec.defaults(), **node.get("config", {})}):
            risks.append(f"{node['name']} changes external state when run for real.")
        if spec and node["type"] == "integration.email" and not node.get("config", {}).get("credential_id"):
            risks.append(f"{node['name']} has no SMTP credential yet.")
    return {
        "summary": f"'{name}' has {len(nodes)} steps and starts with {nodes[order[0]]['name'] if order else 'no trigger'}. (Structural walkthrough generated without an AI model.)",
        "steps": steps,
        "risks": risks,
    }
