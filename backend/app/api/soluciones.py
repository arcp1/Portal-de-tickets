"""Soluciones generales: de muchos tickets, un procedimiento.

El flujo es de dos manos a propósito:

  1. **La máquina propone.** `/proponer` busca problemas que ya se repitieron y
     redacta un borrador por cada uno.
  2. **La persona publica.** El borrador no le contesta a nadie hasta que alguien
     de TI lo lee, lo corrige y lo firma con `/publicar`.

Esa separación no es burocracia. Un procedimiento equivocado en una planta manda
a alguien a desarmar un equipo sano, y la firma de una persona es lo único que
separa un procedimiento de una sugerencia.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import SolucionGeneral, Usuario
from app.schemas.comunes import FechaUTC
from app.services.auditoria_service import AuditoriaService
from app.services.soluciones_service import (
    ARCHIVADA, BORRADOR, PUBLICADA, SolucionesService,
)

router = APIRouter(prefix="/admin/soluciones", tags=["Soluciones generales"])

SOLUCION_PUBLICADA = "solucion_general.publicada"
SOLUCION_EDITADA = "solucion_general.editada"


class SolucionResponse(BaseModel):
    id: int
    titulo: str
    categoria: Optional[str] = None
    contenido: str
    descartado: Optional[str] = None
    estado: str
    tickets_origen: int
    redactada_por: Optional[str] = None
    revisada_por: Optional[int] = None
    veces_sugerida: int = 0
    veces_util: int = 0
    creado_en: Optional[FechaUTC] = None
    publicado_en: Optional[FechaUTC] = None

    class Config:
        from_attributes = True


class EditarSolucion(BaseModel):
    titulo: Optional[str] = Field(default=None, max_length=200)
    contenido: Optional[str] = None
    descartado: Optional[str] = None
    categoria: Optional[str] = None


class CrearSolucion(BaseModel):
    titulo: str = Field(min_length=5, max_length=200)
    contenido: str = Field(min_length=20)
    categoria: Optional[str] = None
    descartado: Optional[str] = None


def _buscar(db: Session, solucion_id: int, admin: Usuario) -> SolucionGeneral:
    solucion = db.query(SolucionGeneral).filter(
        SolucionGeneral.id == solucion_id,
        SolucionGeneral.sitio_id == admin.sitio_id,
    ).first()
    if not solucion:
        raise HTTPException(status_code=404, detail="Solución no encontrada")
    return solucion


@router.get("", response_model=List[SolucionResponse])
def listar(
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    consulta = db.query(SolucionGeneral).filter(SolucionGeneral.sitio_id == admin.sitio_id)
    if estado:
        consulta = consulta.filter(SolucionGeneral.estado == estado)
    return consulta.order_by(SolucionGeneral.tickets_origen.desc(),
                             SolucionGeneral.creado_en.desc()).all()


@router.get("/candidatos")
def candidatos(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Qué problemas ya se repitieron lo suficiente para escribir el procedimiento.

    No escribe nada ni llama a ningún modelo: solo cuenta. Sirve para saber si
    vale la pena pedir los borradores antes de gastar en ello.
    """
    grupos = SolucionesService.agrupar(db, admin.sitio_id)
    return {
        "total": len(grupos),
        "minimo_configurado": len(grupos) and grupos[-1]["ocurrencias"],
        "grupos": [
            {"titulo": g["titulo"], "categoria": g["categoria"],
             "ocurrencias": g["ocurrencias"]}
            for g in grupos
        ],
    }


@router.post("/proponer")
def proponer(
    limite: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Redacta borradores para los problemas más repetidos.

    `limite` acota cuántos se redactan de una vez, porque cada uno es una
    consulta al modelo de pago. Los borradores **no aparecen en las respuestas
    del asistente** hasta que alguien los publique.
    """
    grupos = SolucionesService.agrupar(db, admin.sitio_id)
    if not grupos:
        return {"redactadas": 0, "borradores": [],
                "detalle": "Todavía no hay ningún problema que se repita lo suficiente."}

    # No se vuelve a redactar lo que ya tiene borrador o publicación.
    existentes = {s.titulo for s in db.query(SolucionGeneral.titulo).filter(
        SolucionGeneral.sitio_id == admin.sitio_id).all()}

    borradores = []
    for grupo in grupos:
        if len(borradores) >= limite:
            break
        if grupo["titulo"][:200] in existentes:
            continue
        solucion = SolucionesService.redactar_borrador(db, grupo, admin.sitio_id)
        if solucion:
            borradores.append(SolucionResponse.model_validate(solucion))

    return {"redactadas": len(borradores), "borradores": borradores}


@router.post("", response_model=SolucionResponse, status_code=status.HTTP_201_CREATED)
def crear(
    datos: CrearSolucion,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Escribir el procedimiento a mano, sin esperar a que se repita nada."""
    solucion = SolucionGeneral(
        sitio_id=admin.sitio_id,
        titulo=datos.titulo.strip(),
        categoria=datos.categoria,
        contenido=datos.contenido.strip(),
        descartado=(datos.descartado or "").strip() or None,
        estado=BORRADOR,
        redactada_por="persona",
    )
    db.add(solucion)
    db.commit()
    db.refresh(solucion)
    return solucion


@router.patch("/{solucion_id}", response_model=SolucionResponse)
def editar(
    solucion_id: int,
    cambios: EditarSolucion,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    solucion = _buscar(db, solucion_id, admin)

    for campo in ("titulo", "contenido", "descartado", "categoria"):
        valor = getattr(cambios, campo)
        if valor is not None:
            setattr(solucion, campo, valor.strip() or None)
    # Si alguien la corrigió, deja de ser lo que escribió la máquina.
    if cambios.contenido is not None:
        solucion.redactada_por = "persona"
    db.commit()
    db.refresh(solucion)

    # El texto cambió: el embedding que tenía ya no corresponde.
    SolucionesService.reindexar(db, solucion)
    AuditoriaService.registrar(db, admin, SOLUCION_EDITADA, "solucion_general",
                               solucion.id, {"titulo": solucion.titulo}, peticion)
    return solucion


@router.post("/{solucion_id}/publicar", response_model=SolucionResponse)
def publicar(
    solucion_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """La firma una persona y entra en las respuestas del asistente."""
    solucion = _buscar(db, solucion_id, admin)
    if solucion.estado == PUBLICADA:
        return solucion

    solucion = SolucionesService.publicar(db, solucion, admin)
    AuditoriaService.registrar(db, admin, SOLUCION_PUBLICADA, "solucion_general",
                               solucion.id, {"titulo": solucion.titulo}, peticion)
    return solucion


@router.post("/{solucion_id}/archivar", response_model=SolucionResponse)
def archivar(
    solucion_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Deja de contestar, pero no se borra: puede haber tickets que la citen."""
    solucion = _buscar(db, solucion_id, admin)
    solucion.estado = ARCHIVADA
    solucion.embedding = None
    db.commit()
    db.refresh(solucion)
    return solucion
