"""Imágenes del conocimiento: los pasos, la base de conocimiento, la solución
de un ticket y los procedimientos de Soluciones generales.

**Para qué.** Las tres eran texto puro. "Pulse el botón de reinicio de la parte
trasera" obliga a buscar un botón; con la foto de dónde está, se pulsa a la
primera. Y la solución de un ticket es lo que la persona abre para ver cómo le
arreglaron su problema: una captura de lo que se cambió dice más que el
párrafo que lo describe.

**Quién hace qué.**

  * Sube, corrige el pie y borra: **solo TI**. Es contenido que se le enseña a
    la gente como respuesta; si cualquiera pudiera añadir imágenes, cualquiera
    podría escribir las instrucciones de los demás.
  * Ve: quien ya puede ver el texto al que acompañan, ni más ni menos.

      - un **paso** activo, todo el que entra al portal (el checklist se le
        enseña a quien levanta un ticket); uno dado de baja, solo TI.
      - una entrada de la **base de conocimiento**, todo el que entra. El
        conocimiento se comparte entre plantas —las sugerencias no filtran
        por planta—, así que su texto ya lo lee cualquiera; negarle la foto
        dejaría una imagen rota debajo de un texto que sí ve.
      - la **solución de un ticket**, quien lo reportó y TI. Exactamente lo
        mismo que el ticket: es la regla de `_ticket_visible`. **Y además
        todo el mundo, en cuanto el ticket pasa a la base de conocimiento**:
        la entrada que sale de él enlaza esas capturas (ver
        `BaseConocimiento.imagenes_de_ticket`), y su texto ya lo lee
        cualquiera. Si la entrada se borra, vuelven a ser solo del ticket.
      - un procedimiento de **Soluciones generales**, todo el que entra si
        está publicado —es lo que el asistente le cita a cualquiera—; un
        borrador o uno archivado, solo TI.

Lo que no se alcanza responde 404, nunca 403: un 403 confirmaría que el id
existe (ver app/core/plantas.py).

**La validación es la de los adjuntos**, no una propia: tipo declarado o por
extensión, y además la firma de los primeros bytes (`contenido_coincide`), para
que un HTML que se presenta como PNG no se sirva desde el origen del portal.
Solo JPG, PNG, WEBP y GIF: HEIC no lo pinta ningún navegador fuera de Safari,
y una imagen que la persona no puede ver no explica nada.
"""

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core import plantas
from app.core.archivos import contenido_coincide
from app.core.metadatos import limpiar_subida
from app.core.config import settings
from app.core.db import get_db
from app.core.logging import logger
from app.models import (BaseConocimiento, Checklist, ImagenConocimiento, SolucionGeneral,
                        Ticket, Usuario)
from app.schemas.imagenes import ImagenBreve, ImagenUpdate
from app.services import eventos_service as eventos
from app.services.auditoria_service import AuditoriaService

router = APIRouter(prefix="/imagenes", tags=["Imágenes del conocimiento"])

IMAGEN_SUBIDA = "imagen_conocimiento.subida"
IMAGEN_BORRADA = "imagen_conocimiento.borrada"

TIPOS_IMAGEN = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

#: A qué pertenece una imagen. Es también el segmento de la URL.
Dueno = Literal["paso", "kb", "ticket", "solucion"]

#: La columna de `ImagenConocimiento` que apunta a cada tipo de dueño.
_COLUMNA = {"paso": "paso_id", "kb": "kb_id", "ticket": "ticket_id", "solucion": "solucion_id"}


def carpeta() -> Path:
    """Dentro de ADJUNTOS_RUTA a propósito: el mismo volumen que ya se
    respalda, y el que las pruebas aíslan en un temporal."""
    ruta = Path(settings.ADJUNTOS_RUTA) / "conocimiento"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _no_encontrado():
    return HTTPException(status_code=404, detail="No encontrado")


def _dueno(db: Session, tipo: str, ident: int, usuario: Usuario, escribir: bool):
    """El paso, la entrada o el ticket, si esta persona puede verlo —o
    modificar sus imágenes, con `escribir`—. Si no, 404."""
    es_ti = usuario.rol == "admin"
    if escribir and not es_ti:
        # Este 403 no delata nada: dice que la operación es de TI, no que el
        # recurso exista. Es el mismo que da `get_current_admin`.
        raise HTTPException(status_code=403, detail="Esta operación es solo para el equipo de TI.")

    if tipo == "paso":
        paso = db.get(Checklist, ident)
        if not paso or not (paso.activo or es_ti):
            raise _no_encontrado()
        return paso

    if tipo == "kb":
        entrada = db.get(BaseConocimiento, ident)
        if not entrada:
            raise _no_encontrado()
        return entrada

    if tipo == "ticket":
        ticket = db.get(Ticket, ident)
        propio = ticket is not None and ticket.usuario_id == usuario.id and not escribir
        de_ti = ticket is not None and es_ti and plantas.alcanza(usuario, ticket.sitio_id)
        if not (propio or de_ti):
            raise _no_encontrado()
        return ticket

    if tipo == "solucion":
        solucion = db.get(SolucionGeneral, ident)
        if not solucion or not (solucion.estado == "publicada" or es_ti):
            raise _no_encontrado()
        return solucion

    raise _no_encontrado()


def _en_la_base_de_conocimiento(db: Session, ticket_id: int) -> bool:
    """Si una entrada de la base salió de este ticket: entonces su solución
    —y sus capturas— ya son conocimiento de todos."""
    return db.query(BaseConocimiento.id).filter(
        BaseConocimiento.ticket_origen_id == ticket_id).first() is not None


def _de(db: Session, tipo: str, ident: int) -> List[ImagenConocimiento]:
    columna = getattr(ImagenConocimiento, _COLUMNA[tipo])
    return (db.query(ImagenConocimiento)
            .filter(columna == ident)
            .order_by(ImagenConocimiento.orden, ImagenConocimiento.id)
            .all())


def _tipo_y_dueno(imagen: ImagenConocimiento):
    for tipo, columna in _COLUMNA.items():
        ident = getattr(imagen, columna)
        if ident is not None:
            return tipo, ident
    return None, None


def _imagen_accesible(db: Session, imagen_id: int, usuario: Usuario, escribir: bool):
    imagen = db.get(ImagenConocimiento, imagen_id)
    if not imagen:
        raise _no_encontrado()
    tipo, ident = _tipo_y_dueno(imagen)
    if tipo is None:
        raise _no_encontrado()
    try:
        dueno = _dueno(db, tipo, ident, usuario, escribir)
    except HTTPException as exc:
        # La captura de la solución de un ticket ajeno se ve si ese ticket ya
        # es una entrada de la base de conocimiento: la entrada la enlaza.
        # Solo para mirar; tocarla sigue siendo cosa de TI desde el ticket.
        enlazada = (tipo == "ticket" and not escribir and exc.status_code == 404
                    and _en_la_base_de_conocimiento(db, ident))
        if not enlazada:
            raise
        dueno = db.get(Ticket, ident)
    return imagen, tipo, dueno


def _avisar(tipo: str, dueno) -> None:
    """La solución de un ticket la está mirando quien lo reportó: que la
    pantalla abierta se entere sin recargar."""
    if tipo == "ticket":
        eventos.publicar(dueno.sitio_id, "tickets")


# ----------------------------------------------------------------------
# Una imagen suelta. Van antes que las de colección: comparten forma de ruta
# con `/{tipo}/{id}` solo en apariencia —aquí es un segmento, allá dos—, pero
# así el orden no depende de esa casualidad.
# ----------------------------------------------------------------------
@router.get("/{imagen_id}")
def ver_imagen(
    imagen_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """El archivo, en línea, para quien puede ver el texto al que acompaña."""
    imagen, _, _ = _imagen_accesible(db, imagen_id, usuario, escribir=False)
    ruta = carpeta() / imagen.nombre_guardado
    if not ruta.exists():
        # La fila está y el archivo no: pasa al restaurar la base sin el
        # volumen. Se dice claro en vez de devolver un 500.
        raise HTTPException(status_code=410, detail="La imagen ya no está disponible en el servidor.")
    return FileResponse(
        path=str(ruta),
        media_type=imagen.tipo_mime,
        filename=imagen.nombre_original,
        content_disposition_type="inline",
        # Detrás del token: que ningún intermediario la guarde para otro.
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.patch("/{imagen_id}", response_model=List[ImagenBreve])
def editar_imagen(
    imagen_id: int,
    cambios: ImagenUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """El pie de foto o el lugar en la secuencia."""
    imagen, tipo, dueno = _imagen_accesible(db, imagen_id, admin, escribir=True)
    if cambios.pie is not None:
        imagen.pie = cambios.pie or None
    if cambios.orden is not None:
        imagen.orden = cambios.orden
    db.commit()
    _avisar(tipo, dueno)
    return _de(db, tipo, dueno.id)


@router.delete("/{imagen_id}", response_model=List[ImagenBreve])
def borrar_imagen(
    imagen_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    imagen, tipo, dueno = _imagen_accesible(db, imagen_id, admin, escribir=True)
    archivo = carpeta() / imagen.nombre_guardado
    AuditoriaService.registrar(db, admin, IMAGEN_BORRADA, tipo, dueno.id,
                               {"archivo": imagen.nombre_original}, peticion)
    db.delete(imagen)
    db.commit()
    # Primero la fila y después el archivo: si el commit fallara con el
    # archivo ya borrado, la pantalla enseñaría una imagen que no abre.
    try:
        archivo.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("No se pudo borrar la imagen en disco",
                       extra={"imagen": archivo.name, "error": str(exc)})
    _avisar(tipo, dueno)
    return _de(db, tipo, dueno.id)


# ----------------------------------------------------------------------
# Las imágenes de un paso, de una entrada o de la solución de un ticket.
# ----------------------------------------------------------------------
@router.get("/{tipo}/{ident}", response_model=List[ImagenBreve])
def listar_imagenes(
    tipo: Dueno,
    ident: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    dueno = _dueno(db, tipo, ident, usuario, escribir=False)
    if tipo == "kb":
        # Las suyas y las que enlaza de su ticket de origen: es lo que se le
        # enseña a quien lee la entrada.
        return _de(db, tipo, dueno.id) + dueno.imagenes_de_ticket
    return _de(db, tipo, dueno.id)


@router.post("/{tipo}/{ident}", response_model=List[ImagenBreve],
             status_code=status.HTTP_201_CREATED)
async def subir_imagen(
    tipo: Dueno,
    ident: int,
    peticion: Request,
    archivo: UploadFile = File(...),
    pie: str = Form(""),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Añade una imagen al final de la secuencia y devuelve la secuencia."""
    dueno = _dueno(db, tipo, ident, admin, escribir=True)

    existentes = _de(db, tipo, dueno.id)
    if len(existentes) >= settings.IMAGENES_MAX_POR_ELEMENTO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Máximo {settings.IMAGENES_MAX_POR_ELEMENTO} imágenes por elemento.",
        )

    tipo_mime = (archivo.content_type or "").split(";")[0].strip().lower()
    if tipo_mime not in TIPOS_IMAGEN:
        adivinado = mimetypes.guess_type(archivo.filename or "")[0]
        if adivinado in TIPOS_IMAGEN:
            tipo_mime = adivinado
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Aquí solo caben imágenes: JPG, PNG, WEBP o GIF.",
            )

    # Acotado al leer: sin esto un archivo enorme se carga entero en memoria
    # antes de poder rechazarlo.
    limite = settings.IMAGENES_MAX_MB * 1024 * 1024
    contenido = await archivo.read(limite + 1)
    if len(contenido) > limite:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"La imagen supera {settings.IMAGENES_MAX_MB} MB.",
        )
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")
    if not contenido_coincide(contenido, tipo_mime):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El contenido del archivo no corresponde a su tipo.",
        )

    # Sin metadatos: ni GPS, ni cámara, ni fecha (ver core/metadatos.py). Va
    # antes de escribir, para que el tamaño guardado sea el del archivo limpio.
    contenido = await limpiar_subida(contenido, tipo_mime)

    # Nombre generado: el del usuario nunca toca el sistema de archivos.
    nombre_guardado = f"{uuid.uuid4().hex}{TIPOS_IMAGEN[tipo_mime]}"
    destino = carpeta() / nombre_guardado
    destino.write_bytes(contenido)

    imagen = ImagenConocimiento(
        orden=max([i.orden or 0 for i in existentes] or [0]) + 1,
        pie=(pie or "").strip()[:300] or None,
        nombre_original=(archivo.filename or "imagen")[:255],
        nombre_guardado=nombre_guardado,
        tipo_mime=tipo_mime,
        tamano_bytes=len(contenido),
        subido_por=admin.id,
        creado_en=datetime.utcnow(),
    )
    setattr(imagen, _COLUMNA[tipo], dueno.id)
    db.add(imagen)
    try:
        db.commit()
    except Exception:
        # Sin fila, el archivo no lo encontraría nadie: se retira.
        db.rollback()
        destino.unlink(missing_ok=True)
        raise

    AuditoriaService.registrar(db, admin, IMAGEN_SUBIDA, tipo, dueno.id,
                               {"archivo": imagen.nombre_original, "bytes": imagen.tamano_bytes},
                               peticion)
    logger.info("Imagen de conocimiento subida",
                extra={"tipo": tipo, "dueno": dueno.id, "bytes": imagen.tamano_bytes})
    _avisar(tipo, dueno)
    return _de(db, tipo, dueno.id)


def borrar_archivos(nombres: List[str]) -> None:
    """Para quien borra un dueño entero: la base ya se llevó las filas
    (ON DELETE CASCADE); esto retira los archivos, después del commit."""
    for nombre in nombres:
        try:
            (carpeta() / nombre).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("No se pudo borrar la imagen en disco",
                           extra={"imagen": nombre, "error": str(exc)})
