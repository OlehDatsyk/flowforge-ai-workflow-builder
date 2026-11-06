"""Built-in templates. Each is a real definition that passes the validator (see tests)."""
from __future__ import annotations


def _n(node_id: str, node_type: str, name: str, config: dict | None = None, description: str = "", on_error: str = "stop") -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "description": description,
        "position": {"x": 0, "y": 0},
        "config": config or {},
        "settings": {"retry": {"max_attempts": 1, "delay_ms": 1000, "backoff": 2.0, "allow_non_idempotent": False}, "timeout_seconds": 30, "on_error": on_error},
    }


def _e(source: str, target: str, port: str = "main") -> dict:
    return {"id": f"e_{source}_{port}_{target}", "source": source, "source_port": port, "target": target, "target_port": "main"}


def _d(nodes: list[dict], edges: list[dict]) -> dict:
    return {"schema_version": 1, "nodes": nodes, "edges": edges}


_EMAIL_TEXT = (
    "Hi team, the Q3 supplier review is moved to Thursday at 10am. Please bring updated cost figures. "
    "Northwind has raised prices by 4 percent, so we need a decision on the renewal before Friday. "
    "Thanks, Priya"
)
_INVOICE_TEXT = "Invoice number: INV-2041\nSupplier name: Northwind Traders\nAmount: 1240.50\nDue date: 2027-02-14\nThanks for your business."
_TICKET = "My account has been charged twice this month and I need a refund urgently. Invoice 8841."
_CSV = "name,email,amount\nAda,ada@example.com,120\nGrace,,75\nAlan,alan@example.com,\nKatherine,katherine@example.com,310"

TEMPLATES: list[dict] = [
    {
        "slug": "ai-email-summarisation",
        "name": "AI Email Summarisation",
        "category": "AI",
        "description": "Accepts forwarded email text through a webhook, summarises it with AI and stores the summary.",
        "required_integrations": ["Webhook (built in)", "AI provider (demo mode without a key)", "Data store (built in)"],
        "expected_behaviour": "Your email provider posts each message to the webhook. The workflow writes a summary and key points to the 'email_summaries' collection. FlowForge has no inbound email connector, so you connect your provider's inbound-parse webhook.",
        "configuration_requirements": [],
        "definition": _d(
            [
                _n("hook", "trigger.webhook", "Forwarded Email", {"auth_mode": "hmac", "required_fields": ["text"], "sample_body": {"from": "priya@example.com", "subject": "Supplier review", "text": _EMAIL_TEXT}}),
                _n("summary", "ai.summarize", "Summarise Email", {"text": "{{ trigger.body.text }}", "max_sentences": 2}),
                _n("map", "data.map_fields", "Build Record", {"mappings": [{"target": "from", "source": "{{ trigger.body.from }}"}, {"target": "subject", "source": "{{ trigger.body.subject }}"}, {"target": "summary", "source": "{{ input.summary }}"}, {"target": "key_points", "source": "{{ input.key_points }}"}]}),
                _n("store", "integration.database", "Save Summary", {"operation": "insert", "collection": "email_summaries", "data": "{{ input }}"}),
            ],
            [_e("hook", "summary"), _e("summary", "map"), _e("map", "store")],
        ),
    },
    {
        "slug": "invoice-data-extraction",
        "name": "Invoice Data Extraction",
        "category": "Finance",
        "description": "Extracts invoice fields from text, checks whether the amount needs review, saves it and emails you about large invoices.",
        "required_integrations": ["Webhook (built in)", "AI provider (demo mode without a key)", "Data store (built in)", "Email (SMTP)"],
        "expected_behaviour": "Each invoice is stored in 'invoices'. Invoices above 500 also send an email. Test runs simulate the database write and the email.",
        "configuration_requirements": ["Create an SMTP credential and select it on 'Notify Finance'", "Set the recipient address on 'Notify Finance'"],
        "definition": _d(
            [
                _n("hook", "trigger.webhook", "Invoice Received", {"auth_mode": "hmac", "required_fields": ["text"], "sample_body": {"text": _INVOICE_TEXT}}),
                _n("extract", "ai.extract", "Extract Invoice Fields", {"text": "{{ trigger.body.text }}", "fields": ["invoice_number", "supplier_name", "amount", "due_date"]}),
                _n("store", "integration.database", "Save Invoice", {"operation": "insert", "collection": "invoices", "data": "{{ input.data }}"}),
                _n("check", "logic.if", "Amount Over 500?", {"conditions": [{"left": '{{ nodes["Extract Invoice Fields"].data.amount }}', "operator": "gt", "right": "500"}], "combine": "all"}),
                _n("email", "integration.email", "Notify Finance", {"to": "finance@example.com", "subject": 'Invoice {{ nodes["Extract Invoice Fields"].data.invoice_number }} needs review', "body": 'Supplier: {{ nodes["Extract Invoice Fields"].data.supplier_name }}\nAmount: {{ nodes["Extract Invoice Fields"].data.amount }}\nDue: {{ nodes["Extract Invoice Fields"].data.due_date }}'}),
            ],
            [_e("hook", "extract"), _e("extract", "store"), _e("store", "check"), _e("check", "email", "true")],
        ),
    },
    {
        "slug": "customer-support-classification",
        "name": "Customer Support Classification",
        "category": "Support",
        "description": "Classifies incoming tickets by topic and routes them to the right queue with a summary.",
        "required_integrations": ["Webhook (built in)", "AI provider (demo mode without a key)", "Data store (built in)"],
        "expected_behaviour": "Tickets are classified as billing, technical or general and stored in the matching collection.",
        "configuration_requirements": [],
        "definition": _d(
            [
                _n("hook", "trigger.webhook", "New Ticket", {"auth_mode": "hmac", "required_fields": ["text"], "sample_body": {"customer": "ada@example.com", "text": _TICKET}}),
                _n("classify", "ai.classify", "Classify Topic", {"text": "{{ trigger.body.text }}", "labels": ["billing", "technical", "general"]}),
                _n("route", "logic.switch", "Route by Topic", {"value": "{{ input.label }}", "cases": [{"equals": "billing", "label": "Billing"}, {"equals": "technical", "label": "Technical"}]}),
                _n("billing", "integration.database", "Billing Queue", {"operation": "insert", "collection": "tickets_billing", "data": "{{ trigger.body }}"}),
                _n("technical", "integration.database", "Technical Queue", {"operation": "insert", "collection": "tickets_technical", "data": "{{ trigger.body }}"}),
                _n("general", "integration.database", "General Queue", {"operation": "insert", "collection": "tickets_general", "data": "{{ trigger.body }}"}),
            ],
            [_e("hook", "classify"), _e("classify", "route"), _e("route", "billing", "case_0"), _e("route", "technical", "case_1"), _e("route", "general", "default")],
        ),
    },
    {
        "slug": "website-availability-monitoring",
        "name": "Website Availability Monitoring",
        "category": "Monitoring",
        "description": "Checks a URL every hour, records each result, and raises an alert record when the site is down.",
        "required_integrations": ["HTTP Request (built in)", "Scheduled trigger (built in)", "Data store (built in)"],
        "expected_behaviour": "Once activated, it requests the URL hourly. Results go to 'uptime_checks'; failures also go to 'uptime_alerts'. Connection failures follow the same alert path through an error branch.",
        "configuration_requirements": ["Set the URL to monitor on 'Check Website'"],
        "definition": _d(
            [
                _n("tick", "trigger.schedule", "Every Hour", {"schedule_type": "hourly", "minute": 0, "timezone": "UTC"}),
                _n("check", "integration.http", "Check Website", {"method": "GET", "url": "https://example.com", "fail_on_error_status": False, "timeout_seconds": 15, "headers": [], "query": []}, on_error="error_branch"),
                _n("status", "logic.if", "Site Healthy?", {"conditions": [{"left": "{{ input.status }}", "operator": "lt", "right": "400"}], "combine": "all"}),
                _n("ok", "integration.database", "Log Check", {"operation": "insert", "collection": "uptime_checks", "data": {"url": "{{ input.url }}", "status": "{{ input.status }}", "elapsed_ms": "{{ input.elapsed_ms }}", "at": "{{ now }}"}}),
                _n("alert", "integration.database", "Raise Alert", {"operation": "insert", "collection": "uptime_alerts", "data": {"detail": "{{ input }}", "at": "{{ now }}"}}),
            ],
            [_e("tick", "check"), _e("check", "status"), _e("check", "alert", "error"), _e("status", "ok", "true"), _e("status", "alert", "false")],
        ),
    },
    {
        "slug": "webhook-data-processing",
        "name": "Webhook Data Processing",
        "category": "Data",
        "description": "Receives JSON, validates it, stores valid records and records rejected ones with the reason.",
        "required_integrations": ["Webhook (built in)", "Data store (built in)"],
        "expected_behaviour": "Valid payloads go to 'contacts'. Invalid payloads go to 'rejected_contacts' with a list of problems.",
        "configuration_requirements": [],
        "definition": _d(
            [
                _n("hook", "trigger.webhook", "Receive JSON", {"auth_mode": "hmac", "sample_body": {"name": "Ada Lovelace", "email": "ada@example.com", "age": 36}}),
                _n("validate", "data.validate", "Validate Contact", {"source": "{{ trigger.body }}", "rules": [{"field": "name", "type": "string", "required": True, "min": "2"}, {"field": "email", "type": "email", "required": True}, {"field": "age", "type": "number", "required": False, "min": "0", "max": "130"}]}),
                _n("normal", "data.transform", "Normalise", {"source": "{{ input }}", "operations": [{"operation": "lowercase", "field": "email"}, {"operation": "trim", "field": "name"}]}),
                _n("store", "integration.database", "Save Contact", {"operation": "insert", "collection": "contacts", "data": "{{ input }}"}),
                _n("reject", "integration.database", "Save Rejection", {"operation": "insert", "collection": "rejected_contacts", "data": "{{ input }}"}),
            ],
            [_e("hook", "validate"), _e("validate", "normal", "valid"), _e("normal", "store"), _e("validate", "reject", "invalid")],
        ),
    },
    {
        "slug": "csv-data-analysis",
        "name": "CSV Data Analysis",
        "category": "Data",
        "description": "Parses CSV text, measures it, finds missing values and writes a data quality report.",
        "required_integrations": ["AI provider (demo mode without a key)"],
        "expected_behaviour": "Paste CSV text into the trigger's input data and run. File upload is not supported; pass CSV as text.",
        "configuration_requirements": [],
        "definition": _d(
            [
                _n("start", "trigger.manual", "CSV Input", {"sample_data": {"csv": _CSV}}),
                _n("parse", "data.parse_csv", "Parse CSV", {"source": "{{ trigger.csv }}", "delimiter": ","}),
                _n("total", "data.transform", "Total Amount", {"source": "{{ input.rows }}", "operations": [{"operation": "sum", "field": "amount"}]}),
                _n("report", "ai.generate", "Write Report", {"prompt": 'Write a short data quality report. Rows: {{ nodes["Parse CSV"].row_count }}. Columns: {{ nodes["Parse CSV"].columns | join }}. Total amount: {{ input.sum }}. Missing values: {{ nodes["Parse CSV"].missing | json }}', "max_tokens": 800}),
            ],
            [_e("start", "parse"), _e("parse", "total"), _e("total", "report")],
        ),
    },
    {
        "slug": "customer-welcome-automation",
        "name": "Customer Welcome Automation",
        "category": "Customer",
        "description": "Classifies a new customer's account type, writes a welcome message and emails it.",
        "required_integrations": ["Webhook (built in)", "AI provider (demo mode without a key)", "Email (SMTP)", "Data store (built in)"],
        "expected_behaviour": "Your signup system posts each new customer. They are stored, classified, and sent a generated welcome email.",
        "configuration_requirements": ["Create an SMTP credential and select it on 'Send Welcome Email'"],
        "definition": _d(
            [
                _n("hook", "trigger.webhook", "Customer Registered", {"auth_mode": "hmac", "required_fields": ["email"], "sample_body": {"name": "Ada Lovelace", "email": "ada@analytical.co.uk", "company": "Analytical Engines Ltd", "text": "Ada registered for Analytical Engines Ltd, a company of 40 employees."}}),
                _n("store", "integration.database", "Save Customer", {"operation": "insert", "collection": "customers", "data": "{{ trigger.body }}"}),
                _n("classify", "ai.classify", "Classify Account", {"text": "{{ trigger.body.text }}", "labels": ["personal", "business", "enterprise"]}),
                _n("write", "ai.generate", "Write Welcome Message", {"prompt": "Write a two sentence welcome message for {{ trigger.body.name }}, who has a {{ input.label }} account.", "max_tokens": 400}),
                _n("email", "integration.email", "Send Welcome Email", {"to": "{{ trigger.body.email }}", "subject": "Welcome to the team, {{ trigger.body.name }}", "body": "{{ input.text }}"}),
            ],
            [_e("hook", "store"), _e("store", "classify"), _e("classify", "write"), _e("write", "email")],
        ),
    },
    {
        "slug": "ai-text-classification",
        "name": "AI Text Classification",
        "category": "AI",
        "description": "Classifies a list of texts by sentiment and counts the results.",
        "required_integrations": ["AI provider (demo mode without a key)"],
        "expected_behaviour": "Runs the classifier once per text using a Loop, then returns counts per label. Works immediately in demo mode.",
        "configuration_requirements": [],
        "definition": _d(
            [
                _n("start", "trigger.manual", "Texts to Classify", {"sample_data": {"texts": ["I love this product, it is excellent", "Terrible support and I want a refund", "It works, delivery was on time"]}}),
                _n("loop", "logic.loop", "For Each Text", {"items": "{{ trigger.texts }}", "max_iterations": 100}),
                _n("classify", "ai.classify", "Classify Sentiment", {"text": "{{ item }}", "labels": ["positive", "neutral", "negative"]}),
                _n("count", "data.transform", "Count by Label", {"source": "{{ input }}", "operations": [{"operation": "group_count", "field": "label"}]}),
            ],
            [_e("start", "loop"), _e("loop", "classify", "body"), _e("loop", "count", "done")],
        ),
    },
]
