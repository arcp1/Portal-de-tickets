"""Tipos compartidos por los esquemas de respuesta."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def _marcar_utc(valor: datetime) -> str:
    """Serializa una fecha dejando explícito que es UTC.

    Todo se guarda en UTC pero como `datetime` ingenuo (sin tzinfo). Al
    serializar, Pydantic producía `2026-08-26T16:11:41` sin marca de zona, y
    `new Date(...)` en el navegador interpreta eso como **hora local**. En
    Querétaro (UTC-6) eso desfasaba cada fecha seis horas: los SLA vencidos se
    veían como vigentes y las horas de creación salían mal.

    Con la `Z` al final el navegador la convierte bien a la hora del usuario.
    """
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


#: Fecha que viaja al cliente con su zona explícita.
FechaUTC = Annotated[datetime, PlainSerializer(_marcar_utc, return_type=str)]
