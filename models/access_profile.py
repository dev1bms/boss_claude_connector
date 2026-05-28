# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


# Safe default fields exposed when a permission has no allowed_field_ids set.
SAFE_DEFAULT_FIELDS = ("id", "name", "display_name", "create_date", "write_date")

# Fields that must NEVER be returned to API consumers regardless of configuration.
FORBIDDEN_FIELD_NAMES = (
    "password",
    "password_crypt",
    "new_password",
    "totp_secret",
    "api_key",
    "openai_api_key",
    "anthropic_api_key",
    "token",
    "token_hash",
    "access_token",
    "refresh_token",
    "oauth_access_token",
    "oauth_refresh_token",
)


class BossClaudeAccessProfile(models.Model):
    _name = "boss.claude.access.profile"
    _description = "Boss Claude Access Profile"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    draft_only_default = fields.Boolean(default=True)
    log_full_payload = fields.Boolean(default=True)
    notes = fields.Text()

    permission_ids = fields.One2many(
        "boss.claude.model.permission", "profile_id", string="Model Permissions"
    )
    token_ids = fields.One2many(
        "boss.claude.api.token", "profile_id", string="API Tokens"
    )

    permission_count = fields.Integer(
        compute="_compute_counts", string="Permissions"
    )
    token_count = fields.Integer(compute="_compute_counts", string="Tokens")

    @api.depends("permission_ids", "token_ids")
    def _compute_counts(self):
        for rec in self:
            rec.permission_count = len(rec.permission_ids)
            rec.token_count = len(rec.token_ids)

    # ---------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------
    def get_allowed_models_summary(self):
        self.ensure_one()
        summary = []
        for perm in self.permission_ids:
            summary.append({
                "model": perm.model_model,
                "operations": {
                    "search": perm.allow_search,
                    "read": perm.allow_read,
                    "create": perm.allow_create,
                    "write": perm.allow_write,
                    "delete": False,  # delete is always blocked at API layer
                },
                "draft_only": perm.draft_only,
                "fields": perm.get_allowed_field_names(),
            })
        return summary

    def check_model_permission(self, model, operation, fields=None):
        """Return permission record if granted, otherwise raise AccessError.

        operation in: search, read, create, write
        """
        self.ensure_one()
        if operation not in ("search", "read", "create", "write"):
            raise AccessError(_("Operation '%s' is not allowed via API.") % operation)

        perm = self.permission_ids.filtered(lambda p: p.model_model == model)
        if not perm:
            raise AccessError(
                _("Profile '%s' has no permission for model '%s'.") % (self.name, model)
            )
        perm = perm[0]

        flag_map = {
            "search": perm.allow_search,
            "read": perm.allow_read,
            "create": perm.allow_create,
            "write": perm.allow_write,
        }
        if not flag_map.get(operation):
            raise AccessError(
                _("Operation '%s' not allowed on model '%s' for profile '%s'.")
                % (operation, model, self.name)
            )

        if fields:
            allowed = set(perm.get_allowed_field_names())
            for fname in fields:
                if fname in FORBIDDEN_FIELD_NAMES:
                    raise AccessError(_("Field '%s' is forbidden by policy.") % fname)
                if fname not in allowed:
                    raise AccessError(
                        _("Field '%s' not allowed for model '%s'.") % (fname, model)
                    )

        return perm

    def validate_draft_only(self, model, values):
        """Enforce that values do not attempt to leave draft state."""
        self.ensure_one()
        if not isinstance(values, dict):
            return True

        # Block obvious confirmation states / accounting-impacting fields
        state_val = values.get("state")
        if state_val and state_val not in ("draft",):
            raise ValidationError(
                _("Draft-only policy: cannot set state='%s' on %s.")
                % (state_val, model)
            )

        forbidden_keys = ("invoice_status", "posted", "move_id")
        for k in forbidden_keys:
            if k in values:
                raise ValidationError(
                    _("Draft-only policy: cannot set '%s' via API.") % k
                )
        return True
