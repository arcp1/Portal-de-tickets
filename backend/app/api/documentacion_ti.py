"""Documentación operativa interna del área de TI.

Procedimientos, direccionamiento IP, VLANs, contactos de proveedor: lo que hoy
vive en la cabeza de dos personas y en un Excel que nadie encuentra.

**Solo admin, sin excepción.** Es el único contenido del portal con esa
restricción absoluta: aquí hay información de infraestructura que un usuario
normal no necesita y que no conviene que circule.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, defer

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.core.logging import logger
from app.models import DocumentoTI, Usuario
from app.schemas.comunes import FechaUTC
from app.services.auditoria_service import AuditoriaService
from app.services.ollama_client import ollama

router = APIRouter(prefix="/documentacion", tags=["Documentación TI"])

CATEGORIAS = (
    "procedimiento",       # cómo se hace algo: dar de alta telefonía, configurar una impresora
    "red",                 # IPs, VLANs, segmentos, switches
    "inventario_logico",   # licencias, servidores, servicios
    "proveedor",           # contactos, contratos, números de póliza
    "credenciales",        # dónde están, no cuáles son
    "otro",
)

DOC_CREADO = "docti.creado"
DOC_EDITADO = "docti.editado"
DOC_BORRADO = "docti.borrado"


class DocumentoTICreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    categoria: str
    titulo: str = Field(min_length=4, max_length=200)
    contenido: str = Field(min_length=10, max_length=50000)
    etiquetas: Optional[str] = Field(default=None, max_length=300)
    sensible: bool = False


class DocumentoTIUpdate(BaseModel):
    # Los mismos mínimos que al crear: editar dejaba el título o el contenido
    # en blanco, y el documento quedaba en la lista sin nada que abrir.
    model_config = ConfigDict(str_strip_whitespace=True)

    categoria: Optional[str] = None
    titulo: Optional[str] = Field(default=None, min_length=4, max_length=200)
    contenido: Optional[str] = Field(default=None, min_length=10, max_length=50000)
    etiquetas: Optional[str] = Field(default=None, max_length=300)
    sensible: Optional[bool] = None


class DocumentoTIResponse(BaseModel):
    id: int
    categoria: str
    titulo: str
    contenido: str
    etiquetas: Optional[str] = None
    sensible: bool
    creado_en: Optional[FechaUTC] = None
    actualizado_en: Optional[FechaUTC] = None
    autor_nombre: Optional[str] = None
    editor_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BusquedaRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    texto: str = Field(min_length=3, max_length=2000)


def _validar_categoria(categoria: str):
    if categoria not in CATEGORIAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Categoría inválida. Se acepta: " + ", ".join(CATEGORIAS),
        )


def _salida(d: DocumentoTI) -> dict:
    return {
        "id": d.id, "categoria": d.categoria, "titulo": d.titulo,
        "contenido": d.contenido, "etiquetas": d.etiquetas, "sensible": d.sensible,
        "creado_en": d.creado_en, "actualizado_en": d.actualizado_en,
        "autor_nombre": d.autor.nombre if d.autor else None,
        "editor_nombre": d.editor.nombre if d.editor else None,
    }


def _texto_indexable(categoria: str, titulo: str, contenido: str, etiquetas: Optional[str]) -> str:
    partes = [categoria, titulo, contenido, etiquetas]
    return "\n".join(p.strip() for p in partes if p and p.strip())


@router.get("/categorias")
def categorias(admin: Usuario = Depends(get_current_admin)):
    return {"categorias": list(CATEGORIAS)}


@router.get("", response_model=List[DocumentoTIResponse])
def listar(
    categoria: Optional[str] = None,
    buscar: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Listado con búsqueda por texto. Para búsqueda por significado, `/buscar`."""
    # El listado no enseña el vector: no se trae (768 números por fila).
    consulta = (db.query(DocumentoTI).options(defer(DocumentoTI.embedding)))

    if categoria:
        consulta = consulta.filter(DocumentoTI.categoria == categoria)
    if buscar:
        patron = f"%{buscar.strip()}%"
        consulta = consulta.filter(or_(
            DocumentoTI.titulo.ilike(patron),
            DocumentoTI.contenido.ilike(patron),
            DocumentoTI.etiquetas.ilike(patron),
        ))

    filas = consulta.order_by(DocumentoTI.categoria, DocumentoTI.titulo).all()
    return [_salida(d) for d in filas]


@router.post("/buscar", response_model=List[DocumentoTIResponse])
def buscar_por_significado(
    peticion: BusquedaRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Búsqueda por similitud: encuentra el procedimiento aunque no recuerde
    cómo se titulaba.

    Si Ollama no está, cae a búsqueda por texto en vez de devolver vacío: la
    documentación tiene que poder consultarse siempre.
    """
    vector = ollama.generar_embedding(peticion.texto, tarea="consulta")

    if vector is None:
        patron = f"%{peticion.texto.strip()}%"
        filas = (
            db.query(DocumentoTI)
            .filter(or_(DocumentoTI.titulo.ilike(patron),
                        DocumentoTI.contenido.ilike(patron),
                        DocumentoTI.etiquetas.ilike(patron)))
            .limit(10).all()
        )
        return [_salida(d) for d in filas]

    try:
        filas = (
            db.query(DocumentoTI)
            .filter(DocumentoTI.embedding.isnot(None))
            .order_by(DocumentoTI.embedding.cosine_distance(vector))
            .limit(8).all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Fallo la búsqueda por similitud en documentación",
                     extra={"error": str(exc)})
        return []

    return [_salida(d) for d in filas]


@router.post("", response_model=DocumentoTIResponse, status_code=status.HTTP_201_CREATED)
def crear(
    datos: DocumentoTICreate,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    _validar_categoria(datos.categoria)

    documento = DocumentoTI(
        sitio_id=admin.sitio_id,
        categoria=datos.categoria,
        titulo=datos.titulo.strip(),
        contenido=datos.contenido.strip(),
        etiquetas=(datos.etiquetas or "").strip() or None,
        sensible=datos.sensible,
        embedding=ollama.generar_embedding(
            _texto_indexable(datos.categoria, datos.titulo, datos.contenido, datos.etiquetas),
            tarea="documento",
        ),
        creado_por=admin.id,
        creado_en=datetime.utcnow(),
    )
    db.add(documento)
    db.commit()
    db.refresh(documento)

    AuditoriaService.registrar(db, admin, DOC_CREADO, "documentacion", documento.id,
                               {"titulo": documento.titulo}, peticion)
    return _salida(documento)


@router.patch("/{documento_id}", response_model=DocumentoTIResponse)
def editar(
    documento_id: int,
    cambios: DocumentoTIUpdate,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    documento = db.query(DocumentoTI).filter(
        DocumentoTI.id == documento_id,
    ).first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    if cambios.categoria is not None:
        _validar_categoria(cambios.categoria)

    cambio_texto = False
    for campo in ("categoria", "titulo", "contenido", "etiquetas", "sensible"):
        valor = getattr(cambios, campo)
        if valor is not None:
            setattr(documento, campo, valor.strip() if isinstance(valor, str) else valor)
            if campo in ("categoria", "titulo", "contenido", "etiquetas"):
                cambio_texto = True

    if cambio_texto:
        nuevo = ollama.generar_embedding(
            _texto_indexable(documento.categoria, documento.titulo,
                             documento.contenido, documento.etiquetas),
            tarea="documento",
        )
        if nuevo is not None:
            documento.embedding = nuevo
        else:
            logger.warning("Documento editado sin poder regenerar su vector",
                           extra={"documento_id": documento.id})

    documento.actualizado_por = admin.id
    documento.actualizado_en = datetime.utcnow()
    db.commit()
    db.refresh(documento)

    AuditoriaService.registrar(db, admin, DOC_EDITADO, "documentacion", documento.id,
                               {"titulo": documento.titulo}, peticion)
    return _salida(documento)


@router.delete("/{documento_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar(
    documento_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    documento = db.query(DocumentoTI).filter(
        DocumentoTI.id == documento_id,
    ).first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    AuditoriaService.registrar(db, admin, DOC_BORRADO, "documentacion", documento.id,
                               {"titulo": documento.titulo}, peticion)
    db.delete(documento)
    db.commit()
    return None
