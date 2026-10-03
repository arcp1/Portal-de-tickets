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
    accion: Optional[str] = None,
    entidad: Optional[str] = None,
    dias: int = Query(30, ge=1, le=365),
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

    filas = consulta.order_by(Auditoria.creado_en.desc()).limit(limite).all()

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
