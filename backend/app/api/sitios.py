"""Las plantas.

Leerlas lo puede hacer cualquiera con sesión, pero cada quien ve las suyas: una
persona de planta solo las que tiene asignadas —es lo que elige al levantar un
ticket— y TI todas, porque su alcance es global (ver `core/plantas`).

Darlas de alta y editarlas es cosa de TI. **La clave no se cambia**: va dentro
de cada folio (`TICK-QRO-2026-0001`), y cambiarla dejaría los folios viejos con
una clave que ya no existe y reiniciaría la numeración de los nuevos.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.models import Equipo, Sitio, Ticket, Usuario, usuario_sitios
from app.services.auditoria_service import AuditoriaService

router = APIRouter(prefix="/sitios", tags=["Sitios"])

PLANTA_CREADA = "planta.creada"
PLANTA_EDITADA = "planta.editada"


class SitioResponse(BaseModel):
    id: int
    clave: str
    nombre: str
    pais: str
    activo: bool

    model_config = ConfigDict(from_attributes=True)


class SitioConConteos(SitioResponse):
    personas: int = 0
    equipos: int = 0
    tickets_abiertos: int = 0


class CrearSitio(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Letras y números, sin espacios: va dentro del folio.
    clave: str = Field(min_length=2, max_length=10, pattern=r"^[A-Za-z0-9]+$")
    nombre: str = Field(min_length=3, max_length=100)
    pais: str = Field(default="México", min_length=2, max_length=50)


class EditarSitio(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: Optional[str] = Field(default=None, min_length=3, max_length=100)
    pais: Optional[str] = Field(default=None, min_length=2, max_length=50)
    activo: Optional[bool] = None


@router.get("", response_model=List[SitioResponse])
def list_sitios(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Las plantas activas que alcanza quien pregunta.

    Requiere sesión: el listado de plantas de la empresa no es algo que deba
    poder leer cualquiera que alcance el puerto.
    """
    consulta = db.query(Sitio).filter(Sitio.activo.is_(True))
    alcance = current_user.plantas_ids
    if alcance is not None:
        consulta = consulta.filter(Sitio.id.in_(sorted(alcance) or [-1]))
    return consulta.order_by(Sitio.nombre).all()


@router.get("/admin", response_model=List[SitioConConteos])
def list_sitios_admin(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Todas, también las inactivas, con cuánto tiene cada una."""
    sitios = db.query(Sitio).order_by(Sitio.nombre).all()
    personas = dict(db.query(usuario_sitios.c.sitio_id, func.count())
                    .join(Usuario, Usuario.id == usuario_sitios.c.usuario_id)
                    .filter(Usuario.eliminado_en.is_(None))
                    .group_by(usuario_sitios.c.sitio_id).all())
    equipos = dict(db.query(Equipo.sitio_id, func.count(Equipo.id))
                   .group_by(Equipo.sitio_id).all())
    abiertos = dict(db.query(Ticket.sitio_id, func.count(Ticket.id))
                    .filter(Ticket.estado.in_(["abierto", "en_proceso", "espera_proveedor"]))
                    .group_by(Ticket.sitio_id).all())
    return [
        SitioConConteos(
            **SitioResponse.model_validate(s).model_dump(),
            personas=personas.get(s.id, 0),
            equipos=equipos.get(s.id, 0),
            tickets_abiertos=abiertos.get(s.id, 0),
        )
        for s in sitios
    ]


@router.post("", response_model=SitioResponse, status_code=status.HTTP_201_CREATED)
def crear_sitio(
    datos: CrearSitio,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    clave = datos.clave.upper()
    if db.query(Sitio.id).filter(func.upper(Sitio.clave) == clave).first():
        raise HTTPException(status_code=409, detail="Ya existe una planta con esa clave.")
    sitio = Sitio(clave=clave, nombre=datos.nombre, pais=datos.pais, activo=True)
    db.add(sitio)
    db.commit()
    db.refresh(sitio)
    AuditoriaService.registrar(db, admin, PLANTA_CREADA, "sitio", sitio.id,
                               {"clave": sitio.clave, "nombre": sitio.nombre}, peticion)
    return sitio


@router.patch("/{sitio_id}", response_model=SitioResponse)
def editar_sitio(
    sitio_id: int,
    cambios: EditarSitio,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    sitio = db.get(Sitio, sitio_id) if 0 < sitio_id < 2**31 else None
    if not sitio:
        raise HTTPException(status_code=404, detail="Planta no encontrada")

    if cambios.activo is False and sitio.activo:
        # Desactivar la última dejaría sin dónde levantar tickets a todos.
        otras = db.query(Sitio.id).filter(Sitio.activo.is_(True), Sitio.id != sitio.id).count()
        if not otras:
            raise HTTPException(status_code=409,
                                detail="No se puede desactivar la única planta activa.")

    datos = cambios.model_dump(exclude_unset=True, exclude_none=True)
    for campo, valor in datos.items():
        setattr(sitio, campo, valor)
    db.commit()
    db.refresh(sitio)
    if datos:
        AuditoriaService.registrar(db, admin, PLANTA_EDITADA, "sitio", sitio.id, datos, peticion)
    return sitio
