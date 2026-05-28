# -*- coding: utf-8 -*-
{
    "name": "Boss Claude Connector",
    "version": "17.0.1.0.0",
    "summary": "Secure connector between Claude/MCP clients and Odoo Boss.",
    "description": """
Boss Claude Connector
=====================

Exposes secure JSON tool endpoints so that Claude/MCP clients can:

* Read selected Odoo data.
* Normalize external charge names into Boss charge codes.
* Create draft-only quotations and prevision records.

All actions are logged. Tokens are hashed. Draft-only write policy enforced.
""",
    "author": "Boss Continental",
    "website": "https://www.boss-continental.com",
    "category": "Tools/Integration",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "mail",
        "sale",
        "crm",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/access_profile_views.xml",
        "views/api_token_views.xml",
        "views/normalization_rule_views.xml",
        "views/request_log_views.xml",
        "views/review_queue_views.xml",
        "views/menu.xml",
        "data/normalization_rule_seed.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
