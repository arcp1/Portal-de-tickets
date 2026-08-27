"""Alta, activación y administración de cuentas.

Dos superficies distintas:
  - `/auth/...` públicas o del propio usuario: activar, cambiar contraseña.
  - `/admin/usuarios/...` solo TI: dar de alta, listar, restablecer, desactivar.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.limitador import Limitador
from app.core.security import create_access_token
from app.models import Equipo, Resguardo, Ticket, Usuario
from app.schemas.auth import TokenResponse, UserResponse
from app.schemas.comunes import FechaUTC
from app.services.auditoria_service import AuditoriaService, ip_de
from app.services.cuentas_service import (
    ACTIVA, BLOQUEADA, PENDIENTE, CuentasService, ErrorCuenta,
    dominios_permitidos, validar_password,
)

publico_router = APIRouter(prefix="/auth", tags=["Cuentas"])
admin_router = APIRouter(prefix="/admin/usuarios", tags=["Administración de usuarios"])

USUARIO_CREADO = "usuario.creado"
USUARIO_EDITADO = "usuario.editado"
USUARIO_DESACTIVADO = "usuario.desactivado"
USUARIO_RESTABLECIDO = "usuario.restablecido"
CODIGO_REGENERADO = "usuario.codigo_regenerado"

# La activación también se limita: el código es corto y adivinable a fuerza
# bruta si se deja intentar sin freno.
limitador_activacion = Limitador(maximo=6, ventana_segundos=600)


# ======================================================================
# Esquemas
# ======================================================================

class EstadoCuentaRequest(BaseModel):
    # Número de empleado o correo: la gente teclea lo que recuerda.
    identificador: str = Field(min_length=1, max_length=100)


class ActivarRequest(BaseModel):
    identificador: str = Field(min_length=1, max_length=100)
    password: str
    # Uno de los dos, según cómo se dio de alta la cuenta.
    codigo: Optional[str] = None
    fecha_ingreso: Optional[str] = None


class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str


class CrearUsuarioRequest(BaseModel):
    nombre: str = Field(min_length=3, max_length=100)
    numero_empleado: str = Field(min_length=1, max_length=20)
    # Opcional: en planta mucha gente no tiene correo corporativo.
    email: Optional[EmailStr] = None
    rol: str = "usuario"
    area: Optional[str] = None
    idioma_preferido: str = "es"
    fecha_ingreso: Optional[str] = None


class EditarUsuarioRequest(BaseModel):
    nombre: Optional[str] = None
    numero_empleado: Optional[str] = None
    email: Optional[str] = None
    rol: Optional[str] = None
    area: Optional[str] = None
    activo: Optional[bool] = None


class UsuarioAdminResponse(BaseModel):
    id: int
    nombre: str
    numero_empleado: Optional[str] = None
    email: Optional[str] = None
    rol: str
    area: Optional[str] = None
    activo: bool
    estado_cuenta: str
    debe_cambiar_password: bool = False
    ultimo_acceso: Optional[FechaUTC] = None
    creado_en: Optional[FechaUTC] = None
    codigo_expira: Optional[FechaUTC] = None
    # Resumen para el panel: qué tiene esta persona a su cargo.
    equipos_a_cargo: int = 0
    resguardos_pendientes: int = 0
    tickets_abiertos: int = 0

    class Config:
        from_attributes = True


class CodigoResponse(BaseModel):
    """El código en claro viaja una sola vez, en la respuesta de su creación.

    No se guarda en ningún lado: la base solo tiene su hash. Si TI lo pierde,
    se regenera.
    """
    usuario_id: int
    numero_empleado: Optional[str] = None
    email: Optional[str] = None
    codigo: str
    expira: FechaUTC
    instrucciones: str


# ======================================================================
# Público / del propio usuario
# ======================================================================

@publico_router.post("/estado-cuenta")
def estado_cuenta(peticion: EstadoCuentaRequest, db: Session = Depends(get_db)):
    """Qué le toca hacer a quien llega con su correo: activar o iniciar sesión.

    Nunca revela si el correo existe. Un correo no dado de alta recibe la misma
    respuesta que uno activo, así la pantalla de entrada no sirve para averiguar
    quién trabaja aquí.
    """
    return CuentasService.estado_publico(db, peticion.identificador)


@publico_router.post("/activar", response_model=TokenResponse)
def activar(peticion: ActivarRequest, request: Request, db: Session = Depends(get_db)):
    """La persona usa su código una vez y define su propia contraseña."""
    origen = ip_de(request) or "desconocida"
    if not limitador_activacion.permitido(f"ip:{origen}"):
        espera = limitador_activacion.segundos_restantes(f"ip:{origen}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos. Espere {espera} segundos.",
            headers={"Retry-After": str(espera)},
        )

    try:
        usuario = CuentasService.activar(
            db,
            identificador=peticion.identificador,
            password=peticion.password,
            codigo=peticion.codigo,
            fecha_ingreso=peticion.fecha_ingreso,
        )
    except ErrorCuenta as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    limitador_activacion.limpiar(f"ip:{origen}")
    usuario.ultimo_acceso = datetime.utcnow()
    db.commit()

    # Se le entrega sesión de inmediato: acaba de demostrar quién es.
    return TokenResponse(
        access_token=create_access_token(subject=usuario.id),
        token_type="bearer",
        user=usuario,
    )


@publico_router.get("/requisitos-password")
def requisitos_password():
    """Para que el formulario diga las reglas antes de que la persona falle."""
    return {
        "longitud_minima": settings.PASSWORD_MIN_LONGITUD,
        "dominios_permitidos": dominios_permitidos(),
    }


@publico_router.post("/cambiar-password", response_model=UserResponse)
def cambiar_password(
    peticion: CambiarPasswordRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        return CuentasService.cambiar_password(
            db, current_user, peticion.password_actual, peticion.password_nueva
        )
    except ErrorCuenta as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ======================================================================
# Administración
# ======================================================================

def _resumen(db: Session, usuario: Usuario) -> dict:
    return {
        "id": usuario.id,
        "nombre": usuario.nombre,
        "numero_empleado": usuario.numero_empleado,
        "email": usuario.email,
        "rol": usuario.rol,
        "area": usuario.area,
        "activo": usuario.activo,
        "estado_cuenta": usuario.estado_cuenta,
        "debe_cambiar_password": usuario.debe_cambiar_password,
        "ultimo_acceso": usuario.ultimo_acceso,
        "creado_en": usuario.creado_en,
        "codigo_expira": usuario.codigo_expira,
        "equipos_a_cargo": db.query(func.count(Equipo.id))
            .filter(Equipo.asignado_a == usuario.id).scalar() or 0,
        "resguardos_pendientes": db.query(func.count(Resguardo.id))
            .filter(Resguardo.usuario_id == usuario.id,
                    Resguardo.estado == "pendiente_firma").scalar() or 0,
        "tickets_abiertos": db.query(func.count(Ticket.id))
            .filter(Ticket.usuario_id == usuario.id,
                    Ticket.estado.notin_(["resuelto", "cerrado"])).scalar() or 0,
    }


@admin_router.get("", response_model=List[UsuarioAdminResponse])
def listar(
    buscar: Optional[str] = None,
    estado: Optional[str] = None,
    rol: Optional[str] = None,
    incluir_inactivos: bool = Query(True),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Panel de personas del sitio, con lo que cada una tiene a su cargo."""
    consulta = db.query(Usuario).filter(Usuario.sitio_id == admin.sitio_id)

    if buscar:
        patron = f"%{buscar.strip()}%"
        consulta = consulta.filter(or_(
            Usuario.nombre.ilike(patron),
            Usuario.numero_empleado.ilike(patron),
            Usuario.email.ilike(patron),
            Usuario.area.ilike(patron),
        ))
    if estado:
        consulta = consulta.filter(Usuario.estado_cuenta == estado)
    if rol:
        consulta = consulta.filter(Usuario.rol == rol)
    if not incluir_inactivos:
        consulta = consulta.filter(Usuario.activo.is_(True))

    return [_resumen(db, u) for u in consulta.order_by(Usuario.nombre).all()]


@admin_router.post("", response_model=CodigoResponse, status_code=status.HTTP_201_CREATED)
def crear(
    datos: CrearUsuarioRequest,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Da de alta a una persona y devuelve su código de activación.

    **El código sale una sola vez, aquí.** No se guarda en claro; anótelo o
    entrégueselo a la persona en el momento. Si se pierde, se regenera.
    """
    try:
        from app.services.cuentas_service import _leer_fecha_simple
        usuario, codigo = CuentasService.crear(
            db,
            nombre=datos.nombre,
            numero_empleado=datos.numero_empleado,
            email=datos.email,
            sitio_id=admin.sitio_id,
            rol=datos.rol,
            area=datos.area,
            idioma=datos.idioma_preferido,
            fecha_ingreso=_leer_fecha_simple(datos.fecha_ingreso) if datos.fecha_ingreso else None,
        )
    except ErrorCuenta as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    AuditoriaService.registrar(db, admin, USUARIO_CREADO, "usuario", usuario.id,
                               {"numero_empleado": usuario.numero_empleado, "rol": usuario.rol}, peticion)

    return CodigoResponse(
        usuario_id=usuario.id,
        numero_empleado=usuario.numero_empleado,
        email=usuario.email,
        codigo=codigo,
        expira=usuario.codigo_expira,
        instrucciones=(
            "Entregue este código a la persona. En el portal debe elegir "
            "«Activar mi cuenta», escribir su correo y este código, y crear su "
            "propia contraseña. El código sirve una sola vez."
        ),
    )


@admin_router.patch("/{usuario_id}", response_model=UsuarioAdminResponse)
def editar(
    usuario_id: int,
    cambios: EditarUsuarioRequest,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario or usuario.sitio_id != admin.sitio_id:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Nadie se quita a sí mismo el rol de admin ni se desactiva: dejaría el
    # sitio sin quien administre.
    if usuario.id == admin.id:
        if cambios.rol is not None and cambios.rol != "admin":
            raise HTTPException(status_code=422, detail="No puede quitarse a sí mismo el rol de administrador.")
        if cambios.activo is False:
            raise HTTPException(status_code=422, detail="No puede desactivar su propia cuenta.")

    if cambios.rol is not None:
        if cambios.rol not in ("admin", "usuario"):
            raise HTTPException(status_code=422, detail="Rol inválido.")
        # No se puede dejar el sitio sin administradores.
        if usuario.rol == "admin" and cambios.rol != "admin":
            otros = db.query(func.count(Usuario.id)).filter(
                Usuario.sitio_id == admin.sitio_id, Usuario.rol == "admin",
                Usuario.activo.is_(True), Usuario.id != usuario.id,
            ).scalar()
            if not otros:
                raise HTTPException(status_code=422, detail="Es el único administrador activo del sitio.")
        usuario.rol = cambios.rol

    if cambios.numero_empleado is not None:
        nuevo = cambios.numero_empleado.strip()
        if nuevo != usuario.numero_empleado and db.query(Usuario).filter(
            Usuario.numero_empleado == nuevo).first():
            raise HTTPException(status_code=409, detail=f"Ya existe una cuenta con el número {nuevo}.")
        usuario.numero_empleado = nuevo
    if cambios.email is not None:
        correo = cambios.email.strip().lower() or None
        if correo and correo != usuario.email and db.query(Usuario).filter(
            Usuario.email == correo).first():
            raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo.")
        usuario.email = correo
    if cambios.nombre is not None:
        usuario.nombre = cambios.nombre.strip()
    if cambios.area is not None:
        usuario.area = cambios.area.strip() or None
    if cambios.activo is not None:
        usuario.activo = cambios.activo

    db.commit()
    db.refresh(usuario)

    accion = USUARIO_DESACTIVADO if cambios.activo is False else USUARIO_EDITADO
    AuditoriaService.registrar(db, admin, accion, "usuario", usuario.id,
                               cambios.model_dump(exclude_none=True), peticion)
    return _resumen(db, usuario)


@admin_router.post("/{usuario_id}/restablecer", response_model=CodigoResponse)
def restablecer(
    usuario_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Olvidó su contraseña: se le da un código nuevo y vuelve a definirla.

    No se genera una contraseña temporal a propósito: eso volvería a poner a TI
    en el negocio de transmitir contraseñas por WhatsApp.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario or usuario.sitio_id != admin.sitio_id:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    codigo = CuentasService.restablecer(db, usuario)
    AuditoriaService.registrar(db, admin, USUARIO_RESTABLECIDO, "usuario", usuario.id,
                               {"numero_empleado": usuario.numero_empleado}, peticion)

    return CodigoResponse(
        usuario_id=usuario.id, numero_empleado=usuario.numero_empleado,
        email=usuario.email, codigo=codigo,
        expira=usuario.codigo_expira,
        instrucciones=(
            "La contraseña anterior quedó anulada. Entregue este código a la "
            "persona para que defina una nueva."
        ),
    )


@admin_router.post("/{usuario_id}/regenerar-codigo", response_model=CodigoResponse)
def regenerar_codigo(
    usuario_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Se perdió el código antes de usarlo. El anterior deja de servir."""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario or usuario.sitio_id != admin.sitio_id:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    try:
        codigo = CuentasService.regenerar_codigo(db, usuario)
    except ErrorCuenta as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    AuditoriaService.registrar(db, admin, CODIGO_REGENERADO, "usuario", usuario.id,
                               {"numero_empleado": usuario.numero_empleado}, peticion)
    return CodigoResponse(
        usuario_id=usuario.id, numero_empleado=usuario.numero_empleado,
        email=usuario.email, codigo=codigo,
        expira=usuario.codigo_expira,
        instrucciones="Entregue este código a la persona. El anterior ya no sirve.",
    )
