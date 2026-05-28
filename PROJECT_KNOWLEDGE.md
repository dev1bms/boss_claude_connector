# Boss Claude-Odoo Connector — Project Knowledge

## 1. Project Context

Boss Continental currently works with Odoo 17. Cristina receives daily customer requests by email. Claude can read Cristina’s emails and attachments, understand the operational/commercial context, and may produce an Excel summary if needed.

However, Excel should be considered only an optional intermediate review output. The target workflow is:

```text
Cristina Email + Attachments
        ↓
Claude reads and understands the request
        ↓
Claude queries Odoo through a secure connector
        ↓
Claude prepares quotation/prevision draft data
        ↓
Odoo creates draft records only
        ↓
Cristina reviews and confirms manually
```

The goal of this project is to build an Odoo 17 module named:

```text
boss_claude_connector
```

This module must act as a secure bridge between Claude/MCP and Odoo.

Claude is the assistant that reads emails and reasons over the request. Odoo is the system of record. The connector module exposes controlled tools/API endpoints that Claude can use to read Odoo data and create draft records.

---

## 2. Main Objective

Build a lightweight but production-oriented Odoo 17 addon that allows Claude Desktop / Claude Code / MCP clients to safely interact with selected Odoo models.

The module must allow administrators to configure:

* Which Odoo models Claude can read from.
* Which Odoo models Claude can create records in.
* Which Odoo models Claude can write to.
* Which fields are allowed.
* Whether write/create actions are draft-only.
* API tokens / access profiles for Claude.
* Logs for every Claude action.

The module should not give Claude unrestricted access to Odoo.

---

## 3. Correct Architecture

The correct architecture is:

```text
Claude Desktop / Claude Code
        ↓
MCP Server / Connector Client
        ↓
boss_claude_connector Odoo Module
        ↓
Odoo ORM / Boss Models
```

Important clarification:

The Odoo module does not “connect to Odoo through MCP.”
The Odoo module exposes secure tools/endpoints. Claude or an MCP server connects to those endpoints and uses them to query/write Odoo.

---

## 4. What Claude Does

Claude’s role:

* Reads Cristina’s emails.
* Reads attachments when available.
* Extracts customer request data.
* Understands context from multiple emails.
* Optionally generates an Excel review file.
* Queries Odoo for customer/opportunity/shipment/tariff/code data.
* Prepares quotation/prevision proposals.
* Calls Odoo connector tools to create drafts only.
* Explains what it prepared and what needs review.

Claude must not:

* Confirm sale orders.
* Send quotations to customers automatically.
* Create or post invoices.
* Delete records.
* Modify confirmed/completed records.
* Invent prices, taxes, suppliers, or charge codes.

---

## 5. Business Workflow Required by Cristina

Cristina wants Claude to help with:

### 5.1 Customer Requests

Customer requests arrive by email. Claude reads the email thread and attachments and extracts:

* Customer.
* Contact.
* Origin/destination.
* Transport mode.
* Import/export direction.
* Cargo details.
* Weight.
* CBM.
* Chargeable weight.
* Warehouse/handling operator.
* Airline/carrier.
* Expected costs.
* Expected sales lines.
* Missing information.

### 5.2 Quotation Drafts

Claude should be able to create draft quotations in Odoo after checking:

* Customer exists.
* Opportunity exists or needs to be created.
* Route/service information is clear.
* Sale lines have Boss charge codes.
* Amounts come from email, accepted offer, tariff, or known rule.
* Uncertain values are marked as needing review.

### 5.3 Previsiones

Claude should prepare and create draft previsiones in Odoo.

A prevision is a cost/supplier-side provision line. It must include:

* Supplier.
* Boss code.
* Concept.
* Amount.
* Currency.
* VAT/tax rule.
* Source of information.
* Confidence/status.
* Link to opportunity/shipment/quotation where applicable.

### 5.4 Venta

Claude should read or infer venta from accepted offers/client quotations and create draft sale lines in Odoo.

Venta lines must include:

* Customer.
* Boss code.
* Concept.
* Amount.
* Currency.
* VAT/tax rule.
* Source.
* Link to prevision concept when applicable.

---

## 6. Critical Business Rule: Code Matching

This is one of the most important Cristina requirements.

For the same commercial/operational concept, the code in previsión and venta must match.

Example:

```text
Correct:
Previsión code = FAI
Venta code     = FAI

Wrong:
Previsión code = FAI
Venta code     = FMI
```

If the same concept has different codes between cost/prevision and sale, the system must raise a validation warning and prevent automatic draft creation unless the user explicitly approves.

---

## 7. Boss Charge Code Normalization

Different warehouses or suppliers may use different names for the same fee. The connector must support a Boss charge code dictionary.

Examples:

```text
"Documentation" = "Data Fee" = "Docs" → Boss Code: AWB or DOC depending Boss configuration
"Terminal Handling Charge" = "THC" → Boss Code: THC
"Storage" = "Almacenaje" → Boss Code: ALM
"Air Freight Import" = "Flete aéreo import" → Boss Code: FAI
"Customs Clearance Import" = "Despacho import" → Boss Code: FAD
"Quebranto bancario" → Boss Code: QBR
```

The module should allow this dictionary to be managed from Odoo.

Recommended model:

```text
boss.claude.charge.code.map
```

Fields:

* name
* boss_code
* normalized_concept
* external_name
* supplier_id optional
* transport_mode
* direction
* active
* notes

---

## 8. Known Initial Boss Codes

Initial suggested codes:

```text
FAI = Freight Air Import / Flete aéreo importación
FAE = Freight Air Export / Flete aéreo exportación
THC = Terminal Handling Charge
ALM = Almacenaje / Storage
AWB = AWB / Documentation / Data
FAD = Despacho Aduanas Import
QBR = Quebranto Bancario
SEG = Seguro
INL = Inland / Delivery / Transporte terrestre
CAU = Caución Aval
DUA = DUA / Customs taxes reference
```

These must be configurable, not hardcoded forever.

---

## 9. Air Freight / Handling Logic

For air freight previsiones, Cristina expects Claude/Odoo to understand:

* Airline in the Odoo file can identify the handling operator.
* Example: WFS as handling operator.
* Handling tariffs may include concepts such as:

  * Almacenaje when applicable.
  * Documentation / Data.
  * THC.
  * Other handling-specific charges.
* Handling warehouses may name the same fee differently.
* The system must normalize the fee to a fixed Boss code.

Important: If the tariff says “solo 4 conceptos” but only 3 are clearly listed, the system must mark the fourth as missing/needs confirmation instead of inventing it.

---

## 10. VAT / Tax Rules from Cristina Notes

Initial rules to encode as review logic:

* Import/export air and sea freight is generally VAT exempt.
* Profit share from foreign agents is VAT exempt.
* All previsiones under a foreign supplier should be VAT exempt.
* ALM/storage for import invoiced by a Spanish company pays VAT.
* Local charge in import invoiced to a local Spanish company usually has VAT.
* Local charge in export invoiced to a local Spanish company may be VAT exempt.
* VAT decisions must be marked as reviewable until confirmed.

The module should not silently invent tax rules. It should return a clear status:

```text
tax_status = ok / needs_review / missing_data
```

---

## 11. Draft-Only Policy

Initial version must only create drafts.

Allowed:

* Read records.
* Search records.
* Create draft CRM opportunities.
* Create draft sale quotations.
* Create draft sale order lines.
* Create draft prevision records if model exists.
* Create notes/logs.
* Create review records.

Not allowed:

* Confirm quotations.
* Send emails to customers.
* Create/post invoices.
* Delete records.
* Confirm shipments.
* Modify posted/accounting records.
* Mass update records.
* Modify confirmed sale orders without explicit manual approval.

---

## 12. Dynamic Model Access

The module must include a configuration UI where admin can create access profiles.

Recommended model:

```text
boss.claude.access.profile
```

Fields:

* name
* active
* token_ids
* allowed_model_ids
* notes
* draft_only_default
* log_full_payload

Recommended child model:

```text
boss.claude.model.permission
```

Fields:

* profile_id
* model_id
* model_model
* allow_read
* allow_search
* allow_create
* allow_write
* allow_delete
* draft_only
* allowed_field_ids
* domain_filter
* notes

This allows selecting dynamically which models Claude can read/write.

---

## 13. Token Generation

The module must generate API tokens for Claude/MCP clients.

Recommended model:

```text
boss.claude.api.token
```

Fields:

* name
* profile_id
* token_hash
* token_preview
* active
* last_used_at
* expires_at
* created_by
* notes

Security:

* Never store raw token.
* Store only hash.
* Show token only once after generation.
* Token must be revocable.
* Token must be linked to an access profile.

---

## 14. API / Tool Layer

The module should expose JSON endpoints that can be called by an MCP server or Claude connector.

Initial endpoints:

```text
GET  /boss_claude/health
POST /boss_claude/tools/list
POST /boss_claude/tools/call
```

A single `tools/call` endpoint is preferred over many public endpoints.

Input example:

```json
{
  "tool": "search_records",
  "params": {
    "model": "res.partner",
    "domain": [["name", "ilike", "Cofitel"]],
    "fields": ["id", "name", "email"],
    "limit": 10
  }
}
```

The module must validate:

* Token.
* Profile.
* Model permission.
* Operation permission.
* Allowed fields.
* Draft-only constraints.
* Domain restrictions.

---

## 15. Initial Tools

Implement these initial tools:

### 15.1 health_check

Checks module status.

### 15.2 list_allowed_models

Returns models allowed for this token/profile.

### 15.3 search_records

Generic safe search.

Inputs:

* model
* domain
* fields
* limit

### 15.4 read_record

Generic safe read.

Inputs:

* model
* record_id
* fields

### 15.5 get_boss_charge_codes

Returns Boss charge code dictionary.

### 15.6 normalize_charge_name

Maps external fee names to Boss codes.

Inputs:

* raw_name
* supplier_id optional
* transport_mode optional
* direction optional

### 15.7 validate_sale_prevision_codes

Validates that sale and prevision lines for the same concept use the same Boss code.

### 15.8 create_draft_quotation

Creates a draft sale.order only.

### 15.9 create_draft_prevision

Creates draft prevision/review records only.

If Boss currently does not have a prevision model, create a connector-side draft model:

```text
boss.claude.prevision.draft
```

### 15.10 create_ai_review_note

Creates an internal note/chatter message or connector log with Claude’s proposal.

---

## 16. Logging

Every request must be logged.

Recommended model:

```text
boss.claude.request.log
```

Fields:

* token_id
* profile_id
* tool_name
* model_name
* operation
* request_payload
* response_payload
* status
* error_message
* created_record_model
* created_record_id
* duration_ms
* user_id
* create_date

Logs must be visible in Odoo menus.

---

## 17. User Interface

Add menu:

```text
Settings / Boss Claude Connector
```

Or under a Boss menu if available.

Views needed:

* Access Profiles.
* Model Permissions.
* API Tokens.
* Charge Code Mapping.
* Request Logs.
* Prevision Drafts / AI Review Drafts.

Admin should be able to:

* Create a profile.
* Select models dynamically.
* Select read/create/write permissions.
* Generate token.
* Copy generated MCP config.
* Review logs.
* Disable token.

---

## 18. MCP Config Output

The module should generate a suggested MCP configuration block for Claude Desktop.

The exact external MCP server implementation may vary, but the Odoo module should provide:

* Base URL.
* Token.
* Tools endpoint.
* Health endpoint.
* Profile name.
* Allowed models summary.

Example output:

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

---

## 19. Odoo Version

Target version:

```text
Odoo 17 Community
```

Development environment:

```text
C:\odoo17-docker
C:\odoo17-docker\custom-addons
C:\odoo17-docker\addons
```

Target addon path:

```text
C:\odoo17-docker\custom-addons\boss_claude_connector
```

---

## 20. Implementation Principles

* Keep module lightweight.
* Do not over-engineer.
* Build secure base first.
* Prefer draft-only writes.
* Prefer configurable model permissions.
* Do not hardcode Boss business rules where they must be configurable.
* Return structured JSON responses.
* Fail safely.
* Log everything.
* Add tests where practical.
* Use Odoo ORM, not raw SQL unless necessary.
* Use standard Odoo access rights and record rules where possible.
* Add clear technical comments.

---

## 21. Expected Result After Implementation

After implementation, we should be able to:

1. Install `boss_claude_connector` in Odoo 17.
2. Open Boss Claude Connector settings.
3. Create an access profile.
4. Select allowed models for Claude.
5. Allow read on customers/opportunities/sale orders.
6. Allow draft create on quotations/previsions.
7. Generate an API token.
8. Give token/config to Claude/MCP.
9. Claude can search Odoo customers.
10. Claude can read opportunities and previous shipments if configured.
11. Claude can read Boss charge codes.
12. Claude can normalize external fee names into Boss codes.
13. Claude can validate venta/prevision code matching.
14. Claude can create draft quotation/prevision records only.
15. Admin can review every action in logs.

---

## 22. Cristina Use Case Demo

Demo scenario:

1. Claude reads Cristina’s email thread.
2. Claude extracts:

   * customer
   * route
   * air freight details
   * handling warehouse
   * costs
   * sale concepts
3. Claude calls Odoo:

   * search customer
   * read previous opportunity/shipment
   * get Boss charge codes
   * normalize charge names
4. Claude prepares:

   * draft quotation lines
   * draft prevision lines
   * warnings
5. Claude calls Odoo connector:

   * create draft quotation
   * create draft previsiones
6. Odoo stores logs.
7. Cristina reviews and confirms manually.

---

## 23. Non-Goals for First Version

Do not implement in v1:

* Email reading inside Odoo.
* Direct Gmail/Outlook integration.
* Automatic quotation sending.
* Invoice creation.
* Accounting posting.
* Shipment confirmation.
* WCA/JCtrans scraping.
* Full AI prompt management system.
* Full MCP protocol server inside Odoo unless simple and safe.

The first version is a secure Odoo-side connector for Claude/MCP clients.

---

## 24. Recommended Addon Structure

```text
boss_claude_connector/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py
├── models/
│   ├── __init__.py
│   ├── access_profile.py
│   ├── api_token.py
│   ├── model_permission.py
│   ├── charge_code_map.py
│   ├── request_log.py
│   └── prevision_draft.py
├── security/
│   ├── ir.model.access.csv
│   └── security.xml
├── views/
│   ├── menu.xml
│   ├── access_profile_views.xml
│   ├── api_token_views.xml
│   ├── charge_code_map_views.xml
│   ├── request_log_views.xml
│   └── prevision_draft_views.xml
├── data/
│   └── charge_code_seed.xml
└── README.md
```

---

## 25. Final Rule

Claude should assist Cristina, not replace human review.

The connector must make it easy for Claude to prepare draft work, but final confirmation remains inside Odoo and under human responsibility.
