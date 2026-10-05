"""Consulta de la bitácora. Solo admin.

Es de solo lectura a propósito: no hay endpoint para editar ni borrar. Una
bitácora que se puede modificar no sirve de bitácora.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import Auditoria, Usuario

router = APIRouter(prefix="/auditoria", tags=["Auditoría"])


@router.get("")
def listar(
    accion: Optional[str] = Query(None, max_length=50),
    entidad: Optional[str] = Query(None, max_length=50),
    usuario_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    dias: int = Query(30, ge=1, le=365),
    # La página siguiente: el id de la última fila que ya se tiene. Mientras
    # se lee entran registros nuevos, y con páginas numeradas la segunda
    # repetiría las últimas de la primera.
    antes_de: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    desde = datetime.utcnow() - timedelta(days=dias)

    consulta = (
        db.query(Auditoria, Usuario)
        .join(Usuario, Auditoria.usuario_id == Usuario.id)
        # TI es global: ve la bitácora de todas las plantas.
        .filter(Auditoria.creado_en >= desde)
    )
    if accion:
        consulta = consulta.filter(Auditoria.accion == accion)
    if entidad:
        consulta = consulta.filter(Auditoria.entidad == entidad)
    if usuario_id:
        consulta = consulta.filter(Auditoria.usuario_id == usuario_id)
    if antes_de:
        consulta = consulta.filter(Auditoria.id < antes_de)

    filas = consulta.order_by(Auditoria.id.desc()).limit(limite).all()

    return [
        {
            "id": a.id,
            "accion": a.accion,
            "entidad": a.entidad,
            "entidad_id": a.entidad_id,
            "detalle": a.detalle,
            "ip": a.ip,
            "creado_en": a.creado_en.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if a.creado_en else None,
            "usuario": {"id": u.id, "nombre": u.nombre, "email": u.email},
        }
        for a, u in filas
    ]


@router.get("/opciones")
def opciones(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Qué acciones, entidades y personas aparecen en la bitácora: lo que
    llenan los filtros de la pantalla. Se lee de la tabla y no de una lista
    escrita aquí, para que una acción nueva aparezca sola el día que alguien
    la registre por primera vez."""
    acciones = [a for (a,) in db.query(Auditoria.accion).distinct().order_by(Auditoria.accion)]
    entidades = [e for (e,) in db.query(Auditoria.entidad).distinct().order_by(Auditoria.entidad)]
    personas = (db.query(Usuario.id, Usuario.nombre)
                .filter(Usuario.id.in_(db.query(Auditoria.usuario_id).distinct()))
                .order_by(Usuario.nombre).all())
    return {
        "acciones": acciones,
        "entidades": entidades,
        "personas": [{"id": i, "nombre": n} for i, n in personas],
    }
