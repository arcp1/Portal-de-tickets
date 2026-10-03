from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.db import get_db
from app.models import ReglaNegocio, Usuario
from app.schemas.checklist import ReglaResponse, ReglaCreate
from app.api.deps import get_current_admin
from app.core import plantas
from app.services.ollama_client import CATEGORIAS_VALIDAS, normalizar_categoria

router = APIRouter(prefix="/reglas", tags=["Reglas de Negocio"])

@router.get("", response_model=List[ReglaResponse])
def list_reglas(
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    """Solo TI. Traen los correos de los proveedores y cómo se enruta cada
    falla: configuración interna, no algo que quien reporta necesite. La
    pantalla ya era solo de admin; el API la dejaba leer a cualquiera."""
    # TI es global: todas las plantas, o la que se pida.
    consulta = db.query(ReglaNegocio)
    if sitio_id:
        consulta = consulta.filter(ReglaNegocio.sitio_id == sitio_id)
    return consulta.order_by(ReglaNegocio.sitio_id, ReglaNegocio.id).all()

@router.post("", response_model=ReglaResponse, status_code=status.HTTP_201_CREATED)
def create_regla(
    regla_in: ReglaCreate,
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
    categoria = normalizar_categoria(regla_in.categoria)
    if categoria is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Categoría inválida. Debe ser una de: " + ", ".join(CATEGORIAS_VALIDAS),
        )

    regla = ReglaNegocio(
        # La planta pedida tiene que existir y estar activa; un número
        # inventado era una regla que no casaba con nada. TI es global y puede
        # escribirla en cualquiera (ver core/plantas).
        sitio_id=plantas.planta_para(db, admin, regla_in.sitio_id),
        categoria=categoria,
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
        # 404 y no 403: un 403 confirmaría que esa regla existe.
        raise HTTPException(status_code=404, detail="Regla no encontrada.")
    db.delete(regla)
    db.commit()
