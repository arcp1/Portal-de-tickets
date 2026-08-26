from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import Usuario
from app.schemas.chat import (
    ChatEscalarRequest,
    ChatEstadoResponse,
    ChatMensajeRequest,
    ChatMensajeResponse,
)
from app.services.chat_service import ChatService
from app.services.ollama_client import ollama

router = APIRouter(prefix="/chat", tags=["Chatbot"])


@router.get("/estado", response_model=ChatEstadoResponse)
def estado_chat(current_user: Usuario = Depends(get_current_user)):
    """Le dice al frontend si dibujar el widget.

    Si Ollama no está disponible el widget se oculta y queda el formulario con
    dropdown, que nunca deja de funcionar.
    """
    return ChatEstadoResponse(
        disponible=ollama.disponible(),
        max_intercambios=settings.CHAT_MAX_INTERCAMBIOS,
    )


@router.post("/mensaje", response_model=ChatMensajeResponse)
def enviar_mensaje(
    peticion: ChatMensajeRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Clasifica el mensaje hacia una categoría y decide el siguiente paso.

    Nunca devuelve error por un fallo de IA: responde 200 con
    ``accion: "no_disponible"`` y el widget se oculta solo.
    """
    return ChatService.procesar_mensaje(
        db=db,
        usuario=current_user,
        mensaje=peticion.mensaje,
        sesion_id=peticion.sesion_id,
    )


@router.post("/escalar", response_model=ChatMensajeResponse)
def escalar(
    peticion: ChatEscalarRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """'Hablar con un técnico'. Cierra la sesión y manda al formulario.

    Está disponible en todo momento: nadie se queda atrapado en un bot.
    """
    return ChatService.escalar_a_tecnico(
        db=db,
        usuario=current_user,
        sesion_id=peticion.sesion_id,
    )
