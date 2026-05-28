# -*- coding: utf-8 -*-
"""Generic Claude/MCP suggestion review queue.

Every business-impacting change suggested by Claude is stored here first as a
``pending`` row. A human user reviews each row and can approve/reject. After
approval the user clicks Apply to actually write to the target Odoo model.
The Apply step re-checks model permissions and the draft-only policy of the
profile that produced the suggestion. This keeps the connector generic: it
does not need to know anything about specific business models.
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


SUPPORTED_OPERATIONS = ("create", "write", "post_note", "suggest")


class BossClaudeReviewQueue(models.Model):
    _name = "boss.claude.review.queue"
    _description = "Boss Claude Review Queue"
    _inherit = ["mail.thread"]
    _order = "create_date desc"

    name = fields.Char(required=True, default="Suggestion", tracking=True)

    token_id = fields.Many2one("boss.claude.api.token", ondelete="set null", readonly=True)
    access_profile_id = fields.Many2one(
        "boss.claude.access.profile", ondelete="set null", readonly=True, index=True,
    )
    request_log_id = fields.Many2one("boss.claude.request.log", ondelete="set null", readonly=True)

    target_module = fields.Char(index=True, help="Logical module/domain (e.g. 'sale', 'crm', 'custom').")
    target_model = fields.Char(index=True, help="Odoo technical model name (e.g. 'sale.order').")
    target_record_id = fields.Integer(
        default=0, help="Existing record id for write/post_note operations, or 0 for create/suggest.",
    )
    target_operation = fields.Selection([
        ("create", "Create"),
        ("write", "Write"),
        ("post_note", "Post Note"),
        ("suggest", "Suggestion (informational)"),
    ], required=True, default="suggest", tracking=True)

    payload_json = fields.Text(help="Proposed values / message as JSON.")
    normalized_key = fields.Char(index=True, help="Optional canonical key (concept, code, ...).")
    normalized_value = fields.Char(help="Optional canonical value associated with normalized_key.")
    source_text = fields.Text(help="Original/raw text or context that produced this suggestion.")
    confidence = fields.Float(default=0.0)

    status = fields.Selection([
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("applied", "Applied"),
        ("error", "Error"),
    ], default="pending", required=True, tracking=True, index=True)

    approved_by_id = fields.Many2one("res.users", readonly=True)
    approved_date = fields.Datetime(readonly=True)
    applied_date = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)

    applied_record_model = fields.Char(readonly=True)
    applied_record_id = fields.Integer(readonly=True)

    notes = fields.Text()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _parse_payload(self):
        self.ensure_one()
        if not self.payload_json:
            return {}
        try:
            data = json.loads(self.payload_json)
        except Exception as e:
            raise ValidationError(_("Invalid JSON in payload: %s") % e)
        if not isinstance(data, dict):
            raise ValidationError(_("Payload root must be a JSON object."))
        return data

    @api.constrains("target_operation", "target_model", "target_record_id")
    def _check_target(self):
        for rec in self:
            if rec.target_operation in ("create", "write", "post_note") and not rec.target_model:
                raise ValidationError(_("target_model is required for operation '%s'.") % rec.target_operation)
            if rec.target_operation in ("write", "post_note") and not rec.target_record_id:
                raise ValidationError(
                    _("target_record_id is required for operation '%s'.") % rec.target_operation
                )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------
    def action_approve(self):
        for rec in self:
            if rec.status not in ("pending",):
                raise UserError(_("Only pending suggestions can be approved (current: %s).") % rec.status)
            rec.write({
                "status": "approved",
                "approved_by_id": self.env.uid,
                "approved_date": fields.Datetime.now(),
                "error_message": False,
            })
            rec.message_post(body=_("Suggestion approved by %s.") % self.env.user.display_name)
        return True

    def action_reject(self):
        for rec in self:
            if rec.status in ("applied",):
                raise UserError(_("Cannot reject an already-applied suggestion."))
            rec.write({
                "status": "rejected",
                "approved_by_id": self.env.uid,
                "approved_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Suggestion rejected by %s.") % self.env.user.display_name)
        return True

    def action_reset_to_pending(self):
        for rec in self:
            if rec.status == "applied":
                raise UserError(_("Cannot reset an applied suggestion."))
            rec.write({
                "status": "pending",
                "approved_by_id": False,
                "approved_date": False,
                "error_message": False,
            })
        return True

    def action_apply(self):
        """Apply the approved suggestion. Re-checks permissions and draft-only rules."""
        for rec in self:
            if rec.status != "approved":
                raise UserError(_("Only approved suggestions can be applied (current: %s).") % rec.status)
            try:
                rec._do_apply()
            except (AccessError, ValidationError, UserError) as e:
                msg = e.args[0] if e.args else str(e)
                rec.write({"status": "error", "error_message": msg})
                rec.message_post(body=_("Apply failed: %s") % msg)
                # Do not raise to allow batch processing; user sees error per row.
            except Exception as e:
                _logger.exception("Unexpected error applying review queue %s", rec.id)
                rec.write({"status": "error", "error_message": str(e)})
                rec.message_post(body=_("Apply failed (internal): %s") % e)
        return True

    def _do_apply(self):
        """Internal: actually perform the queued operation."""
        self.ensure_one()
        env = self.env
        op = self.target_operation
        model = self.target_model
        profile = self.access_profile_id

        if op == "suggest":
            # Informational only. Mark applied with no record changes.
            self.write({
                "status": "applied",
                "applied_date": fields.Datetime.now(),
            })
            return

        if not profile:
            raise UserError(_("Suggestion has no access profile; cannot re-validate permissions."))
        if env.get(model) is None:
            raise ValidationError(_("Target model '%s' does not exist.") % model)

        payload = self._parse_payload()

        if op == "create":
            values = payload.get("values") or {}
            if not isinstance(values, dict):
                raise ValidationError(_("payload.values must be a JSON object."))
            profile.check_model_permission(model, "create", list(values.keys()) if values else None)
            profile.validate_draft_only(model, values)
            new_rec = env[model].sudo().create(values)
            self.write({
                "status": "applied",
                "applied_date": fields.Datetime.now(),
                "applied_record_model": model,
                "applied_record_id": new_rec.id,
            })
            self.message_post(body=_("Created %s id=%s.") % (model, new_rec.id))

        elif op == "write":
            values = payload.get("values") or {}
            if not isinstance(values, dict):
                raise ValidationError(_("payload.values must be a JSON object."))
            profile.check_model_permission(model, "write", list(values.keys()) if values else None)
            profile.validate_draft_only(model, values)
            target = env[model].sudo().browse(self.target_record_id)
            if not target.exists():
                raise ValidationError(_("Target record %s/%s not found.") % (model, self.target_record_id))
            target.write(values)
            self.write({
                "status": "applied",
                "applied_date": fields.Datetime.now(),
                "applied_record_model": model,
                "applied_record_id": target.id,
            })
            self.message_post(body=_("Wrote %s id=%s.") % (model, target.id))

        elif op == "post_note":
            message = payload.get("message")
            if not message:
                raise ValidationError(_("payload.message is required for post_note."))
            # post_note requires at least read; prefer write.
            try:
                profile.check_model_permission(model, "write")
            except AccessError:
                profile.check_model_permission(model, "read")
            target = env[model].sudo().browse(self.target_record_id)
            if not target.exists():
                raise ValidationError(_("Target record %s/%s not found.") % (model, self.target_record_id))
            if not hasattr(target, "message_post"):
                raise UserError(_("Model '%s' does not support chatter.") % model)
            target.message_post(body=message, subject=_("Boss Claude Review Note"))
            self.write({
                "status": "applied",
                "applied_date": fields.Datetime.now(),
                "applied_record_model": model,
                "applied_record_id": target.id,
            })
            self.message_post(body=_("Posted note on %s id=%s.") % (model, target.id))
        else:
            raise ValidationError(_("Unsupported operation '%s'.") % op)
