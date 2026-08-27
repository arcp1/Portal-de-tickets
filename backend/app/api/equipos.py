from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.core.db import get_db
from app.models import Equipo, Usuario, Ticket
from app.schemas.equipo import EquipoCreate, EquipoUpdate, EquipoResponse
from app.api.deps import get_current_user, get_current_admin

router = APIRouter(prefix="/equipos", tags=["Equipos"])

@router.get("", response_model=List[EquipoResponse])
def list_equipos(
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    query = db.query(Equipo).filter(Equipo.sitio_id == current_user.sitio_id)
    if tipo:
        query = query.filter(Equipo.tipo == tipo)
    if estado:
        query = query.filter(Equipo.estado == estado)
    return query.all()

@router.post("", response_model=EquipoResponse, status_code=status.HTTP_201_CREATED)
def create_equipo(
    equipo_in: EquipoCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    equipo = Equipo(
        sitio_id=equipo_in.sitio_id,
        tipo=equipo_in.tipo,
        categoria=equipo_in.categoria,
        marca=equipo_in.marca,
        modelo=equipo_in.modelo,
        numero_serie=equipo_in.numero_serie,
        ubicacion=equipo_in.ubicacion,
        estado=equipo_in.estado,
        asignado_a=equipo_in.asignado_a,
        fecha_asignacion=datetime.utcnow() if equipo_in.asignado_a else None,
        notas=equipo_in.notas
    )
    db.add(equipo)
    db.commit()
    db.refresh(equipo)
    return equipo

@router.get("/{equipo_id}", response_model=EquipoResponse)
def get_equipo(
    equipo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo not found")
    return equipo

@router.patch("/{equipo_id}", response_model=EquipoResponse)
def update_equipo(
    equipo_id: int,
    equipo_in: EquipoUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo not found")

    for field, value in equipo_in.dict(exclude_unset=True).items():
        if field == "asignado_a" and value != equipo.asignado_a:
            equipo.fecha_asignacion = datetime.utcnow() if value else None
        setattr(equipo, field, value)

    db.commit()
    db.refresh(equipo)
    return equipo


@router.get("/{equipo_id}/historial")
def historial_del_equipo(
    equipo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Todos los tickets de este equipo.

    Es lo que revela cuál impresora conviene cambiar en vez de seguir
    reparándola: si un solo equipo concentra veinte incidencias, el problema
    no es de soporte, es de compras.
    """
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    tickets = (
        db.query(Ticket)
        .filter(Ticket.equipo_id == equipo_id)
        .order_by(Ticket.creado_en.desc())
        .all()
    )

    resueltos = [t for t in tickets if t.tiempo_resolucion is not None]
    return {
        "equipo_id": equipo_id,
        "total_tickets": len(tickets),
        "abiertos": sum(1 for t in tickets if t.estado not in ("resuelto", "cerrado")),
        "tiempo_promedio_min": (
            round(sum(t.tiempo_resolucion for t in resueltos) / len(resueltos), 1)
            if resueltos else None
        ),
        "tickets": [
            {
                "id": t.id,
                "folio": t.folio,
                "categoria": t.categoria,
                "estado": t.estado,
                "prioridad": t.prioridad,
                "creado_en": t.creado_en.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if t.creado_en else None,
                "solucion": t.solucion,
            }
            for t in tickets
        ],
    }
