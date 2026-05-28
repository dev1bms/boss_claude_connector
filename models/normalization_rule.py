# -*- coding: utf-8 -*-
"""Generic normalization rules.

Replaces the previous business-specific charge_code_map. A rule maps an
external/raw textual value to a normalized canonical value, optionally scoped
to a module / model / field. Claude can call ``normalize_value`` on any
allowed (module, model, field) triplet and get a structured suggestion back.
"""
import re

from odoo import api, fields, models


def _normalize(text):
    if not text:
        return ""
    t = text.strip().lower()
    t = re.sub(r"[^a-z0-9áéíóúñü ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class BossClaudeNormalizationRule(models.Model):
    _name = "boss.claude.normalization.rule"
    _description = "Boss Claude Normalization Rule"
    _order = "module, model, field, raw_value"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    module = fields.Char(index=True, help="Optional module/domain scope (e.g. 'sale', 'crm', or a custom domain like 'boss_charge_codes').")
    model = fields.Char(index=True, help="Optional Odoo technical model name (e.g. 'sale.order.line').")
    field = fields.Char(index=True, help="Optional field/attribute the rule applies to (e.g. 'name', 'product_id', 'concept').")

    raw_value = fields.Char(required=True, index=True, help="External/raw value to recognize.")
    normalized_value = fields.Char(required=True, help="Canonical normalized value.")
    confidence = fields.Float(default=1.0, help="Default confidence for an exact match using this rule (0.0-1.0).")

    match_type = fields.Selection([
        ("exact", "Exact (normalized text)"),
        ("contains", "Contains (substring)"),
        ("token", "Token overlap"),
    ], default="exact", required=True)

    notes = fields.Text()

    @api.model
    def normalize_value(self, raw_value, module=None, model=None, field=None):
        """Find the best matching rule for a raw value.

        Returns a dict: {raw_value, normalized_value, confidence, matched_rule_id,
        needs_review, candidates[]}. Candidates is the top-N alternatives.
        """
        result = {
            "raw_value": raw_value,
            "normalized_value": False,
            "confidence": 0.0,
            "matched_rule_id": False,
            "needs_review": True,
            "candidates": [],
        }
        if not raw_value:
            return result

        normalized = _normalize(raw_value)
        domain = [("active", "=", True)]
        # Scope filters: rule may be unscoped (False) which makes it match any scope.
        if module:
            domain += ["|", ("module", "=", module), ("module", "in", (False, ""))]
        if model:
            domain += ["|", ("model", "=", model), ("model", "in", (False, ""))]
        if field:
            domain += ["|", ("field", "=", field), ("field", "in", (False, ""))]

        candidates = self.sudo().search(domain)
        if not candidates:
            return result

        scored = []
        for c in candidates:
            raw_norm = _normalize(c.raw_value)
            norm_norm = _normalize(c.normalized_value)
            score = 0.0
            if c.match_type == "exact":
                if normalized == raw_norm or normalized == norm_norm:
                    score = max(score, c.confidence or 1.0)
            elif c.match_type == "contains":
                if raw_norm and (raw_norm in normalized or normalized in raw_norm):
                    score = max(score, min(0.85, (c.confidence or 1.0)))
                if norm_norm and norm_norm in normalized:
                    score = max(score, min(0.85, (c.confidence or 1.0)))
            elif c.match_type == "token":
                tokens_a = set(normalized.split())
                tokens_b = set(raw_norm.split()) | set(norm_norm.split())
                if tokens_a and tokens_b:
                    overlap = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
                    if overlap > 0:
                        score = max(score, min(c.confidence or 1.0, 0.5 + overlap * 0.4))
            if score > 0:
                scored.append((score, c))

        if not scored:
            return result

        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best = scored[0]
        result.update({
            "normalized_value": best.normalized_value,
            "confidence": round(best_score, 3),
            "matched_rule_id": best.id,
            "needs_review": best_score < 0.8,
            "candidates": [{
                "rule_id": c.id,
                "normalized_value": c.normalized_value,
                "raw_value": c.raw_value,
                "score": round(s, 3),
                "match_type": c.match_type,
            } for s, c in scored[:5]],
        })
        return result
