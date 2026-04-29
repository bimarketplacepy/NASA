"""Schema de error estandar para respuestas HTTP."""

from datetime import datetime

from pydantic import BaseModel


class ErrorRespuesta(BaseModel):
    """Contrato de error estructurado."""

    error_code: str
    message: str
    details: dict | None = None
    timestamp: datetime
    request_id: str
