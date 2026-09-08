"""Small request/response contracts shared by API route modules."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    history: Optional[list[dict[str, str]]] = None
    tier: Optional[Literal["public", "researcher"]] = None
