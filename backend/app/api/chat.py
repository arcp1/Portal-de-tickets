from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, usuario_con_cupo_ia
from app.core.config import settings
from app.core.db import get_db
from app.models import Usuario
from app.schemas.chat import (
    ChatEscalarRequest,
    ChatEstadoResponse,
    ChatMensajeRequest,
    ChatMensajeResponse,
)
from app.services.asistente_service import AsistenteService
from app.services.chat_service import ChatService
from app.services.ollama_client import ollama
from app.services.recuperacion_service import RecuperacionService
from app.services.visual_service import VisualService

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
    current_user: Usuario = Depends(usuario_con_cupo_ia),
):
    """Primero mira si es un problema que se ve; luego busca la respuesta; y
    sólo si no la hay, clasifica y escala.

    Ese orden es el punto.

    **Lo visual va delante de todo**, y no por importancia sino porque es lo
    único que *pregunta* en vez de afirmar. "Mi copia sale borrosa", "sale con
    una raya" y "sale con sombra doble" se parecen tanto entre sí que la
    búsqueda por significado las confunde, y las tres se arreglan distinto;
    enseñar las fotos y dejar que la persona señale la suya resuelve en dos
    segundos lo que ningún parecido de coseno decide bien. Si el mensaje no
    describe nada visible —o no hay foto de eso— esta parte no se entera y todo
    sigue exactamente como antes: ver `visual_service.py`.

    Después, si alguien escribe "me sale una raya negra" y eso ya se resolvió,
    **no tiene sentido preguntarle de qué categoría es**: se le da la solución
    ahí mismo y se acabó. La clasificación existe para lo que todavía no
    sabemos, no para lo que ya está escrito.

    Nunca devuelve error por un fallo de IA: responde 200 con
    ``accion: "no_disponible"`` y el widget se oculta solo.
    """
    # **El mensaje se vectoriza una vez para los dos caminos.**
    #
    # Antes de esto, un mensaje que sonara a defecto visual y no tuviera foto
    # se vectorizaba dos veces —una en el catálogo, otra dentro del asistente
    # de texto al que cae después—, y un embedding cuesta aquí entre 74 y 579
    # ms según la frase. Es el mismo ahorro que ya hace el endpoint del grafo
    # pasando su vector a `RecuperacionService.buscar`.
    #
    # `None` es una respuesta válida: significa que Ollama no está. Cada uno de
    # los dos caminos sabe degradar por su cuenta —el catálogo a coincidencia
    # literal por frases, el asistente a no responder— y ninguno levanta.
    vector = ollama.generar_embedding(peticion.mensaje, tarea="consulta")

    if not peticion.omitir_visual:
        visual = VisualService.reconocer(
            db, peticion.mensaje, current_user.sitio_id,
            usuario_id=current_user.id, vector=vector,
        )
        if visual["activado"]:
            return ChatMensajeResponse(
                sesion_id=peticion.sesion_id,
                accion="reconocer_imagen",
                fichas=visual["candidatas"],
                descripcion_sugerida=peticion.mensaje,
            )

    # Sin vector no hay búsqueda posible, así que se le entrega la lista vacía
    # en vez de dejar que la calcule: con Ollama caído, `buscar` volvería a
    # intentar el embedding y pagaría **otro** timeout entero antes de devolver
    # lo mismo. Una lista vacía —y no `None`— es lo que le dice al asistente
    # que no busque de nuevo.
    respuesta = AsistenteService.responder(
        db, pregunta=peticion.mensaje, sitio_id=current_user.sitio_id,
        pasajes=(
            RecuperacionService.buscar(
                db, peticion.mensaje, current_user.sitio_id, vector=vector)
            if vector is not None else []
        ),
    )
    if respuesta["fundamentada"] and respuesta["respuesta"]:
        return ChatMensajeResponse(
            sesion_id=peticion.sesion_id,
            respuesta=respuesta["respuesta"],
            accion="solucion",
            fuentes=respuesta["fuentes"],
            descripcion_sugerida=peticion.mensaje,
        )

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
