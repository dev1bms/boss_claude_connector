# -*- coding: utf-8 -*-
"""Boss Claude Connector controller.

Generic, dynamic AI gateway. The controller exposes a small set of generic
tools. Any business-impacting change requested by Claude is queued in
``boss.claude.review.queue`` and a human user must approve and apply it.
"""
import ast
import json
import logging
import time

from odoo import http, fields, _
from odoo.http import request, Response
from odoo.exceptions import AccessError, ValidationError, UserError

_logger = logging.getLogger(__name__)

MODULE_VERSION = "17.0.2.0.0"

# Hard cap on returned records to keep responses small.
MAX_LIMIT = 50
DEFAULT_LIMIT = 10

# Operations Claude is allowed to queue.
QUEUEABLE_OPERATIONS = ("create", "write", "post_note", "suggest")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _json_response(payload, status=200):
    return Response(
        json.dumps(payload, default=str),
        status=status,
        headers=[("Content-Type", "application/json")],
    )


def _ok(data):
    return _json_response({"ok": True, "data": data})


def _err(message, status=400, code="error"):
    return _json_response(
        {"ok": False, "error": {"code": code, "message": message}},
        status=status,
    )


def _extract_bearer():
    auth = request.httprequest.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip()


def _parse_json_body():
    try:
        raw = request.httprequest.get_data(as_text=True) or "{}"
        return json.loads(raw)
    except Exception as e:
        raise ValidationError(_("Invalid JSON body: %s") % e)


def _truncate(text, n=20000):
    if text is None:
        return None
    s = text if isinstance(text, str) else json.dumps(text, default=str)
    return s if len(s) <= n else s[:n] + "...[truncated]"


def _safe_domain(domain_text):
    if not domain_text:
        return []
    try:
        d = ast.literal_eval(domain_text)
        if isinstance(d, list):
            return d
    except Exception:
        pass
    return []


def _normalize_text(t):
    if not t:
        return ""
    return " ".join(t.strip().lower().split())


# ------------------------------------------------------------------
# Logging helper
# ------------------------------------------------------------------
def _log_request(env, token, profile, tool_name, model_name, operation,
                 request_payload, response_payload, status, error_message,
                 created_record_model=None, created_record_id=None,
                 duration_ms=0, log_full_payload=True):
    try:
        vals = {
            "token_id": token.id if token else False,
            "profile_id": profile.id if profile else False,
            "tool_name": tool_name,
            "model_name": model_name,
            "operation": operation,
            "status": status,
            "error_message": _truncate(error_message) if error_message else False,
            "created_record_model": created_record_model,
            "created_record_id": created_record_id or 0,
            "duration_ms": duration_ms,
            "user_id": env.uid,
        }
        if log_full_payload:
            vals["request_payload"] = _truncate(json.dumps(request_payload, default=str))
            vals["response_payload"] = _truncate(json.dumps(response_payload, default=str))
        return env["boss.claude.request.log"].sudo().create(vals)
    except Exception:
        _logger.exception("Failed to write boss.claude.request.log")
        return False


# ==================================================================
# Controller
# ==================================================================
class BossClaudeConnector(http.Controller):

    @http.route("/boss_claude/health", type="http", auth="public", methods=["GET"], csrf=False)
    def health(self, **kwargs):
        return _ok({
            "status": "ok",
            "module": "boss_claude_connector",
            "version": MODULE_VERSION,
            "server_time": fields.Datetime.now().isoformat(),
        })

    @http.route("/boss_claude/tools/list", type="http", auth="public", methods=["POST"], csrf=False)
    def tools_list(self, **kwargs):
        token_raw = _extract_bearer()
        if not token_raw:
            return _err("Missing Authorization Bearer token.", status=401, code="missing_token")
        token = request.env["boss.claude.api.token"].sudo().validate_token(token_raw)
        if not token:
            return _err("Invalid or expired token.", status=401, code="invalid_token")
        profile = token.profile_id
        return _ok({
            "profile": profile.name,
            "tools": self._available_tools(),
            "allowed_models": profile.get_allowed_models_summary(),
        })

    @http.route("/boss_claude/tools/call", type="http", auth="public", methods=["POST"], csrf=False)
    def tools_call(self, **kwargs):
        start = time.time()
        env = request.env
        token = None
        profile = None
        tool_name = None
        params = {}
        model_name = None
        operation = None
        log_full_payload = True
        try:
            token_raw = _extract_bearer()
            if not token_raw:
                return _err("Missing Authorization Bearer token.", status=401, code="missing_token")
            token = env["boss.claude.api.token"].sudo().validate_token(token_raw)
            if not token:
                return _err("Invalid or expired token.", status=401, code="invalid_token")
            profile = token.profile_id
            log_full_payload = profile.log_full_payload

            body = _parse_json_body()
            tool_name = body.get("tool")
            params = body.get("params") or {}
            if not tool_name:
                raise ValidationError(_("Missing 'tool' in request body."))

            handler = _TOOL_REGISTRY.get(tool_name)
            if not handler:
                raise ValidationError(_("Unknown tool '%s'.") % tool_name)

            # First pass: execute the tool and collect meta.
            # The handler may need the request_log id to attach it to a queue
            # entry. We pass a placeholder dict that the handler can mutate.
            ctx = {"request_log_id": False}
            result, meta = handler(env, token, profile, params, ctx)
            model_name = meta.get("model_name")
            operation = meta.get("operation")

            duration_ms = int((time.time() - start) * 1000)
            log_rec = _log_request(
                env, token, profile, tool_name, model_name, operation,
                params, result, "success", None,
                created_record_model=meta.get("created_record_model"),
                created_record_id=meta.get("created_record_id"),
                duration_ms=duration_ms,
                log_full_payload=log_full_payload,
            )
            # Attach log id to any queue entry the handler may have created.
            if log_rec and meta.get("review_queue_id"):
                env["boss.claude.review.queue"].sudo().browse(
                    meta["review_queue_id"]
                ).write({"request_log_id": log_rec.id})

            return _ok(result)

        except AccessError as e:
            duration_ms = int((time.time() - start) * 1000)
            _log_request(env, token, profile, tool_name, model_name, operation,
                         params, None, "blocked", str(e),
                         duration_ms=duration_ms, log_full_payload=log_full_payload)
            return _err(str(e), status=403, code="forbidden")
        except (ValidationError, UserError) as e:
            duration_ms = int((time.time() - start) * 1000)
            msg = e.args[0] if e.args else str(e)
            _log_request(env, token, profile, tool_name, model_name, operation,
                         params, None, "error", msg,
                         duration_ms=duration_ms, log_full_payload=log_full_payload)
            return _err(msg, status=400, code="validation_error")
        except Exception as e:
            _logger.exception("boss_claude tools/call internal error")
            duration_ms = int((time.time() - start) * 1000)
            _log_request(env, token, profile, tool_name, model_name, operation,
                         params, None, "error", str(e),
                         duration_ms=duration_ms, log_full_payload=log_full_payload)
            return _err("Internal error.", status=500, code="internal_error")

    # --------------------------------------------------------------
    # Tool descriptors
    # --------------------------------------------------------------
    def _available_tools(self):
        return [
            {"name": "health_check",
             "description": "Connector status."},
            {"name": "list_allowed_models",
             "description": "Models and operations allowed for this token."},
            {"name": "search_records",
             "description": "Generic safe search. Params: model, domain?, fields?, limit?"},
            {"name": "read_record",
             "description": "Read one record. Params: model, record_id, fields?"},
            {"name": "get_normalization_rules",
             "description": "List normalization rules. Params: module?, model?, field?, limit?"},
            {"name": "normalize_value",
             "description": "Normalize a raw value. Params: raw_value, module?, model?, field?"},
            {"name": "validate_codes",
             "description": "Validate that two sets of {concept, code} entries are consistent. "
                            "Params: lines_a[], lines_b[], key='concept', value='code'."},
            {"name": "create_suggestion",
             "description": "Queue a suggestion for human approval. Params: target_model, "
                            "target_operation (create|write|post_note|suggest), values? or message?, "
                            "target_record_id?, normalized_key?, normalized_value?, source_text?, "
                            "confidence?, name?, target_module?."},
            {"name": "list_pending_suggestions",
             "description": "List the caller's pending review queue items. Params: status?, limit?."},
        ]


# ==================================================================
# Tool implementations
# Each handler signature: (env, token, profile, params, ctx) -> (result, meta)
# ==================================================================
def _tool_health_check(env, token, profile, params, ctx):
    return {
        "status": "ok",
        "module": "boss_claude_connector",
        "version": MODULE_VERSION,
        "profile": profile.name,
    }, {}


def _tool_list_allowed_models(env, token, profile, params, ctx):
    return {
        "profile": profile.name,
        "allowed_models": profile.get_allowed_models_summary(),
    }, {}


def _tool_search_records(env, token, profile, params, ctx):
    model = params.get("model")
    if not model:
        raise ValidationError(_("Missing 'model'."))
    domain_in = params.get("domain") or []
    fields_in = params.get("fields") or None
    limit = int(params.get("limit") or DEFAULT_LIMIT)
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    perm = None
    try:
        perm = profile.check_model_permission(model, "search", fields_in)
    except AccessError:
        perm = profile.check_model_permission(model, "read", fields_in)

    if fields_in is None:
        fields_in = perm.get_allowed_field_names()

    if env.get(model) is None:
        raise ValidationError(_("Model '%s' does not exist.") % model)

    extra_domain = _safe_domain(perm.domain_filter)
    final_domain = list(domain_in) + list(extra_domain)

    records = env[model].sudo().search(final_domain, limit=limit)
    data = records.read(fields_in)
    return {"model": model, "count": len(data), "records": data}, {
        "model_name": model, "operation": "search",
    }


def _tool_read_record(env, token, profile, params, ctx):
    model = params.get("model")
    record_id = params.get("record_id")
    if not model or not record_id:
        raise ValidationError(_("Missing 'model' or 'record_id'."))
    fields_in = params.get("fields") or None
    perm = profile.check_model_permission(model, "read", fields_in)
    if fields_in is None:
        fields_in = perm.get_allowed_field_names()
    if env.get(model) is None:
        raise ValidationError(_("Model '%s' does not exist.") % model)
    rec = env[model].sudo().browse(int(record_id))
    if not rec.exists():
        raise ValidationError(_("Record %s/%s not found.") % (model, record_id))
    extra_domain = _safe_domain(perm.domain_filter)
    if extra_domain:
        filtered = env[model].sudo().search(
            [("id", "=", rec.id)] + extra_domain, limit=1
        )
        if not filtered:
            raise AccessError(_("Record outside of configured domain filter."))
    data = rec.read(fields_in)
    return {"model": model, "record": data[0] if data else None}, {
        "model_name": model, "operation": "read",
    }


def _tool_get_normalization_rules(env, token, profile, params, ctx):
    domain = [("active", "=", True)]
    for key in ("module", "model", "field"):
        val = params.get(key)
        if val:
            domain.append((key, "=", val))
    limit = int(params.get("limit") or 200)
    if limit > 1000:
        limit = 1000
    rules = env["boss.claude.normalization.rule"].sudo().search(domain, limit=limit)
    data = [{
        "id": r.id,
        "name": r.name,
        "module": r.module,
        "model": r.model,
        "field": r.field,
        "raw_value": r.raw_value,
        "normalized_value": r.normalized_value,
        "match_type": r.match_type,
        "confidence": r.confidence,
    } for r in rules]
    return {"count": len(data), "rules": data}, {
        "model_name": "boss.claude.normalization.rule", "operation": "search",
    }


def _tool_normalize_value(env, token, profile, params, ctx):
    raw = params.get("raw_value")
    if not raw:
        raise ValidationError(_("Missing 'raw_value'."))
    res = env["boss.claude.normalization.rule"].sudo().normalize_value(
        raw,
        module=params.get("module"),
        model=params.get("model"),
        field=params.get("field"),
    )
    return res, {
        "model_name": "boss.claude.normalization.rule",
        "operation": "read",
    }


def _tool_validate_codes(env, token, profile, params, ctx):
    """Generic consistency check between two sets of {key: value} entries.

    Default key is 'concept', default value is 'code', so the same tool covers
    the previous validate_sale_prevision_codes use-case without hardcoding it.
    """
    lines_a = params.get("lines_a") or []
    lines_b = params.get("lines_b") or []
    key_field = params.get("key") or "concept"
    value_field = params.get("value") or "code"
    label_a = params.get("label_a") or "set_a"
    label_b = params.get("label_b") or "set_b"

    def _build_map(lines):
        m = {}
        for ln in lines:
            k = _normalize_text(ln.get(key_field))
            v = (ln.get(value_field) or "").strip().upper() if isinstance(ln.get(value_field), str) else ln.get(value_field)
            if not k:
                continue
            m.setdefault(k, set()).add(v)
        return m

    map_a = _build_map(lines_a)
    map_b = _build_map(lines_b)

    warnings = []
    for k in set(map_a) | set(map_b):
        va = map_a.get(k, set())
        vb = map_b.get(k, set())
        if va and vb and va != vb:
            warnings.append({
                "key": k,
                label_a: sorted(va, key=str),
                label_b: sorted(vb, key=str),
                "issue": "mismatch",
            })
        if va and len(va) > 1:
            warnings.append({
                "key": k, label_a: sorted(va, key=str),
                "issue": "multiple_values_in_" + label_a,
            })
        if vb and len(vb) > 1:
            warnings.append({
                "key": k, label_b: sorted(vb, key=str),
                "issue": "multiple_values_in_" + label_b,
            })
    return {
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "%s_keys" % label_a: list(map_a.keys()),
        "%s_keys" % label_b: list(map_b.keys()),
    }, {"operation": "validate"}


def _tool_create_suggestion(env, token, profile, params, ctx):
    """Queue a suggestion. NEVER touches the target model directly."""
    target_model = params.get("target_model")
    target_operation = params.get("target_operation") or "suggest"
    if target_operation not in QUEUEABLE_OPERATIONS:
        raise ValidationError(_("Unsupported target_operation '%s'.") % target_operation)

    if target_operation in ("create", "write", "post_note") and not target_model:
        raise ValidationError(_("'target_model' is required for operation '%s'.") % target_operation)

    target_record_id = int(params.get("target_record_id") or 0)
    if target_operation in ("write", "post_note") and not target_record_id:
        raise ValidationError(_("'target_record_id' is required for operation '%s'.") % target_operation)

    # Pre-validate that the profile *could* perform this operation.
    # We do not actually perform it; we only block obvious abuse early so
    # Claude does not pile up suggestions that will always fail to apply.
    if target_operation == "create":
        values = params.get("values") or {}
        if not isinstance(values, dict):
            raise ValidationError(_("'values' must be a JSON object."))
        profile.check_model_permission(target_model, "create",
                                       list(values.keys()) if values else None)
        profile.validate_draft_only(target_model, values)
        payload = {"values": values}
    elif target_operation == "write":
        values = params.get("values") or {}
        if not isinstance(values, dict):
            raise ValidationError(_("'values' must be a JSON object."))
        profile.check_model_permission(target_model, "write",
                                       list(values.keys()) if values else None)
        profile.validate_draft_only(target_model, values)
        payload = {"values": values}
    elif target_operation == "post_note":
        message = params.get("message")
        if not message:
            raise ValidationError(_("'message' is required for post_note."))
        # Need at least read; prefer write.
        try:
            profile.check_model_permission(target_model, "write")
        except AccessError:
            profile.check_model_permission(target_model, "read")
        payload = {"message": message}
    else:  # suggest
        payload = {"data": params.get("data") or {}}

    name = params.get("name") or (
        "%s/%s" % (target_model or "suggestion", target_operation)
    )

    queue_vals = {
        "name": name,
        "token_id": token.id,
        "access_profile_id": profile.id,
        "target_module": params.get("target_module") or False,
        "target_model": target_model or False,
        "target_record_id": target_record_id,
        "target_operation": target_operation,
        "payload_json": json.dumps(payload, default=str),
        "normalized_key": params.get("normalized_key") or False,
        "normalized_value": params.get("normalized_value") or False,
        "source_text": params.get("source_text") or False,
        "confidence": float(params.get("confidence") or 0.0),
        "status": "pending",
    }
    qrec = env["boss.claude.review.queue"].sudo().create(queue_vals)
    if ctx is not None:
        ctx["request_log_id"] = False  # filled later by controller
    return {
        "review_queue_id": qrec.id,
        "name": qrec.name,
        "status": qrec.status,
        "target_model": qrec.target_model,
        "target_operation": qrec.target_operation,
    }, {
        "model_name": "boss.claude.review.queue",
        "operation": "queue_" + target_operation,
        "created_record_model": "boss.claude.review.queue",
        "created_record_id": qrec.id,
        "review_queue_id": qrec.id,
    }


def _tool_list_pending_suggestions(env, token, profile, params, ctx):
    """List queue items for this profile, optionally filtered by status."""
    status = params.get("status") or "pending"
    limit = int(params.get("limit") or 50)
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    domain = [("access_profile_id", "=", profile.id)]
    if status and status != "all":
        domain.append(("status", "=", status))
    queue = env["boss.claude.review.queue"].sudo().search(
        domain, limit=limit, order="create_date desc"
    )
    data = [{
        "id": q.id,
        "name": q.name,
        "status": q.status,
        "target_model": q.target_model,
        "target_operation": q.target_operation,
        "target_record_id": q.target_record_id,
        "normalized_key": q.normalized_key,
        "normalized_value": q.normalized_value,
        "confidence": q.confidence,
        "applied_record_model": q.applied_record_model,
        "applied_record_id": q.applied_record_id,
        "create_date": q.create_date,
        "approved_date": q.approved_date,
        "applied_date": q.applied_date,
        "error_message": q.error_message,
    } for q in queue]
    return {"count": len(data), "items": data}, {
        "model_name": "boss.claude.review.queue",
        "operation": "search",
    }


# Registry
_TOOL_REGISTRY = {
    "health_check": _tool_health_check,
    "list_allowed_models": _tool_list_allowed_models,
    "search_records": _tool_search_records,
    "read_record": _tool_read_record,
    "get_normalization_rules": _tool_get_normalization_rules,
    "normalize_value": _tool_normalize_value,
    "validate_codes": _tool_validate_codes,
    "create_suggestion": _tool_create_suggestion,
    "list_pending_suggestions": _tool_list_pending_suggestions,
}
