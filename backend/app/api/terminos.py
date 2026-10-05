"""Términos y Condiciones de uso: leerlos y aceptarlos.

El texto vive en `recursos/terminos.md` (ver app/core/terminos.py). Mientras
la persona no acepte la versión vigente, el resto de la API le responde 403
`terminos_pendientes` (ver `exigir_terminos` en api/deps.py).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import terminos
from app.core.db import get_db
from app.core.logging import logger
from app.models import Auditoria, Usuario
from app.schemas.auth import SesionResponse
from app.services.auditoria_service import ip_de

router = APIRouter(tags=["Términos y Condiciones"])

TERMINOS_ACEPTADOS = "terminos.aceptados"


class AceptarTerminosRequest(BaseModel):
    # Lo que la pantalla mostró: la versión y la huella del texto. Tienen que
    # ser las vigentes; si no, la persona leyó otra cosa.
    version: str = Field(min_length=1, max_length=20)
    huella: str = Field(min_length=64, max_length=64)


@router.get("/terminos")
def leer_terminos():
    """El texto vigente, con su versión y su huella. **Sin sesión**: se enlaza
    desde la pantalla de entrada, y antes de aceptar también hay que poder
    leerlo."""
    return terminos.documento().a_dict()


@router.post("/auth/terminos", response_model=SesionResponse)
def aceptar_terminos(
    datos: AceptarTerminosRequest,
    peticion: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """La persona acepta la versión vigente. Devuelve su sesión ya al día.

    **La aceptación y su constancia van en la misma transacción.** La bitácora
    normal (`AuditoriaService.registrar`) se traga sus errores para no tumbar
    la operación; aquí es al revés: una aceptación sin constancia no prueba
    nada, así que si la fila de la bitácora no se puede escribir, tampoco se
    da por aceptado.

    Aceptar otra vez la misma versión no cambia nada ni deja otra fila: la
    fecha que vale es la de la primera vez.
    """
    vigente = terminos.documento()
    if datos.version != vigente.version or datos.huella != vigente.huella:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Los Términos y Condiciones cambiaron mientras los leía. "
                    "Vuelva a leerlos para poder aceptarlos."),
        )
    if current_user.terminos_vigentes:
        return current_user

    ahora = datetime.utcnow()
    current_user.terminos_version = vigente.version
    current_user.terminos_aceptados_en = ahora
    db.add(Auditoria(
        usuario_id=current_user.id,
        accion=TERMINOS_ACEPTADOS,
        entidad="usuario",
        entidad_id=current_user.id,
        detalle={
            "version": vigente.version,
            "vigente_desde": vigente.vigente_desde,
            "huella_sha256": vigente.huella,
            "navegador": (peticion.headers.get("user-agent") or "")[:200],
        },
        ip=ip_de(peticion),
        creado_en=ahora,
    ))
    db.commit()
    db.refresh(current_user)
    logger.info("Términos y Condiciones aceptados",
                extra={"usuario_id": current_user.id, "version": vigente.version})
    return current_user
