# -*- coding: utf-8 -*-
from odoo import fields, models


class BossClaudeTokenWizard(models.TransientModel):
    _name = "boss.claude.token.wizard"
    _description = "Boss Claude Token Display Wizard"

    token_id = fields.Many2one(
        "boss.claude.api.token",
        string="API Token",
        required=True,
        readonly=True,
    )
    raw_token = fields.Char(
        string="Raw Token",
        readonly=True,
        help="Copy this token now. It will never be shown again.",
    )
    warning = fields.Char(
        default="This token is displayed exactly once. If you lose it, generate a new one.",
        readonly=True,
    )

    def action_close(self):
        return {"type": "ir.actions.act_window_close"}
