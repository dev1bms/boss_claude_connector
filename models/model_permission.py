# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .access_profile import SAFE_DEFAULT_FIELDS, FORBIDDEN_FIELD_NAMES


class BossClaudeModelPermission(models.Model):
    _name = "boss.claude.model.permission"
    _description = "Boss Claude Model Permission"
    _order = "profile_id, model_model"

    profile_id = fields.Many2one(
        "boss.claude.access.profile",
        required=True,
        ondelete="cascade",
        index=True,
    )
    model_id = fields.Many2one("ir.model", string="Model", required=True, ondelete="cascade")
    model_model = fields.Char(
        related="model_id.model", store=True, string="Technical Name", index=True
    )

    allow_search = fields.Boolean(default=False)
    allow_read = fields.Boolean(default=False)
    allow_create = fields.Boolean(default=False)
    allow_write = fields.Boolean(default=False)
    # Kept for future. ENFORCED OFF at controller layer in v1.
    allow_delete = fields.Boolean(default=False, string="Allow Delete (disabled in API v1)")

    draft_only = fields.Boolean(default=True)

    allowed_field_ids = fields.Many2many(
        "ir.model.fields",
        "boss_claude_perm_field_rel",
        "perm_id", "field_id",
        domain="[('model_id', '=', model_id)]",
        string="Allowed Fields",
    )
    domain_filter = fields.Text(
        help="Optional Python literal list-domain applied on top of caller-supplied domain."
    )
    notes = fields.Text()

    _sql_constraints = [
        ("uniq_profile_model", "unique(profile_id, model_id)",
         "Each model can be added only once per profile."),
    ]

    def get_allowed_field_names(self):
        """Return list of allowed field names (technical), filtering forbidden ones.

        If no fields are explicitly listed, fall back to a small safe default set
        rather than exposing every field on the model.
        """
        self.ensure_one()
        if self.allowed_field_ids:
            names = [f.name for f in self.allowed_field_ids if f.name not in FORBIDDEN_FIELD_NAMES]
            # Always make sure id is available
            if "id" not in names:
                names.insert(0, "id")
            return names
        # Safe defaults: only those that actually exist on the model
        Model = self.env.get(self.model_model)
        if Model is None:
            return list(SAFE_DEFAULT_FIELDS)
        existing = []
        for f in SAFE_DEFAULT_FIELDS:
            if f in Model._fields and f not in FORBIDDEN_FIELD_NAMES:
                existing.append(f)
        return existing
