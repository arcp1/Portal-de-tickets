"""Estado operativo del portal: horario de TI y SLA.

Lo consume el frontend para decirle la verdad al usuario sobre cuándo lo van a
atender, en vez de dejarlo esperando una respuesta que no va a llegar hasta
mañana.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import settings
from app.models import Usuario
from app.services.horario_service import HorarioService

router = APIRouter(tags=["Estado"])


@router.get("/estado/horario")
def horario(current_user: Usuario = Depends(get_current_user)):
    contexto = HorarioService.contexto()
    return {
        **contexto,
        "sla_horas": {
            "critica": settings.SLA_HORAS_CRITICA,
            "alta": settings.SLA_HORAS_ALTA,
            "media": settings.SLA_HORAS_MEDIA,
            "baja": settings.SLA_HORAS_BAJA,
        },
    }
