"""Adjuntos de tickets: fotos del error, del LED parpadeando, de la pantalla.

En planta una foto ahorra media conversación. El binario va a disco; la base
solo guarda dónde está.
"""

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.logging import logger
from app.models import Ticket, TicketAdjunto, Usuario
from app.schemas.ticket import AdjuntoResponse

router = APIRouter(prefix="/tickets", tags=["Adjuntos"])

# Solo lo que un técnico necesita ver. Nada ejecutable: un portal interno no es
# lugar para intercambiar binarios arbitrarios.
TIPOS_PERMITIDOS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}


def _carpeta() -> Path:
    ruta = Path(settings.ADJUNTOS_RUTA)
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _ticket_accesible(db: Session, ticket_id: int, usuario: Usuario) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    if usuario.rol != "admin" and ticket.usuario_id != usuario.id:
        raise HTTPException(status_code=403, detail="No autorizado para este ticket")
    return ticket


@router.post("/{ticket_id}/adjuntos", response_model=AdjuntoResponse,
             status_code=status.HTTP_201_CREATED)
async def subir_adjunto(
    ticket_id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    ticket = _ticket_accesible(db, ticket_id, current_user)

    cuantos = db.query(TicketAdjunto).filter(TicketAdjunto.ticket_id == ticket.id).count()
    if cuantos >= settings.ADJUNTOS_MAX_POR_TICKET:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Máximo {settings.ADJUNTOS_MAX_POR_TICKET} archivos por ticket.",
        )

    # El tipo se decide por el contenido declarado y la extensión, no solo por
    # lo que diga el cliente.
    tipo = (archivo.content_type or "").split(";")[0].strip().lower()
    if tipo not in TIPOS_PERMITIDOS:
        adivinado = mimetypes.guess_type(archivo.filename or "")[0]
        if adivinado in TIPOS_PERMITIDOS:
            tipo = adivinado
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tipo de archivo no permitido. Se aceptan imágenes, PDF y texto.",
            )

    # Se lee acotado: sin esto un archivo enorme se carga entero en memoria
    # antes de poder rechazarlo.
    limite = settings.ADJUNTOS_MAX_MB * 1024 * 1024
    contenido = await archivo.read(limite + 1)
    if len(contenido) > limite:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo supera {settings.ADJUNTOS_MAX_MB} MB.",
        )
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")

    # Nombre generado: el del usuario nunca toca el sistema de archivos.
    nombre_guardado = f"{uuid.uuid4().hex}{TIPOS_PERMITIDOS[tipo]}"
    (_carpeta() / nombre_guardado).write_bytes(contenido)

    adjunto = TicketAdjunto(
        ticket_id=ticket.id,
        subido_por=current_user.id,
        nombre_original=(archivo.filename or "archivo")[:255],
        nombre_guardado=nombre_guardado,
        tipo_mime=tipo,
        tamano_bytes=len(contenido),
        creado_en=datetime.utcnow(),
    )
    db.add(adjunto)
    db.commit()
    db.refresh(adjunto)

    logger.info("Adjunto subido", extra={"ticket_id": ticket.id, "adjunto_id": adjunto.id,
                                         "bytes": adjunto.tamano_bytes})
    return adjunto


@router.get("/{ticket_id}/adjuntos", response_model=List[AdjuntoResponse])
def listar_adjuntos(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    ticket = _ticket_accesible(db, ticket_id, current_user)
    return (
        db.query(TicketAdjunto)
        .filter(TicketAdjunto.ticket_id == ticket.id)
        .order_by(TicketAdjunto.creado_en)
        .all()
    )


@router.get("/{ticket_id}/adjuntos/{adjunto_id}")
def descargar_adjunto(
    ticket_id: int,
    adjunto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _ticket_accesible(db, ticket_id, current_user)
    adjunto = db.query(TicketAdjunto).filter(
        TicketAdjunto.id == adjunto_id,
        TicketAdjunto.ticket_id == ticket_id,
    ).first()
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    ruta = _carpeta() / adjunto.nombre_guardado
    if not ruta.exists():
        # La fila existe pero el archivo no: pasa si se restauró la base sin el
        # volumen. Se dice claro en vez de devolver un 500.
        raise HTTPException(status_code=410, detail="El archivo ya no está disponible en el servidor.")

    return FileResponse(
        path=str(ruta),
        media_type=adjunto.tipo_mime,
        filename=adjunto.nombre_original,
        # inline permite ver la foto en el navegador sin descargarla.
        content_disposition_type="inline",
    )


@router.delete("/{ticket_id}/adjuntos/{adjunto_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_adjunto(
    ticket_id: int,
    adjunto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    _ticket_accesible(db, ticket_id, current_user)
    adjunto = db.query(TicketAdjunto).filter(
        TicketAdjunto.id == adjunto_id,
        TicketAdjunto.ticket_id == ticket_id,
    ).first()
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    # Quien lo subió, o un admin.
    if current_user.rol != "admin" and adjunto.subido_por != current_user.id:
        raise HTTPException(status_code=403, detail="Solo quien lo subió puede borrarlo.")

    ruta = _carpeta() / adjunto.nombre_guardado
    try:
        ruta.unlink(missing_ok=True)
    except OSError as exc:
        # Si el archivo no se puede borrar, la fila se va igual: dejarla sería
        # mostrar un adjunto que el usuario ya pidió quitar.
        logger.warning("No se pudo borrar el archivo en disco",
                       extra={"ruta": str(ruta), "error": str(exc)})

    db.delete(adjunto)
    db.commit()
    return None
