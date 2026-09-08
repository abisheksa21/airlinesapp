"""Security dependencies for state-changing API operations."""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Header, HTTPException

from config import APP_ENV, PIPELINE_ADMIN_TOKEN


def require_pipeline_admin(
    token: Optional[str] = Header(None, alias="X-Pipeline-Admin-Token"),
) -> None:
    """Protect the warehouse-writing endpoint without breaking local setup."""
    if PIPELINE_ADMIN_TOKEN:
        if not token or not secrets.compare_digest(token, PIPELINE_ADMIN_TOKEN):
            raise HTTPException(status_code=401, detail="Valid pipeline admin token required.")
        return
    if APP_ENV == "production":
        raise HTTPException(
            status_code=503,
            detail="Pipeline administration is disabled until PIPELINE_ADMIN_TOKEN is configured.",
        )
