"""Resguardos de equipo y expediente de la persona.

Reglas de acceso:
  - Un usuario ve **lo suyo**: sus resguardos, sus equipos, sus documentos.
  - Solo TI emite, cancela y registra devoluciones.
  - **Solo el resguardante firma lo suyo.** Que un admin pueda firmar por otro
    anularía el valor del documento, así que ni siquiera se permite.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
from app.core.logging import logger
from app.models import (
    DocumentoUsuario, Equipo, MovimientoEquipo, Resguardo, Sitio, Ticket, Usuario,
)
from app.schemas.resguardo import (
    CancelacionRequest, DevolucionRequest, ExpedienteResponse, FirmaRequest,
    MovimientoResponse, ResguardoCreate, ResguardoResponse,
)
from app.services.auditoria_service import AuditoriaService, ip_de
from app.services.pdf_service import generar_carta_no_adeudo, generar_pdf_resguardo
from app.services.resguardo_service import (
    CONDICIONES_POR_DEFECTO, ESTADOS_ACTIVOS, PENDIENTE_FIRMA, ResguardoService,
)

router = APIRouter(prefix="/resguardos", tags=["Resguardos"])

RESGUARDO_EMITIDO = "resguardo.emitido"
RESGUARDO_FIRMADO = "resguardo.firmado"
RESGUARDO_DEVUELTO = "resguardo.devuelto"
RESGUARDO_CANCELADO = "resguardo.cancelado"


def _visible(resguardo: Resguardo, usuario: Usuario) -> bool:
    return usuario.rol == "admin" or resguardo.usuario_id == usuario.id


def _obtener(db: Session, resguardo_id: int, usuario: Usuario) -> Resguardo:
    resguardo = db.query(Resguardo).filter(Resguardo.id == resguardo_id).first()
    if not resguardo:
        raise HTTPException(status_code=404, detail="Resguardo no encontrado")
    if not _visible(resguardo, usuario):
        raise HTTPException(status_code=403, detail="No autorizado para este resguardo")
    return resguardo


@router.get("/condiciones")
def condiciones_estandar(admin: Usuario = Depends(get_current_admin)):
    """Texto que se copia en cada resguardo nuevo. Editable al emitir."""
    return {"condiciones": CONDICIONES_POR_DEFECTO}


@router.get("", response_model=List[ResguardoResponse])
def listar(
    estado: Optional[str] = None,
    usuario_id: Optional[int] = None,
    equipo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    consulta = db.query(Resguardo)

    if current_user.rol == "admin":
        consulta = consulta.filter(Resguardo.sitio_id == current_user.sitio_id)
        if usuario_id:
            consulta = consulta.filter(Resguardo.usuario_id == usuario_id)
    else:
        # Un usuario normal solo ve los suyos, ignore lo que pida.
        consulta = consulta.filter(Resguardo.usuario_id == current_user.id)

    if estado:
        consulta = consulta.filter(Resguardo.estado == estado)
    if equipo_id:
        consulta = consulta.filter(Resguardo.equipo_id == equipo_id)

    return consulta.order_by(Resguardo.creado_en.desc()).all()


@router.get("/mis-pendientes", response_model=List[ResguardoResponse])
def mis_pendientes(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lo que la persona tiene por firmar. Alimenta el aviso del portal."""
    return (
        db.query(Resguardo)
        .filter(Resguardo.usuario_id == current_user.id, Resguardo.estado == PENDIENTE_FIRMA)
        .order_by(Resguardo.creado_en.desc())
        .all()
    )


@router.post("", response_model=ResguardoResponse, status_code=status.HTTP_201_CREATED)
def emitir(
    datos: ResguardoCreate,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    equipo = db.query(Equipo).filter(Equipo.id == datos.equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    if equipo.sitio_id != admin.sitio_id:
        raise HTTPException(status_code=403, detail="El equipo pertenece a otro sitio")
    if equipo.estado == "baja":
        raise HTTPException(status_code=422, detail="No se puede resguardar un equipo dado de baja")

    usuario = db.query(Usuario).filter(Usuario.id == datos.usuario_id).first()
    if not usuario or not usuario.activo:
        raise HTTPException(status_code=404, detail="Usuario no encontrado o inactivo")

    try:
        resguardo = ResguardoService.emitir(
            db, equipo, usuario, admin,
            accesorios=datos.accesorios,
            observaciones=datos.observaciones,
            condiciones=datos.condiciones,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    AuditoriaService.registrar(db, admin, RESGUARDO_EMITIDO, "resguardo", resguardo.id,
                               {"folio": resguardo.folio, "equipo_id": equipo.id,
                                "usuario_id": usuario.id}, peticion)
    return resguardo


@router.get("/{resguardo_id}", response_model=ResguardoResponse)
def detalle(
    resguardo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return _obtener(db, resguardo_id, current_user)


@router.post("/{resguardo_id}/firmar", response_model=ResguardoResponse)
def firmar(
    resguardo_id: int,
    datos: FirmaRequest,
    peticion: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Aceptación del resguardante. Nadie puede firmar por otro."""
    resguardo = _obtener(db, resguardo_id, current_user)

    if not datos.acepto:
        raise HTTPException(status_code=422, detail="Debe marcar la aceptación de las condiciones.")

    try:
        resguardo = ResguardoService.firmar(
            db, resguardo, current_user, datos.nombre_completo, ip_de(peticion)
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    AuditoriaService.registrar(db, current_user, RESGUARDO_FIRMADO, "resguardo", resguardo.id,
                               {"folio": resguardo.folio, "nombre": resguardo.firma_nombre}, peticion)
    return resguardo


@router.post("/{resguardo_id}/devolver", response_model=ResguardoResponse)
def devolver(
    resguardo_id: int,
    datos: DevolucionRequest,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    resguardo = db.query(Resguardo).filter(Resguardo.id == resguardo_id).first()
    if not resguardo:
        raise HTTPException(status_code=404, detail="Resguardo no encontrado")

    try:
        resguardo = ResguardoService.devolver(
            db, resguardo, admin, datos.observaciones, datos.estado_equipo
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    AuditoriaService.registrar(db, admin, RESGUARDO_DEVUELTO, "resguardo", resguardo.id,
                               {"folio": resguardo.folio,
                                "estado_equipo": datos.estado_equipo}, peticion)
    return resguardo


@router.post("/{resguardo_id}/cancelar", response_model=ResguardoResponse)
def cancelar(
    resguardo_id: int,
    datos: CancelacionRequest,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    resguardo = db.query(Resguardo).filter(Resguardo.id == resguardo_id).first()
    if not resguardo:
        raise HTTPException(status_code=404, detail="Resguardo no encontrado")

    try:
        resguardo = ResguardoService.cancelar(db, resguardo, admin, datos.motivo)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    AuditoriaService.registrar(db, admin, RESGUARDO_CANCELADO, "resguardo", resguardo.id,
                               {"folio": resguardo.folio, "motivo": datos.motivo}, peticion)
    return resguardo


@router.get("/{resguardo_id}/pdf")
def descargar_pdf(
    resguardo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """PDF del resguardo, generado al vuelo.

    No se guarda en disco: siempre se puede reconstruir desde los datos, y
    archivarlo obligaría a mantener dos versiones del mismo documento.
    """
    resguardo = _obtener(db, resguardo_id, current_user)

    equipo = db.query(Equipo).filter(Equipo.id == resguardo.equipo_id).first()
    usuario = db.query(Usuario).filter(Usuario.id == resguardo.usuario_id).first()
    sitio = db.query(Sitio).filter(Sitio.id == resguardo.sitio_id).first()
    emisor = db.query(Usuario).filter(Usuario.id == resguardo.creado_por).first()

    try:
        pdf = generar_pdf_resguardo(resguardo, equipo, usuario, sitio, emisor)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo generar el PDF del resguardo",
                     extra={"resguardo_id": resguardo_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail="No se pudo generar el documento.")

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{resguardo.folio}.pdf"'},
    )


# ======================================================================
# Expediente de la persona
# ======================================================================

expediente_router = APIRouter(prefix="/expediente", tags=["Expediente"])


def _armar_expediente(db: Session, usuario: Usuario) -> dict:
    equipos = db.query(Equipo).filter(Equipo.asignado_a == usuario.id).all()
    resguardos = (
        db.query(Resguardo)
        .filter(Resguardo.usuario_id == usuario.id)
        .order_by(Resguardo.creado_en.desc())
        .all()
    )
    documentos = (
        db.query(DocumentoUsuario)
        .filter(DocumentoUsuario.usuario_id == usuario.id)
        .order_by(DocumentoUsuario.creado_en.desc())
        .all()
    )

    ahora = datetime.utcnow()
    docs = []
    vencidos = 0
    for d in documentos:
        vencido = bool(d.vigente_hasta and d.vigente_hasta < ahora)
        vencidos += 1 if vencido else 0
        docs.append({
            "id": d.id, "usuario_id": d.usuario_id, "tipo": d.tipo, "titulo": d.titulo,
            "descripcion": d.descripcion, "resguardo_id": d.resguardo_id,
            "nombre_original": d.nombre_original, "tipo_mime": d.tipo_mime,
            "tamano_bytes": d.tamano_bytes, "vigente_hasta": d.vigente_hasta,
            "creado_en": d.creado_en, "autor": d.autor, "vencido": vencido,
        })

    return {
        "usuario": usuario,
        "equipos_a_cargo": equipos,
        "resguardos": resguardos,
        "documentos": docs,
        "resguardos_pendientes_firma": sum(1 for r in resguardos if r.estado == PENDIENTE_FIRMA),
        "documentos_vencidos": vencidos,
    }


@expediente_router.get("/mio", response_model=ExpedienteResponse)
def mi_expediente(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lo que la persona tiene a su cargo y firmado."""
    return _armar_expediente(db, current_user)


@expediente_router.get("/{usuario_id}", response_model=ExpedienteResponse)
def expediente_de(
    usuario_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.sitio_id != admin.sitio_id:
        raise HTTPException(status_code=403, detail="El usuario pertenece a otro sitio")
    return _armar_expediente(db, usuario)


# ======================================================================
# Movimientos de un equipo
# ======================================================================

@router.get("/equipo/{equipo_id}/movimientos", response_model=List[MovimientoResponse])
def movimientos_del_equipo(
    equipo_id: int,
    limite: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Por dónde ha pasado un activo.

    `asignado_a` dice dónde está hoy; esto dice dónde estuvo. Es lo que se pide
    cuando un equipo se pierde y hay que reconstruir quién lo tuvo.
    """
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    if current_user.rol != "admin" and equipo.asignado_a != current_user.id:
        raise HTTPException(status_code=403, detail="No autorizado para este equipo")

    return (
        db.query(MovimientoEquipo)
        .filter(MovimientoEquipo.equipo_id == equipo_id)
        .order_by(MovimientoEquipo.creado_en.desc())
        .limit(limite)
        .all()
    )


@expediente_router.get("/{usuario_id}/no-adeudo")
def carta_no_adeudo(
    usuario_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Constancia de qué tiene la persona a su cargo, para darla de baja.

    Si no tiene nada pendiente, sale como carta de no adeudo. Si tiene equipos
    o resguardos abiertos, sale como **relación de pendientes**: emitir un "no
    adeudo" a alguien que no ha devuelto su laptop sería firmar algo falso.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.sitio_id != admin.sitio_id:
        raise HTTPException(status_code=403, detail="El usuario pertenece a otro sitio")

    equipos = db.query(Equipo).filter(Equipo.asignado_a == usuario.id).all()
    resguardos = (
        db.query(Resguardo)
        .filter(Resguardo.usuario_id == usuario.id, Resguardo.estado.in_(ESTADOS_ACTIVOS))
        .all()
    )
    tickets = (
        db.query(Ticket)
        .filter(Ticket.usuario_id == usuario.id,
                Ticket.estado.notin_(["resuelto", "cerrado"]))
        .all()
    )
    sitio = db.query(Sitio).filter(Sitio.id == usuario.sitio_id).first()

    try:
        pdf = generar_carta_no_adeudo(usuario, sitio, admin, resguardos, tickets, equipos)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo generar la carta de no adeudo",
                     extra={"usuario_id": usuario_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail="No se pudo generar el documento.")

    limpio = "sin-pendientes" if not (equipos or resguardos or tickets) else "con-pendientes"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="no-adeudo-{usuario.id}-{limpio}.pdf"'},
    )
