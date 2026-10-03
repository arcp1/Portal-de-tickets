"""Documentos del expediente de una persona.

Resguardos firmados escaneados, cartas responsivas, políticas aceptadas. Los
binarios van a disco igual que los adjuntos de tickets; la fila guarda qué es y
dónde está.

Reglas de acceso: una persona **ve** sus documentos pero no los sube ni los
borra. Su expediente lo administra TI; si el propio interesado pudiera quitar
una responsiva firmada, el expediente no serviría de nada.
"""

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.archivos import contenido_coincide
from app.core.config import settings
from app.core import plantas
from app.core.db import get_db
from app.core.logging import logger
from app.models import DocumentoUsuario, Resguardo, Usuario
from app.schemas.resguardo import TIPOS_DOCUMENTO, DocumentoResponse

router = APIRouter(prefix="/documentos", tags=["Documentos"])

TIPOS_PERMITIDOS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _carpeta() -> Path:
    ruta = Path(settings.DOCUMENTOS_RUTA)
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _con_vencimiento(d: DocumentoUsuario) -> dict:
    return {
        "id": d.id, "usuario_id": d.usuario_id, "tipo": d.tipo, "titulo": d.titulo,
        "descripcion": d.descripcion, "resguardo_id": d.resguardo_id,
        "nombre_original": d.nombre_original, "tipo_mime": d.tipo_mime,
        "tamano_bytes": d.tamano_bytes, "vigente_hasta": d.vigente_hasta,
        "creado_en": d.creado_en, "autor": d.autor,
        "vencido": bool(d.vigente_hasta and d.vigente_hasta < datetime.utcnow()),
    }


@router.get("/usuario/{usuario_id}", response_model=List[DocumentoResponse])
def listar_de_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    # TI es global: ve el expediente de cualquiera. Los demás, solo el suyo.
    duenio = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    propio = current_user.id == usuario_id
    de_su_planta = (
        duenio is not None
        and current_user.rol == "admin"
    )
    if not (propio or de_su_planta):
        raise HTTPException(status_code=404, detail="Expediente no encontrado")

    filas = (
        db.query(DocumentoUsuario)
        .filter(DocumentoUsuario.usuario_id == usuario_id)
        .order_by(DocumentoUsuario.creado_en.desc())
        .all()
    )
    return [_con_vencimiento(d) for d in filas]


@router.post("", response_model=DocumentoResponse, status_code=status.HTTP_201_CREATED)
async def subir(
    usuario_id: int = Form(...),
    tipo: str = Form(...),
    titulo: str = Form(...),
    descripcion: Optional[str] = Form(None),
    resguardo_id: Optional[int] = Form(None),
    vigente_hasta: Optional[str] = Form(None),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Alta de un documento en el expediente. Solo TI."""
    if tipo not in TIPOS_DOCUMENTO:
        raise HTTPException(
            status_code=422,
            detail="Tipo inválido. Se acepta: " + ", ".join(TIPOS_DOCUMENTO),
        )

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    # 404 también si es de otra planta: un 403 confirmaba que el id existe.
    if not usuario or usuario.eliminado_en:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if resguardo_id is not None:
        resguardo = db.query(Resguardo).filter(Resguardo.id == resguardo_id).first()
        if not resguardo or resguardo.usuario_id != usuario_id:
            raise HTTPException(status_code=422, detail="El resguardo no corresponde a este usuario")

    mime = (archivo.content_type or "").split(";")[0].strip().lower()
    if mime not in TIPOS_PERMITIDOS:
        adivinado = mimetypes.guess_type(archivo.filename or "")[0]
        if adivinado in TIPOS_PERMITIDOS:
            mime = adivinado
        else:
            raise HTTPException(
                status_code=422,
                detail="Tipo de archivo no permitido. Se aceptan PDF e imágenes.",
            )

    limite = settings.DOCUMENTOS_MAX_MB * 1024 * 1024
    contenido = await archivo.read(limite + 1)
    if len(contenido) > limite:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"El archivo supera {settings.DOCUMENTOS_MAX_MB} MB.",
        )
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")
    if not contenido_coincide(contenido, mime):
        raise HTTPException(status_code=422, detail="El contenido del archivo no corresponde a su tipo.")

    vence = None
    if vigente_hasta:
        try:
            vence = datetime.fromisoformat(vigente_hasta.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=422, detail="Fecha de vigencia inválida.")

    nombre_guardado = f"{uuid.uuid4().hex}{TIPOS_PERMITIDOS[mime]}"
    (_carpeta() / nombre_guardado).write_bytes(contenido)

    documento = DocumentoUsuario(
        usuario_id=usuario_id,
        sitio_id=usuario.sitio_id,
        tipo=tipo,
        titulo=titulo[:200],
        descripcion=descripcion,
        resguardo_id=resguardo_id,
        nombre_original=(archivo.filename or "documento")[:255],
        nombre_guardado=nombre_guardado,
        tipo_mime=mime,
        tamano_bytes=len(contenido),
        vigente_hasta=vence,
        subido_por=admin.id,
        creado_en=datetime.utcnow(),
    )
    db.add(documento)
    db.commit()
    db.refresh(documento)

    logger.info("Documento agregado al expediente",
                extra={"usuario_id": usuario_id, "tipo": tipo, "documento_id": documento.id})
    return _con_vencimiento(documento)


@router.get("/{documento_id}")
def descargar(
    documento_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    documento = db.query(DocumentoUsuario).filter(DocumentoUsuario.id == documento_id).first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    # Un documento del expediente puede ser una identificacion escaneada o un
    # contrato: el rol de admin no alcanza si es de otra planta.
    propio = documento.usuario_id == current_user.id
    de_su_planta = current_user.rol == "admin"  # TI es global
    if not (propio or de_su_planta):
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    ruta = _carpeta() / documento.nombre_guardado
    if not ruta.exists():
        raise HTTPException(status_code=410, detail="El archivo ya no está disponible en el servidor.")

    return FileResponse(
        path=str(ruta),
        media_type=documento.tipo_mime,
        filename=documento.nombre_original,
        content_disposition_type="inline",
    )


@router.delete("/{documento_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar(
    documento_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Solo TI. Una persona no puede quitar de su expediente lo que firmó."""
    documento = db.query(DocumentoUsuario).filter(DocumentoUsuario.id == documento_id).first()
    # 404 también si es de otra planta: un 403 confirmaba que el id existe.
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # Primero la fila y después el archivo: si el commit fallara con el
    # archivo ya borrado, quedaría una fila que apunta a nada. Al revés, lo
    # peor es un archivo huérfano en disco.
    archivo = _carpeta() / documento.nombre_guardado
    db.delete(documento)
    db.commit()
    try:
        archivo.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("No se pudo borrar el archivo en disco",
                       extra={"documento_id": documento_id, "error": str(exc)})
    return None
