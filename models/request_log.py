# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BossClaudeRequestLog(models.Model):
    _name = "boss.claude.request.log"
    _description = "Boss Claude Request Log"
    _order = "create_date desc"
    _rec_name = "name"

    name = fields.Char(default=lambda self: self._default_name(), readonly=True)
    token_id = fields.Many2one("boss.claude.api.token", ondelete="set null", readonly=True)
    profile_id = fields.Many2one("boss.claude.access.profile", ondelete="set null", readonly=True)
    tool_name = fields.Char(readonly=True, index=True)
    model_name = fields.Char(readonly=True, index=True)
    operation = fields.Char(readonly=True)
    request_payload = fields.Text(readonly=True)
    response_payload = fields.Text(readonly=True)
    status = fields.Selection([
        ("success", "Success"),
        ("error", "Error"),
        ("blocked", "Blocked"),
    ], default="success", readonly=True, index=True)
    error_message = fields.Text(readonly=True)
    created_record_model = fields.Char(readonly=True)
    created_record_id = fields.Integer(readonly=True)
    duration_ms = fields.Integer(readonly=True)
    user_id = fields.Many2one("res.users", readonly=True)

    @api.model
    def _default_name(self):
        seq = self.env["ir.sequence"].next_by_code("boss.claude.request.log")
        return seq or "LOG/NEW"
