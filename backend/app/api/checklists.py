from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional

from app.core.db import get_db
from app.models import Checklist, Usuario
from app.schemas.checklist import ChecklistResponse, ChecklistCreate
from app.api.deps import get_current_user, get_current_admin
from app.services.ollama_client import CATEGORIAS_VALIDAS, normalizar_categoria

router = APIRouter(prefix="/checklists", tags=["Checklists"])

@router.get("", response_model=List[ChecklistResponse])
def list_checklists(
    categoria: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    # Solo los pasos activos: los que el admin dio de baja siguen en la tabla
    # por su historial, pero no se le muestran a nadie.
    query = (db.query(Checklist).options(selectinload(Checklist.imagenes))
             .filter(Checklist.activo.is_(True)))
    # Igualdad exacta y no `ilike`: en `ILIKE`, `%` es un comodín, así que
    # `?categoria=%` devolvía los pasos de **todas** las categorías. Un
    # checklist son los pasos de un problema concreto; enseñar los de otro es
    # peor que no enseñar ninguno. Una categoría que no existe no casa con
    # nada, que es lo correcto aquí.
    categoria_util = normalizar_categoria(categoria)
    if categoria:
        query = query.filter(Checklist.categoria == (categoria_util or ""))
    return query.order_by(Checklist.orden.asc()).all()

@router.post("", response_model=ChecklistResponse, status_code=status.HTTP_201_CREATED)
def create_checklist(
    checklist_in: ChecklistCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    # **Se valida al escribir, no solo al leer.**
    #
    # Los filtros de categoría pasaron a igualdad exacta, y eso solo es seguro
    # si lo guardado sale siempre del vocabulario. Sin esta comprobación, un
    # «Impresora» con mayúscula —o un «impresoras»— se guardaría sin queja y no
    # casaría nunca: la fila existe, nadie la ve, y no hay error que buscar.
    #
    # Es la misma guarda que ya tenían los pasos (`/admin/pasos`) y la
    # documentación de TI; aquí faltaba.
    categoria = normalizar_categoria(checklist_in.categoria)
    if categoria is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Categoría inválida. Debe ser una de: " + ", ".join(CATEGORIAS_VALIDAS),
        )

    chk = Checklist(
        categoria=categoria,
        orden=checklist_in.orden,
        pregunta_key=checklist_in.pregunta_key,
        accion_si_no=checklist_in.accion_si_no,
        resuelve=checklist_in.resuelve
    )
    db.add(chk)
    db.commit()
    db.refresh(chk)
    return chk
