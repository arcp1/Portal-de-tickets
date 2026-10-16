"""Inicio de sesión con Microsoft: las rutas.

El cómo y el porqué están en app/services/sso_microsoft.py. Aquí solo va lo
de HTTP: la cookie del intento, las redirecciones, la bitácora y el canje
del código por la sesión del portal.

Lo que sale de aquí es la misma sesión que la del número de empleado: el
mismo token, la misma revocación, la misma vida máxima y **la misma puerta de
los Términos y Condiciones** (`exigir_terminos` en api/deps.py la aplica a
todo token, venga de donde venga).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.config import settings
from app.core.db import get_db
from app.core.limitador import frenar, freno_por_ip, limitador_sso_ip
from app.core.logging import logger
from app.core.security import create_access_token
from app.models import Usuario
from app.schemas.auth import TokenResponse
from app.services import sso_microsoft as sso
from app.services.auditoria_service import AuditoriaService

router = APIRouter(prefix="/auth/microsoft", tags=["Auth"])
admin_router = APIRouter(prefix="/admin/usuarios", tags=["Administración de usuarios"])

ENTRADA_MICROSOFT = "auth.microsoft"
RECHAZO_MICROSOFT = "auth.microsoft_rechazado"
MICROSOFT_VINCULADA = "usuario.microsoft_vinculada"
MICROSOFT_DESVINCULADA = "usuario.microsoft_desvinculada"

#: Lo que Microsoft contesta cuando la persona se echa para atrás.
_CANCELACIONES = {"access_denied", "consent_required", "interaction_required", "login_required"}


def _navegador(peticion: Request) -> str:
    return (peticion.headers.get("user-agent") or "")[:300]


def _volver_al_login(fragmento: str) -> RedirectResponse:
    """A la pantalla de entrada, con el resultado en el fragmento (`#…`), que
    no llega a ningún servidor ni a ningún registro de accesos. Y la cookie
    del intento se borra: sirve una vez."""
    respuesta = RedirectResponse(f"/login#{fragmento}", status_code=status.HTTP_303_SEE_OTHER)
    respuesta.delete_cookie(sso.COOKIE, path=sso.COOKIE_RUTA, secure=sso.cookie_segura(),
                            httponly=True, samesite="lax")
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@router.get("/config")
def configuracion():
    """Si el botón se enseña y a dónde lleva. Sin sesión: lo pide el login."""
    if not sso.activo():
        return {"activo": False, "url": None}
    return {"activo": True, "url": sso.url_de_entrada()}


@router.get("/login")
def iniciar(peticion: Request):
    """Manda el navegador a Microsoft con un intento nuevo."""
    motivo = sso.motivo_inactivo()
    if motivo:
        logger.warning("Inicio de sesión con Microsoft pedido sin configurar", extra={"motivo": motivo})
        return _volver_al_login("sso_error=no_configurado")
    estado, galleta = sso.nuevo_estado()
    respuesta = RedirectResponse(sso.url_de_autorizacion(estado), status_code=status.HTTP_302_FOUND)
    # Lax y no Strict: la vuelta desde Microsoft es una navegación de otro
    # sitio, y con Strict el navegador no mandaría la cookie.
    respuesta.set_cookie(sso.COOKIE, galleta, max_age=sso.VIDA_ESTADO_S, path=sso.COOKIE_RUTA,
                         secure=sso.cookie_segura(), httponly=True, samesite="lax")
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@router.get("/callback")
def volver_de_microsoft(
    peticion: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Microsoft devuelve aquí a la persona. Todo acaba en `/login#…`."""
    if not sso.activo():
        return _volver_al_login("sso_error=no_configurado")
    try:
        # Cada intento cuesta dos llamadas a Microsoft. La red de la planta
        # no lleva freno por IP: ver `freno_por_ip`.
        frenar(*freno_por_ip(limitador_sso_ip, peticion), motivo="Demasiados intentos con Microsoft")
    except HTTPException:
        return _volver_al_login("sso_error=demasiados")

    estado = sso.leer_estado(peticion.cookies.get(sso.COOKIE))
    if error:
        codigo = "cancelado" if error in _CANCELACIONES else "fallo"
        logger.info("Microsoft devolvió un error", extra={"error": error[:80], "codigo": codigo})
        return _volver_al_login(f"sso_error={codigo}")
    if estado is None or not sso.mismo_state(state, estado) or not code or len(code) > 4096:
        logger.warning("Vuelta de Microsoft sin un intento válido",
                       extra={"con_cookie": estado is not None})
        return _volver_al_login("sso_error=estado_invalido")

    identidad = None
    try:
        identidad = sso.identidad_desde_codigo(code, estado)
        usuario, vinculada = sso.resolver_cuenta(db, identidad)
    except sso.ErrorSSO as exc:
        db.rollback()
        logger.warning("Inicio de sesión con Microsoft rechazado",
                       extra={"codigo": exc.codigo, "motivo": exc.motivo})
        # A la bitácora lo que tiene a alguien detrás —un correo, una cuenta—;
        # un `state` caducado o Microsoft sin contestar van solo al registro.
        if identidad is not None:
            AuditoriaService.registrar(
                db, exc.usuario, RECHAZO_MICROSOFT, "usuario",
                exc.usuario.id if exc.usuario else None,
                {"motivo": exc.codigo, "correo": identidad.correos[0] if identidad.correos else None,
                 "correos": identidad.correos, "oid": identidad.oid, "nombre": identidad.nombre,
                 "navegador": _navegador(peticion)},
                peticion)
        return _volver_al_login(f"sso_error={exc.codigo}")

    usuario.ultimo_acceso = datetime.utcnow()
    db.commit()
    if vinculada:
        AuditoriaService.registrar(db, usuario, MICROSOFT_VINCULADA, "usuario", usuario.id,
                                   {"oid": identidad.oid, "correo": usuario.email}, peticion)
    AuditoriaService.registrar(db, usuario, ENTRADA_MICROSOFT, "usuario", usuario.id,
                               {"navegador": _navegador(peticion), "vinculada_ahora": vinculada},
                               peticion)
    logger.info("Inicio de sesión con Microsoft", extra={"usuario_id": usuario.id, "vinculada": vinculada})
    return _volver_al_login(f"sso={sso.emitir_canje(usuario)}")


class CanjeRequest(BaseModel):
    codigo: str = Field(min_length=20, max_length=1000)


@router.post("/canje", response_model=TokenResponse)
def canjear(datos: CanjeRequest, db: Session = Depends(get_db)):
    """El código de la redirección por la sesión del portal. Un solo uso y un
    minuto de vida. Se vuelve a mirar la cuenta: si en ese minuto la dieron de
    baja o cambió su contraseña, no entra."""
    resultado = sso.canjear(datos.codigo)
    usuario = db.get(Usuario, resultado[0]) if resultado else None
    if (usuario is None or not sso._puede_entrar(usuario)
            or int(usuario.version_token or 1) != resultado[1]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El inicio de sesión con Microsoft caducó o ya se usó. Vuelva a intentarlo.",
        )
    token = create_access_token(subject=usuario.id, version_token=usuario.version_token)
    return TokenResponse(access_token=token, token_type="bearer", user=usuario)


@admin_router.delete("/{usuario_id}/microsoft")
def desvincular(usuario_id: int, peticion: Request, db: Session = Depends(get_db),
                admin: Usuario = Depends(get_current_admin)):
    """Suelta la cuenta de Microsoft de una persona. La siguiente vez que
    entre con Microsoft se vuelve a vincular por correo, si coincide.

    Para cuando la cuenta de Microsoft de alguien cambia —una recontratación,
    un buzón nuevo— o se vinculó la que no era. No cierra sus sesiones.
    """
    from app.api.cuentas import _buscar_administrable

    usuario = _buscar_administrable(db, admin, usuario_id)
    anterior = usuario.microsoft_oid
    if not anterior:
        return {"microsoft_vinculada": False}
    usuario.microsoft_oid = None
    db.commit()
    AuditoriaService.registrar(db, admin, MICROSOFT_DESVINCULADA, "usuario", usuario.id,
                               {"oid": anterior}, peticion)
    return {"microsoft_vinculada": False}
