from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import Usuario
from app.services.metricas_service import MetricasService

router = APIRouter(prefix="/metricas", tags=["Métricas"])


@router.get("")
def resumen_completo(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Tablero del admin. Solo su sitio."""
    sitio_id = admin.sitio_id
    return {
        "tickets": MetricasService.resumen(db, sitio_id, dias=dias),
        "base_conocimiento": MetricasService.base_conocimiento(db, sitio_id),
        "chatbot": MetricasService.chatbot(db, sitio_id),
        "ollama": MetricasService.ollama_estado(),
    }
