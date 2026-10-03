from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user, usuario_con_cupo_ia
from app.core.db import get_db
from app.models import SugerenciaKB, Ticket, Usuario
from app.schemas.kb import (
    FeedbackRequest,
    FeedbackResponse,
    IndexarResponse,
    MetricasKBResponse,
    NormalizarRequest,
    NormalizarResponse,
    SimilaresRequest,
    SimilaresResponse,
)
from app.services.kb_service import KBService, solucion_es_valida
from app.services.ollama_client import ollama

router = APIRouter(tags=["Base de conocimiento"])


@router.post("/ia/normalizar", response_model=NormalizarResponse)
def normalizar(
    peticion: NormalizarRequest,
    current_user: Usuario = Depends(usuario_con_cupo_ia),
):
    """Reescribe texto libre en una descripción legible para el técnico.

    Si Ollama no responde devuelve el texto original con confianza 0: la
    normalización es una mejora, nunca un requisito.
    """
    normalizado = ollama.normalizar_descripcion(peticion.texto)
    if normalizado is None:
        return NormalizarResponse(
            texto_normalizado=peticion.texto,
            confianza=0.0,
            degradado=True,
        )
    return NormalizarResponse(texto_normalizado=normalizado, confianza=1.0)


@router.post("/ia/similares", response_model=SimilaresResponse)
def buscar_similares(
    peticion: SimilaresRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(usuario_con_cupo_ia),
):
    """Incidencias parecidas ya resueltas.

    Nunca devuelve error por un fallo de IA: si Ollama no está disponible
    responde 200 con la lista vacía y ``degradado: true``, y el frontend
    simplemente no muestra el bloque de sugerencias.

    El `sitio_id` del cuerpo se ignora a proposito. Se aceptaba tal cual, asi
    que cualquiera con sesion podia pedir el sitio que quisiera y leer la base
    de conocimiento de otra planta: titulos y solucion completa. La planta la
    decide la sesion, no quien pregunta.
    """
    return KBService.buscar_similares(
        db=db,
        texto=peticion.texto,
        sitio_id=current_user.sitio_id,
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

    Solo se acepta el voto de quien recibio la sugerencia. Antes se tomaba
    cualquier `sugerencia_id`, asi que con una sesion cualquiera se podian votar
    sugerencias ajenas en masa. No es un robo de datos, pero `veces_util /
    veces_sugerida` es justo lo que calibra el umbral de similitud: envenenarlo
    degrada las sugerencias de toda la planta.
    """
    propia = (
        db.query(SugerenciaKB)
        .filter(SugerenciaKB.id == peticion.sugerencia_id,
                SugerenciaKB.usuario_id == current_user.id)
        .first()
    )
    if not propia:
        raise HTTPException(status_code=404, detail="Sugerencia no encontrada")

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
    # TI es global y el conocimiento se comparte entre plantas.
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    if not solucion_es_valida(ticket.solucion):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    return KBService.metricas(db, sitio_id=None)
