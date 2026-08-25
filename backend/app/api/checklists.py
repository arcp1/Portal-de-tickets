from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.db import get_db
from app.models import Checklist, Usuario
from app.schemas.checklist import ChecklistResponse, ChecklistCreate
from app.api.deps import get_current_user, get_current_admin

router = APIRouter(prefix="/checklists", tags=["Checklists"])

@router.get("", response_model=List[ChecklistResponse])
def list_checklists(
    categoria: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    query = db.query(Checklist)
    if categoria:
        query = query.filter(Checklist.categoria.ilike(categoria))
    return query.order_by(Checklist.orden.asc()).all()

@router.post("", response_model=ChecklistResponse, status_code=status.HTTP_201_CREATED)
def create_checklist(
    checklist_in: ChecklistCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    chk = Checklist(
        categoria=checklist_in.categoria,
        orden=checklist_in.orden,
        pregunta_key=checklist_in.pregunta_key,
        accion_si_no=checklist_in.accion_si_no,
        resuelve=checklist_in.resuelve
    )
    db.add(chk)
    db.commit()
    db.refresh(chk)
    return chk
