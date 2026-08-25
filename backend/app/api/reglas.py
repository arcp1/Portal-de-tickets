from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.db import get_db
from app.models import ReglaNegocio, Usuario
from app.schemas.checklist import ReglaResponse, ReglaCreate
from app.api.deps import get_current_user, get_current_admin

router = APIRouter(prefix="/reglas", tags=["Reglas de Negocio"])

@router.get("", response_model=List[ReglaResponse])
def list_reglas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    return db.query(ReglaNegocio).filter(ReglaNegocio.sitio_id == current_user.sitio_id).all()

@router.post("", response_model=ReglaResponse, status_code=status.HTTP_201_CREATED)
def create_regla(
    regla_in: ReglaCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    regla = ReglaNegocio(
        sitio_id=regla_in.sitio_id,
        categoria=regla_in.categoria,
        condicion=regla_in.condicion,
        accion=regla_in.accion,
        destinatario=regla_in.destinatario,
        activa=regla_in.activa
    )
    db.add(regla)
    db.commit()
    db.refresh(regla)
    return regla

@router.delete("/{regla_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_regla(
    regla_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    regla = db.query(ReglaNegocio).filter(ReglaNegocio.id == regla_id).first()
    if not regla:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(regla)
    db.commit()
