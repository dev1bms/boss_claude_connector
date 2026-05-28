# -*- coding: utf-8 -*-
import hashlib
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError


TOKEN_PREFIX = "bcc"  # Boss Claude Connector


class BossClaudeApiToken(models.Model):
    _name = "boss.claude.api.token"
    _description = "Boss Claude API Token"
    _inherit = ["mail.thread"]
    _order = "create_date desc"

    name = fields.Char(required=True, tracking=True)
    profile_id = fields.Many2one(
        "boss.claude.access.profile", required=True, ondelete="cascade", tracking=True
    )
    active = fields.Boolean(default=True, tracking=True)

    token_hash = fields.Char(readonly=True, copy=False, index=True)
    token_preview = fields.Char(
        readonly=True,
        copy=False,
        help="Last 4 characters of the token. The raw token is NEVER stored.",
    )

    last_used_at = fields.Datetime(readonly=True)
    expires_at = fields.Datetime()
    notes = fields.Text()

    # ---------------------------------------------------------------
    # Token logic
    # ---------------------------------------------------------------
    @staticmethod
    def _hash_token(raw_token):
        if not raw_token:
            return False
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def action_generate_token(self):
        """Generate a new raw token, store only its hash, return it once via a wizard-like action."""
        self.ensure_one()
        raw = "%s_%s" % (TOKEN_PREFIX, secrets.token_urlsafe(32))
        self.sudo().write({
            "token_hash": self._hash_token(raw),
            "token_preview": raw[-4:],
        })
        # Post the raw token ONLY in chatter for one-time copy. It is not stored as a field.
        body = _(
            "<b>New API token generated.</b><br/>"
            "Copy it now. It will not be shown again.<br/>"
            "<pre style='user-select:all;'>%s</pre>"
        ) % raw
        self.message_post(body=body, subject=_("Boss Claude Token Generated"))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Token generated"),
                "message": _("The raw token has been posted in the chatter. Copy it now; it will not be stored."),
                "sticky": True,
                "type": "success",
            },
        }

    @api.model
    def validate_token(self, raw_token):
        """Return active token record if raw_token matches, else False."""
        if not raw_token:
            return False
        token_hash = self._hash_token(raw_token)
        token = self.sudo().search([
            ("token_hash", "=", token_hash),
            ("active", "=", True),
        ], limit=1)
        if not token:
            return False
        # Expiration check
        if token.expires_at and token.expires_at < fields.Datetime.now():
            return False
        token.sudo().write({"last_used_at": fields.Datetime.now()})
        return token

    def action_revoke(self):
        for rec in self:
            rec.active = False
        return True
