from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.core.logging import logger
from app.models import Ticket, Usuario
from app.schemas.kb import (
    FeedbackRequest,
    FeedbackResponse,
    IndexarResponse,
    MetricasKBResponse,
    SimilaresRequest,
    SimilaresResponse,
)
from app.services.kb_service import KBService, solucion_es_valida

router = APIRouter(tags=["Base de conocimiento"])


@router.post("/ia/similares", response_model=SimilaresResponse)
def buscar_similares(
    peticion: SimilaresRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Incidencias parecidas ya resueltas.

    Nunca devuelve error por un fallo de IA: si Ollama no está disponible
    responde 200 con la lista vacía y ``degradado: true``, y el frontend
    simplemente no muestra el bloque de sugerencias.
    """
    return KBService.buscar_similares(
        db=db,
        texto=peticion.texto,
        sitio_id=peticion.sitio_id,
        categoria=peticion.categoria,
        usuario_id=current_user.id,
        ticket_id=peticion.ticket_id,
    )


@router.post("/kb/feedback", response_model=FeedbackResponse)
def registrar_feedback(
    peticion: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """El '¿te sirvió?'.

    Es lo que permite calibrar el umbral de similitud con datos reales en lugar
    de a ojo.
    """
    sugerencia = KBService.registrar_feedback(
        db=db,
        sugerencia_id=peticion.sugerencia_id,
        fue_util=peticion.fue_util,
    )
    if not sugerencia:
        raise HTTPException(status_code=404, detail="Sugerencia no encontrada")

    return FeedbackResponse(
        ok=True,
        sugerencia_id=sugerencia.id,
        fue_util=sugerencia.fue_util,
    )


@router.post("/kb/indexar/{ticket_id}", response_model=IndexarResponse)
def indexar_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Indexa un ticket resuelto a mano. Sirve también para reprocesar los que
    quedaron pendientes porque Ollama estaba caído al momento del cierre."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    if not solucion_es_valida(ticket.solucion):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El ticket no tiene una solución documentada: no se puede indexar.",
        )

    indexado = KBService.indexar_ticket(db, ticket)
    return IndexarResponse(
        ok=indexado,
        embedding_generado=indexado,
        motivo=None if indexado else "Ya estaba indexado o el servicio de embeddings no respondió.",
    )


@router.get("/kb/metricas", response_model=MetricasKBResponse)
def metricas_kb(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Tasa de utilidad y estado de la base de conocimiento."""
    return KBService.metricas(db, sitio_id=admin.sitio_id)
