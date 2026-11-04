"""Actionable client errors with a correlation ID for private server diagnostics."""
import logging
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def fail(request, status, code, message, *, stage, target=None, upstream_status=None, reason=None):
    request_id = getattr(request.state, 'collection_request_id', None) if request else None
    request_id = request_id or uuid4().hex[:12]
    if request:
        request.state.collection_request_id = request_id
    # Targets stay in server logs. Never log headers, tokens, query strings or response bodies.
    logger.warning('collection_error request_id=%s code=%s stage=%s status=%s '
                   'upstream_status=%s route=%r target=%r reason=%r',
                   request_id, code, stage, status, upstream_status,
                   request.url.path if request else None, target, reason)
    detail = {'code': code, 'message': message, 'stage': stage, 'request_id': request_id}
    if upstream_status is not None:
        detail['upstream_status'] = upstream_status
    raise HTTPException(status, detail) from None
