# Boss Claude Connector

Secure Odoo 17 connector between Claude / MCP clients and Odoo.

## Purpose

A generic AI gateway that lets Claude (Desktop / Code / MCP client) safely interact with Odoo:

1. Claude reads customer requests externally (email, documents, chat, etc.).
2. Claude extracts structured data and reasoning.
3. Claude calls **this module** over HTTP to:
   * search/read selected Odoo data (customers, opportunities, etc.),
   * normalize external values into canonical codes,
   * queue **draft-only** business changes for human approval.
4. Odoo remains the system of record. **A human reviewer manually approves and applies** every queued suggestion.

> This module does **not** read email or external documents. Reading happens in Claude (externally). The module only exposes safe, controlled API tools into Odoo.

## Architecture

```
Claude Desktop / Claude Code / MCP client
            │  HTTP + Bearer token
            ▼
   /boss_claude/tools/call
            │
            ▼
  boss_claude_connector (this module)
            │
            ▼
        Odoo ORM
```

## Installation

1. Place this folder in your custom addons path:
   `/path/to/custom-addons/boss_claude_connector`
2. Restart Odoo and update the apps list.
3. Install the **Boss Claude Connector** app.

Or with Docker:

```powershell
docker exec -it <ODOO_CONTAINER> odoo -c /etc/odoo/odoo.conf -d <DB_NAME> -u boss_claude_connector --stop-after-init
```

> Replace `<DB_NAME>` with your real database name and `<ODOO_CONTAINER>` with your container name.

## Configuration

1. Log in as admin (you are automatically in **Boss Claude Admin**).
2. Open **Boss Claude Connector → Configuration → Access Profiles**.
3. Create a profile (e.g. `Customer Service AI Access`).
4. Add **Model Permissions**:
   * `res.partner` → allow_search, allow_read
   * `crm.lead` → allow_search, allow_read
   * `sale.order` → allow_read, allow_create
   * `boss.claude.review.queue` → allow_read, allow_create
   * `boss.claude.normalization.rule` → allow_search, allow_read
   For each, set **Allowed Fields** to whitelist the columns Claude is allowed to see. If empty, the module falls back to a tiny safe set (`id`, `name`, `display_name`, `create_date`, `write_date`).
5. Open **Configuration → API Tokens**, create one linked to the profile, click **Generate Token**. A popup shows the full raw token **exactly once**. Copy it immediately and store it securely.
6. Send `Authorization: Bearer <token>` from your Claude/MCP client.

> **Important**: the `token_preview` field (last 4 characters) shown in the Odoo list view is **not** the full token. Using only the preview in your `Authorization` header will result in a `401 invalid_token` error. If you lose the full raw token, generate a new one — the old one cannot be recovered.

## API Endpoints

| Method | URL                          | Description                            |
|--------|------------------------------|----------------------------------------|
| GET    | `/boss_claude/health`        | Public health check.                   |
| POST   | `/boss_claude/tools/list`    | List tools allowed for this token.     |
| POST   | `/boss_claude/tools/call`    | Call a tool by name with JSON params.  |

All non-public endpoints require `Authorization: Bearer <token>`.

### Health

```bash
curl http://localhost:8069/boss_claude/health
```

### Tools List

```bash
curl -X POST http://localhost:8069/boss_claude/tools/list \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Search Records

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "search_records",
    "params": {
      "model": "res.partner",
      "domain": [["name","ilike","Example Company"]],
      "fields": ["id","name","email"],
      "limit": 10
    }
  }'
```

### Get Normalization Rules

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_normalization_rules","params":{"module":"boss_charge_codes"}}'
```

### Normalize a Value

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool":"normalize_value","params":{"raw_value":"Documentation","module":"boss_charge_codes","field":"boss_code"}}'
```

### Validate Codes (generic consistency check)

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "validate_codes",
    "params": {
      "lines_a":[{"concept":"Air Freight Import","code":"FAI"}],
      "lines_b":[{"concept":"Air Freight Import","code":"FMI"}],
      "label_a":"cost","label_b":"sale"
    }
  }'
```

### Queue a Suggestion (create)

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_suggestion",
    "params": {
      "name": "Draft quotation for Example Company",
      "target_module": "sale",
      "target_model": "sale.order",
      "target_operation": "create",
      "values": {"partner_id": 1},
      "source_text": "Customer email requesting air freight quote",
      "confidence": 0.7
    }
  }'
```

### Queue a Suggestion (post note)

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_suggestion",
    "params": {
      "target_module": "crm",
      "target_model": "crm.lead",
      "target_operation": "post_note",
      "target_record_id": 1,
      "message": "AI summary: customer asks for air freight import route."
    }
  }'
```

### List Pending Suggestions

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool":"list_pending_suggestions","params":{"status":"pending"}}'
```

## Example Claude / MCP config

```json
{
  "boss_odoo_connector": {
    "base_url": "http://localhost:8069",
    "token": "PASTE_GENERATED_TOKEN_HERE",
    "tools_endpoint": "/boss_claude/tools/call",
    "health_endpoint": "/boss_claude/health"
  }
}
```

## Security Notes

* **Tokens are hashed (SHA-256)**, never stored in plain text. The raw token is shown only once in the chatter at generation time.
* **Delete is hard-blocked** at the API layer in v1, even if `allow_delete` is set in the permission.
* **Draft-only enforcement**: cannot set non-draft state, `invoice_status`, `posted`, `move_id` via API.
* **Sale orders are never confirmed** by this module.
* **Allowed fields whitelist**: if empty, falls back to a tiny safe set, not to all fields.
* **Forbidden fields** (e.g. `password`, `*token*`, `*api_key*`) are always stripped.
* Every request is logged in `boss.claude.request.log` with status `success` / `error` / `blocked`.
* Token can be revoked instantly by un-checking `Active`.

## Limitations / Known Issues (v1)

* The connector is generic; it does not ship with business-specific Odoo models. Prevision/venta models must be added by the implementing team.
* No automatic product mapping. Quotation suggestions that reach the apply stage use a single fallback service product `AI Draft Service Line` unless a real product mapping is configured.
* No rate limiting; deploy behind a reverse proxy if needed.
* No webhook to push events back to Claude; pull-based only.
* Normalization uses simple normalized-text + token overlap, not a real fuzzy/embedding match.
* VAT/tax rule logic is **not enforced** — `tax_status` is only a flag for human review.

## Next Recommended Steps

1. Map real business models (prevision, venta, shipment, etc.) once schema is known and add dedicated tools.
2. Add per-customer / per-supplier normalization overrides.
3. Add a Settings wizard generating a ready-to-paste MCP config block.
4. Add a small product-mapping model so quotation lines can use real Odoo products.
5. Add automated tests under `tests/`.
