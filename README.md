# Boss Claude Connector

Secure Odoo 17 connector between Claude / MCP clients and Odoo Boss.

## Purpose

Cristina's real workflow is:

1. Cristina receives customer requests by email + attachments.
2. **Claude** (Desktop / Code / MCP client) reads those emails externally.
3. Claude extracts customer / route / cost data, optionally produces an Excel review.
4. Claude calls **this module** over HTTP to:
   * search/read selected Odoo data (customers, opportunities, etc.),
   * normalize external charge names into Boss codes,
   * create **draft-only** quotations and prevision lines.
5. Odoo remains the system of record. **Cristina manually confirms** everything.

> This module does **not** read email. Email/attachment reading happens in Claude (externally). The module only exposes safe, controlled API tools into Odoo.

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
   `C:\odoo17-docker\custom-addons\boss_claude_connector`
2. Restart Odoo and update the apps list.
3. Install the **Boss Claude Connector** app.

Or with Docker:

```powershell
docker exec -it odoo17_web odoo -c /etc/odoo/odoo.conf -d <DB_NAME> -u boss_claude_connector --stop-after-init
```

> Replace `<DB_NAME>` with your real database name (e.g. `boss17_dev`).

## Configuration

1. Log in as admin (you are automatically in **Boss Claude Admin**).
2. Open **Boss Claude Connector → Configuration → Access Profiles**.
3. Create a profile (e.g. `Cristina Claude Profile`).
4. Add **Model Permissions**:
   * `res.partner` → allow_search, allow_read
   * `crm.lead` → allow_search, allow_read
   * `sale.order` → allow_read, allow_create
   * `boss.claude.prevision.draft` → allow_read, allow_create
   * `boss.claude.charge.code.map` → allow_search, allow_read
   For each, set **Allowed Fields** to whitelist the columns Claude is allowed to see. If empty, the module falls back to a tiny safe set (`id`, `name`, `display_name`, `create_date`, `write_date`).
5. Open **Configuration → API Tokens**, create one linked to the profile, click **Generate Token**. The raw token is shown **once** in the chatter. Copy it now.
6. Send `Authorization: Bearer <token>` from your Claude/MCP client.

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
      "domain": [["name","ilike","Cofitel"]],
      "fields": ["id","name","email"],
      "limit": 10
    }
  }'
```

### Get Boss Charge Codes

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_boss_charge_codes","params":{}}'
```

### Normalize Charge Name

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool":"normalize_charge_name","params":{"raw_name":"Documentation","transport_mode":"air"}}'
```

### Validate Sale vs Prevision Codes

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "validate_sale_prevision_codes",
    "params": {
      "prevision_lines":[{"concept":"Air Freight Import","boss_code":"FAI"}],
      "sale_lines":[{"concept":"Air Freight Import","boss_code":"FMI"}]
    }
  }'
```

### Create Draft Quotation

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_draft_quotation",
    "params": {
      "partner_id": 1,
      "origin_note": "From Cristina email 2025-05-28",
      "lines": [
        {"boss_code":"FAI","name":"Air Freight Import","price_unit":350.0,"quantity":1},
        {"boss_code":"AWB","name":"Documentation","price_unit":45.0,"quantity":1}
      ]
    }
  }'
```

### Create Draft Prevision

```bash
curl -X POST http://localhost:8069/boss_claude/tools/call \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_draft_prevision",
    "params": {
      "supplier_id": 7,
      "lines": [
        {"boss_code":"ALM","concept":"Almacenaje","amount":30.0,"tax_status":"needs_review","source":"handling tariff","confidence":0.8}
      ]
    }
  }'
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

* No real Boss `prevision` model integration — falls back to `boss.claude.prevision.draft`.
* No automatic product mapping. All quotation lines use a single fallback service product `AI Draft Service Line`. Real product mapping is out of scope for v1.
* No rate limiting; deploy behind a reverse proxy if needed.
* No webhook to push events back to Claude; pull-based only.
* Charge name normalization uses simple normalized-text + token overlap, not a real fuzzy/embedding match.
* VAT rule logic is **not enforced** — `tax_status` is only a flag for human review.

## Next Recommended Steps

1. Map Boss real prevision / venta models once schema is known and add dedicated tools.
2. Add per-customer / per-supplier charge code overrides.
3. Add a Settings wizard generating a ready-to-paste MCP config block.
4. Add a small product-mapping model so quotation lines can use real Odoo products.
5. Add automated tests under `tests/`.
