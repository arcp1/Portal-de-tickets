"""Alta, activación y administración de cuentas.

Dos superficies distintas:
  - `/auth/...` públicas o del propio usuario: activar, cambiar contraseña.
  - `/admin/usuarios/...` solo TI: dar de alta, listar, restablecer, desactivar.
"""

from datetime import datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, ValidationError, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core import plantas
from app.core.db import get_db
from app.core.limitador import (
    clave_de_cuenta, clave_de_red, es_publico, frenar, limitador_activacion,
    limitador_activacion_ip, limitador_login,
)
from app.core.logging import logger
from app.core.security import HashOcupado, create_access_token, respuesta_ocupado, turno_de_hash
from app.models import ESTADOS_TERMINADOS, Equipo, Resguardo, Sitio, Ticket, Usuario
from app.schemas.auth import TokenResponse, UserResponse
from app.schemas.comunes import FechaUTC, PlantaBreve
from app.services.auditoria_service import AuditoriaService, ip_de
from app.services.frases_service import sugerencias
from app.services.cuentas_service import (
    BLOQUEADA, NUMERO_EMPLEADO_INVALIDO, PENDIENTE, CuentasService, ErrorCuenta,
    _leer_fecha_simple,
    dominio_valido, dominios_permitidos, factores_secretos, normalizar_epp,
    numero_empleado_valido,
)


def _numero_de_gafete(valor):
    """Para `field_validator`: el número de empleado con el formato de un gafete."""
    if valor is not None and not numero_empleado_valido(valor.strip()):
        raise ValueError(NUMERO_EMPLEADO_INVALIDO)
    return valor

publico_router = APIRouter(prefix="/auth", tags=["Cuentas"])
admin_router = APIRouter(prefix="/admin/usuarios", tags=["Administración de usuarios"])

USUARIO_CREADO = "usuario.creado"
USUARIO_EDITADO = "usuario.editado"
USUARIO_DESACTIVADO = "usuario.desactivado"
USUARIO_ELIMINADO = "usuario.eliminado"
# Aparte de `usuario.editado`: es una sanción, y en la bitácora tiene que
# poder encontrarse sola —quién se la quitó a quién y cuándo—.
PRIORIDAD_ALTA_CAMBIADA = "usuario.prioridad_alta"
# También aparte: con el número de antes y el de después, que es lo que se
# necesita para entender por qué alguien "dejó de existir" con su número.
NUMERO_CORREGIDO = "usuario.numero_corregido"
USUARIO_RESTABLECIDO = "usuario.restablecido"
CODIGO_REGENERADO = "usuario.codigo_regenerado"
ACTIVACION_ASISTIDA = "usuario.activacion_asistida"

# Valor del filtro de estado que pide justo lo contrario que los demás: no un
# `estado_cuenta`, sino las cuentas sin acceso. Va en la misma lista porque
# para quien administra es una opción más del desplegable.
BAJA = "baja"

# La activación también se limita: el código es corto y adivinable a fuerza
# bruta si se deja intentar sin freno.

# Valida un correo suelto con la misma regla que `EmailStr` aplica en el alta.
_CORREO = TypeAdapter(EmailStr)


# ======================================================================
# Esquemas
# ======================================================================

class EstadoCuentaRequest(BaseModel):
    # Número de empleado o correo: la gente teclea lo que recuerda.
    identificador: str = Field(min_length=1, max_length=100)


class ActivarRequest(BaseModel):
    identificador: str = Field(min_length=1, max_length=100)
    password: str
    # Uno de los tres, según cómo se dio de alta la cuenta.
    codigo: Optional[str] = None
    nombre_completo: Optional[str] = None
    numero_epp: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    fecha_ingreso: Optional[str] = None


class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str


class CrearUsuarioRequest(BaseModel):
    # Los largos mínimos se miden sin los espacios de los extremos: un nombre
    # de cinco espacios pasaba y la cuenta nacía sin nombre.
    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: str = Field(min_length=3, max_length=100)
    numero_empleado: str = Field(min_length=1, max_length=20)
    _numero = field_validator("numero_empleado")(_numero_de_gafete)
    # Opcional: en planta mucha gente no tiene correo corporativo.
    email: Optional[EmailStr] = None
    # Valores cerrados: un rol inventado respondía 409 —como si chocara con
    # algo— y un idioma de más de cinco letras no cabía en su columna y daba 500.
    rol: Literal["usuario", "admin"] = "usuario"
    area: Optional[str] = Field(default=None, max_length=50)
    idioma_preferido: Literal["es", "en", "fr"] = "es"
    numero_epp: Optional[str] = Field(default=None, max_length=20)
    fecha_nacimiento: Optional[str] = None
    fecha_ingreso: Optional[str] = None
    # Las plantas en que trabaja (la primera, principal). Obligatoria para una
    # persona de planta cuando hay más de una; TI no lleva: es global.
    plantas: List[int] = Field(default_factory=list, max_length=50)


class EditarUsuarioRequest(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=100)
    numero_empleado: Optional[str] = Field(default=None, max_length=20)
    email: Optional[str] = Field(default=None, max_length=100)
    rol: Optional[str] = None

    _numero = field_validator("numero_empleado")(_numero_de_gafete)
    area: Optional[str] = Field(default=None, max_length=50)
    activo: Optional[bool] = None
    numero_epp: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    fecha_ingreso: Optional[str] = None
    # Revocarla es la sanción por pedir prioridad alta sin motivo.
    puede_usar_prioridad_alta: Optional[bool] = None
    # Las plantas de la persona, completas: sustituyen a las que tenía.
    plantas: Optional[List[int]] = Field(default=None, max_length=50)


class UsuarioAdminResponse(BaseModel):
    id: int
    sitio_id: Optional[int] = None
    plantas: List[PlantaBreve] = []
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
    numero_epp: Optional[str] = None
    datos_verificacion: List[str] = []
    puede_usar_prioridad_alta: bool = True
    # Resumen para el panel: qué tiene esta persona a su cargo.
    equipos_a_cargo: int = 0
    resguardos_pendientes: int = 0
    tickets_abiertos: int = 0

    model_config = ConfigDict(from_attributes=True)


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
def estado_cuenta(peticion: EstadoCuentaRequest):
    """Qué le toca hacer a quien llega con su correo: activar o iniciar sesión.

    Nunca revela si el correo existe. Un correo no dado de alta recibe la misma
    respuesta que uno activo, así la pantalla de entrada no sirve para averiguar
    quién trabaja aquí. El cuerpo se sigue validando —es lo que manda el paso 1
    del asistente—, pero ya no se consulta: ver `CuentasService.estado_publico`.
    """
    return CuentasService.estado_publico()


@publico_router.post("/activar", response_model=TokenResponse)
def activar(peticion: ActivarRequest, request: Request, db: Session = Depends(get_db)):
    """La persona usa su código una vez y define su propia contraseña.

    **Los datos de verificación solo valen desde dentro.** Número de EPP y fecha
    de nacimiento salen los dos de la misma lista de RH: contra un desconocido
    suman unos 27 bits, pero contra un compañero —o contra cualquiera que haya
    visto esa lista— valen cero. Ningún factor adicional arregla eso, porque
    todos vienen del mismo sitio.

    Lo que sí lo acota es dónde se puede intentar. Desde la red de la planta el
    riesgo es un compañero curioso: acotado, identificable y con bitácora. Desde
    internet es el mundo entero, y ahí ese nivel de prueba no es aceptable, así
    que por la vía pública se exige el código de un solo uso.
    """
    origen = clave_de_red(ip_de(request))
    publico = es_publico(request)
    usa_verificacion = peticion.codigo is None and any(
        (peticion.nombre_completo, peticion.numero_epp,
         peticion.fecha_nacimiento, peticion.fecha_ingreso)
    )

    if publico and usa_verificacion:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Desde fuera de la planta la activación necesita el código que "
                    "entrega el área de TI. Los datos personales solo sirven "
                    "conectado a la red de la planta."),
        )

    # Dos frenos, y el que de verdad importa es el segundo.
    #
    # Por IP frena a quien barre muchas cuentas desde un sitio. Por cuenta frena
    # lo contrario —muchos orígenes contra una sola persona—, que es el ataque
    # que el freno por IP no veía: bastaba con cambiar de red para seguir
    # probando cumpleaños contra el mismo número de empleado.
    cuenta = clave_de_cuenta(
        CuentasService.buscar_por_identificador(db, peticion.identificador),
        peticion.identificador, publico=publico)
    frenar((limitador_activacion_ip, f"ip:{origen}"), (limitador_activacion, cuenta))

    try:
        # Compara el código y calcula el hash de la nueva: dos bcrypt, en fila
        # con los demás (ver `turno_de_hash`).
        with turno_de_hash():
            usuario = CuentasService.activar(
                db,
                identificador=peticion.identificador,
                password=peticion.password,
                codigo=peticion.codigo,
                nombre_completo=peticion.nombre_completo,
                fecha_ingreso=peticion.fecha_ingreso,
                fecha_nacimiento=peticion.fecha_nacimiento,
                numero_epp=peticion.numero_epp,
            )
    except HashOcupado:
        limitador_activacion_ip.descontar(f"ip:{origen}")
        limitador_activacion.descontar(cuenta)
        raise respuesta_ocupado()
    except ErrorCuenta as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    limitador_activacion.limpiar(cuenta)
    limitador_activacion_ip.descontar(f"ip:{origen}")
    usuario.ultimo_acceso = datetime.utcnow()
    db.commit()

    # Se le entrega sesión de inmediato: acaba de demostrar quién es.
    return TokenResponse(
        access_token=create_access_token(subject=usuario.id,
                                         version_token=usuario.version_token),
        token_type="bearer",
        user=usuario,
    )


@publico_router.get("/requisitos-password")
def requisitos_password():
    """Las reglas y **tres frases ya listas**, antes de que la persona falle.

    Las sugerencias no son un adorno. La plantilla son sesenta personas, buena
    parte de ellas mayores, y pedirles que inventen una contrasena termina
    siempre igual: apuntada en un papel pegado al monitor. Tres palabras
    concretas se recuerdan a la primera y resisten diez millones de veces mas
    que el "Marzo2026" que sale cuando se exige "una mayuscula y un numero".

    Van generadas en el servidor y no en el navegador porque el generador
    aleatorio del navegador no siempre es criptografico, y esto acaba siendo la
    llave de la cuenta de alguien.
    """
    return {
        "longitud_minima": settings.PASSWORD_MIN_LONGITUD,
        "dominios_permitidos": dominios_permitidos(),
        "sugerencias": sugerencias(3),
    }


@publico_router.post("/cambiar-password", response_model=UserResponse)
def cambiar_password(
    peticion: CambiarPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    # **Con el mismo freno que el inicio de sesión.** Sin él, quien se quedara
    # con una sesión ajena —una computadora compartida que alguien no cerró—
    # podía probar contraseñas aquí sin límite: el login frenaba, esto no. Los
    # intentos cuentan contra el mismo cupo de la cuenta.
    cuenta = clave_de_cuenta(current_user, "", publico=es_publico(request))
    frenar((limitador_login, cuenta))
    try:
        with turno_de_hash():
            usuario = CuentasService.cambiar_password(
                db, current_user, peticion.password_actual, peticion.password_nueva
            )
    except HashOcupado:
        limitador_login.descontar(cuenta)
        raise respuesta_ocupado()
    except ErrorCuenta as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    limitador_login.limpiar(cuenta)
    return usuario


# ======================================================================
# Administración
# ======================================================================

#: Lo que puede ser una fecha de verdad para cada campo. Una fecha que se
#: entiende pero es imposible —nacer en 2099 o en 1700— se guardaba igual y
#: dejaba a la persona sin poder activarse con ella.
RANGO_DE_FECHAS = {
    "fecha_nacimiento": (datetime(1900, 1, 1), timedelta(days=0)),
    # Ingreso puede ir algo adelante: se da de alta a quien empieza el lunes.
    "fecha_ingreso": (datetime(1950, 1, 1), timedelta(days=366)),
}
#: Cómo se dice cada una en el mensaje: el nombre del campo no le dice nada a TI.
NOMBRE_DE_FECHA = {"fecha_nacimiento": "La fecha de nacimiento",
                   "fecha_ingreso": "La fecha de ingreso"}


def _fecha_valida(campo: str, valor: str):
    """La fecha de `campo` ya leída, o un 422 que dice cuál falló."""
    nombre = NOMBRE_DE_FECHA[campo]
    fecha = _leer_fecha_simple(valor)
    if not fecha:
        raise HTTPException(status_code=422,
                            detail=f"{nombre} no es una fecha válida. Use AAAA-MM-DD o DD/MM/AAAA.")
    desde, margen = RANGO_DE_FECHAS[campo]
    if not (desde <= fecha <= datetime.utcnow() + margen):
        raise HTTPException(status_code=422, detail=f"{nombre} está fuera de lo posible: revise el año.")
    return fecha


def _no_sobre_si_mismo(admin: Usuario, usuario: Usuario) -> None:
    """Restablecer y activar en mostrador anulan la contraseña y cierran la
    sesión de la cuenta. Sobre la propia, el admin se echaba a sí mismo con un
    código en pantalla como única llave: si cerraba el diálogo sin anotarlo, y
    era el único admin de la planta, nadie quedaba para darle otro."""
    if usuario.id == admin.id:
        raise HTTPException(
            status_code=422,
            detail="No puede restablecer su propia cuenta. Para cambiar su contraseña "
                   "use «Cambiar mi contraseña» en su perfil.")


def _buscar_administrable(db: Session, admin: Usuario, usuario_id: int) -> Usuario:
    """La persona sobre la que va a actuar el administrador, o 404.

    Un eliminado responde 404 igual que uno inexistente, y a propósito: si
    devolviera "esta cuenta fue eliminada" bastaría con recorrer ids para saber
    quién trabajó aquí. Para el portal, esa cuenta ya no está.

    **Bloquea la fila.** Todo lo que la usa cambia la cuenta, y dos clics
    seguidos llegaban juntos: cada petición leía el valor de antes de la otra,
    las dos creían cambiar algo y la bitácora anotaba cuatro veces "se retiró
    la prioridad alta" por un solo cambio. Con el bloqueo la segunda espera y
    lee lo que dejó la primera; `populate_existing` es para que de verdad lo
    relea aunque la sesión ya tuviera ese objeto —el propio admin—.
    """
    usuario = (db.query(Usuario).filter(Usuario.id == usuario_id)
               .with_for_update().populate_existing().first())
    if not usuario or usuario.eliminado_en:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario


def _conteos(db: Session, ids: List[int]) -> dict:
    """Lo que cada persona tiene a su cargo, para todas de una vez.

    Tres consultas agrupadas en total, no tres por persona. Antes el panel
    hacía un `COUNT` de equipos, uno de resguardos y uno de tickets por cada
    fila: con la plantilla entera, unas 1 800 consultas para abrir la lista.
    """
    if not ids:
        return {}

    def agrupado(columna, *filtros):
        return dict(db.query(columna, func.count()).filter(columna.in_(ids), *filtros)
                    .group_by(columna).all())

    equipos = agrupado(Equipo.asignado_a)
    resguardos = agrupado(Resguardo.usuario_id, Resguardo.estado == "pendiente_firma")
    tickets = agrupado(Ticket.usuario_id, Ticket.estado.notin_(ESTADOS_TERMINADOS))
    return {i: (equipos.get(i, 0), resguardos.get(i, 0), tickets.get(i, 0)) for i in ids}


def _resumen(db: Session, usuario: Usuario, conteos: Optional[dict] = None) -> dict:
    if conteos is None:
        conteos = _conteos(db, [usuario.id])
    equipos_a_cargo, resguardos_pendientes, tickets_abiertos = conteos[usuario.id]
    return {
        "id": usuario.id,
        "sitio_id": usuario.sitio_id,
        "plantas": usuario.plantas_resumen,
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
        # Para que TI vea de un vistazo quién no puede activarse solo y
        # quién quedó con un solo factor.
        # Solo los que son secretos: el nombre no cuenta (ver
        # `factores_secretos`). Es lo que hace util la columna "un solo factor".
        "datos_verificacion": factores_secretos(usuario),
        "numero_epp": usuario.numero_epp,
        "puede_usar_prioridad_alta": usuario.puede_usar_prioridad_alta,
        "equipos_a_cargo": equipos_a_cargo,
        "resguardos_pendientes": resguardos_pendientes,
        "tickets_abiertos": tickets_abiertos,
    }


@admin_router.get("", response_model=List[UsuarioAdminResponse])
def listar(
    buscar: Optional[str] = None,
    estado: Optional[str] = None,
    rol: Optional[str] = None,
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Panel de personas del sitio, con lo que cada una tiene a su cargo.

    **Quien está de baja no sale salvo que se pida.** Antes salían todos
    mezclados —el que trabaja aquí y el que se fue hace dos años, distinguidos
    por un distintivo rojo y medio punto de opacidad—, así que la lista crecía
    con gente a la que ya no se le puede hacer nada. Ahora el padrón enseña a
    quien tiene acceso, y las bajas están a un filtro de distancia
    (`estado=baja`), donde se les puede devolver el acceso.

    Los eliminados no salen nunca, con filtro o sin él: para el portal esa
    persona ya no existe. Lo que dejó hecho sigue en su sitio.
    """
    # TI es global: todas las plantas. Con `sitio_id`, las personas de esa
    # planta —en cualquiera de las suyas—.
    consulta = db.query(Usuario).filter(Usuario.eliminado_en.is_(None))
    if sitio_id is not None:
        consulta = consulta.filter(or_(Usuario.sitio_id == sitio_id,
                                       Usuario.plantas.any(Sitio.id == sitio_id)))

    if buscar:
        patron = f"%{buscar.strip()}%"
        consulta = consulta.filter(or_(
            Usuario.nombre.ilike(patron),
            Usuario.numero_empleado.ilike(patron),
            Usuario.numero_epp.ilike(patron),
            Usuario.email.ilike(patron),
            Usuario.area.ilike(patron),
        ))
    if estado == BAJA:
        consulta = consulta.filter(Usuario.activo.is_(False))
    else:
        # El estado de la cuenta —activa, pendiente— solo tiene sentido leerlo
        # de quien puede entrar: una cuenta "activa" a la que se le cortó el
        # acceso no está activa para nadie.
        consulta = consulta.filter(Usuario.activo.is_(True))
        if estado:
            consulta = consulta.filter(Usuario.estado_cuenta == estado)
    if rol:
        consulta = consulta.filter(Usuario.rol == rol)

    personas = consulta.order_by(Usuario.nombre).all()
    conteos = _conteos(db, [u.id for u in personas])
    return [_resumen(db, u, conteos) for u in personas]


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
    # Una fecha que no se entiende se rechaza, igual que al editar. Antes se
    # descartaba sin avisar: la cuenta nacía sin cumpleaños, la persona no
    # podía activarse con él y nadie sabía por qué.
    fechas = {}
    for campo in ("fecha_ingreso", "fecha_nacimiento"):
        valor = getattr(datos, campo)
        if valor:
            fechas[campo] = _fecha_valida(campo, valor)

    # Las plantas: TI no lleva; una persona de planta, al menos una. Si el
    # portal tiene una sola planta y no se dijo, es esa.
    plantas_pedidas = [] if datos.rol == "admin" else list(datos.plantas)
    if datos.rol != "admin" and not plantas_pedidas:
        plantas_pedidas = [plantas.planta_para(db, admin, None)]

    try:
        usuario, codigo = CuentasService.crear(
            db,
            nombre=datos.nombre,
            numero_empleado=datos.numero_empleado,
            email=datos.email,
            sitio_id=plantas_pedidas[0] if plantas_pedidas else None,
            plantas=plantas_pedidas,
            rol=datos.rol,
            area=datos.area,
            idioma=datos.idioma_preferido,
            fecha_ingreso=fechas.get("fecha_ingreso"),
            fecha_nacimiento=fechas.get("fecha_nacimiento"),
            numero_epp=datos.numero_epp,
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
            "«Activar mi cuenta», escribir su número de empleado y este código, "
            "y crear su propia contraseña. El código sirve una sola vez."
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
    usuario = _buscar_administrable(db, admin, usuario_id)
    numero_anterior = None

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
        # No se puede dejar el portal sin TI.
        if usuario.rol == "admin" and cambios.rol != "admin":
            otros = db.query(func.count(Usuario.id)).filter(
                Usuario.rol == "admin", Usuario.activo.is_(True),
                Usuario.eliminado_en.is_(None), Usuario.id != usuario.id,
            ).scalar()
            if not otros:
                raise HTTPException(status_code=422, detail="Es el único administrador activo.")
            # Deja de ser global: necesita al menos una planta.
            if not cambios.plantas:
                cambios.plantas = [plantas.planta_para(db, admin, None)]
        usuario.rol = cambios.rol
    # TI es global: al pasar a TI se le quitan las plantas. Para una persona de
    # planta, las que se manden sustituyen a las que tenía.
    if usuario.rol == "admin":
        plantas.asignar_plantas(db, usuario, [])
    elif cambios.plantas is not None:
        plantas.asignar_plantas(db, usuario, cambios.plantas)

    if cambios.numero_empleado is not None:
        nuevo = cambios.numero_empleado.strip()
        # Es con lo que la persona entra: vaciarlo la dejaba fuera, y el
        # segundo que se vaciara chocaba con el primero.
        if not nuevo:
            raise HTTPException(status_code=422, detail="El número de empleado es obligatorio.")
        # **Solo mientras la cuenta no se ha activado.** Una cuenta activa ya
        # entra con su número: cambiárselo la deja fuera sin aviso, con la
        # contraseña correcta en la mano. Antes de activarse, en cambio, el
        # número es solo un dato mal tecleado en el alta, y la única salida
        # era borrar la cuenta y crearla de nuevo. El código de activación que
        # ya se entregó sigue sirviendo con el número corregido.
        #
        # La excepción son los `TMP-` que dejó la migración: con ese número no
        # entra nadie, así que sustituirlo es justo lo que hace falta.
        if nuevo != usuario.numero_empleado:
            provisional = (usuario.numero_empleado or "").startswith("TMP-")
            if usuario.estado_cuenta != PENDIENTE and not provisional:
                raise HTTPException(
                    status_code=422,
                    detail=("El número de empleado solo se corrige mientras la cuenta no se "
                            "ha activado: ya entra con él, y cambiarlo la dejaría fuera."))
            if db.query(Usuario).filter(Usuario.numero_empleado == nuevo).first():
                raise HTTPException(status_code=409,
                                    detail=f"Ya existe una cuenta con el número {nuevo}.")
            numero_anterior = usuario.numero_empleado
        usuario.numero_empleado = nuevo
    if cambios.email is not None:
        correo = cambios.email.strip().lower() or None
        # Las mismas dos reglas que al dar de alta. Sin ellas, lo que el alta
        # rechazaba entraba por la edición.
        if correo:
            try:
                _CORREO.validate_python(correo)
            except ValidationError:
                raise HTTPException(status_code=422, detail="El correo no es válido.")
            if not dominio_valido(correo):
                permitidos = ", ".join("@" + d for d in dominios_permitidos())
                raise HTTPException(
                    status_code=422,
                    detail=f"El correo debe ser de un dominio de la empresa ({permitidos}).")
        if correo and correo != usuario.email and db.query(Usuario).filter(
            Usuario.email == correo).first():
            raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo.")
        usuario.email = correo
    if cambios.numero_epp is not None:
        usuario.numero_epp = normalizar_epp(cambios.numero_epp)
    for campo in ("fecha_nacimiento", "fecha_ingreso"):
        valor = getattr(cambios, campo)
        if valor is not None:
            setattr(usuario, campo, _fecha_valida(campo, valor) if valor.strip() else None)
    if cambios.nombre is not None:
        # El mismo mínimo que al dar de alta: la edición dejaba borrar el nombre.
        if len(cambios.nombre.strip()) < 3:
            raise HTTPException(status_code=422, detail="El nombre debe tener al menos 3 caracteres.")
        usuario.nombre = cambios.nombre.strip()
    if cambios.area is not None:
        usuario.area = cambios.area.strip() or None
    if cambios.activo is not None:
        usuario.activo = cambios.activo
    prioridad_cambio = (cambios.puede_usar_prioridad_alta is not None
                        and cambios.puede_usar_prioridad_alta != usuario.puede_usar_prioridad_alta)
    if prioridad_cambio:
        usuario.puede_usar_prioridad_alta = cambios.puede_usar_prioridad_alta

    db.commit()
    db.refresh(usuario)

    if prioridad_cambio:
        AuditoriaService.registrar(db, admin, PRIORIDAD_ALTA_CAMBIADA, "usuario", usuario.id,
                                   {"permitida": usuario.puede_usar_prioridad_alta}, peticion)

    if numero_anterior is not None:
        AuditoriaService.registrar(db, admin, NUMERO_CORREGIDO, "usuario", usuario.id,
                                   {"antes": numero_anterior, "despues": usuario.numero_empleado},
                                   peticion)

    # El permiso de prioridad y el número ya dejaron su propia entrada: lo
    # demás, en la común.
    resto = cambios.model_dump(exclude_none=True)
    resto.pop("puede_usar_prioridad_alta", None)
    if numero_anterior is not None:
        resto.pop("numero_empleado", None)
    if resto:
        accion = USUARIO_DESACTIVADO if cambios.activo is False else USUARIO_EDITADO
        AuditoriaService.registrar(db, admin, accion, "usuario", usuario.id, resto, peticion)
    return _resumen(db, usuario)


@admin_router.delete("/{usuario_id}", status_code=status.HTTP_200_OK)
def eliminar(
    usuario_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Saca a una persona del padrón para siempre, sin tocar lo que dejó hecho.

    **Es la operación fuerte, y la otra sigue existiendo.** Dar de baja
    (`PATCH` con `activo: false`) corta el acceso y se puede deshacer: la
    persona sigue en la lista, bajo el filtro de bajas, y se le puede devolver
    la entrada mañana. Esto no: la cuenta se vacía, la persona desaparece de
    todas las listas y no hay camino de vuelta.

    **Qué se conserva.** Todo lo que hizo: sus tickets, sus comentarios, los
    resguardos que firmó, los documentos que subió, los movimientos de
    inventario a su nombre. Y su nombre con ellos, que es lo que los hace
    legibles —un ticket reportado por nadie no le dice nada a quien lo abra
    dentro de un año—.

    **Qué se borra.** Lo que identifica y lo que deja entrar: contraseña,
    código de activación, correo, número de empleado, número de EPP y fechas
    personales. El número de empleado queda libre para darlo de alta otra vez.
    Las sesiones abiertas de esa cuenta caen en la siguiente petición.
    """
    usuario = _buscar_administrable(db, admin, usuario_id)

    # **La que de verdad protege al sitio es la primera.** Quien ejecuta esto
    # es un administrador activo, así que si no puede eliminarse a sí mismo,
    # siempre queda al menos uno. La segunda no es alcanzable hoy; se deja por
    # simetría con `editar`, que lleva la misma pareja de reglas, y para que
    # siga habiendo red si algún día se permite eliminar la propia cuenta.
    if usuario.id == admin.id:
        raise HTTPException(status_code=422, detail="No puede eliminar su propia cuenta.")
    if usuario.rol == "admin":
        otros = db.query(func.count(Usuario.id)).filter(
            Usuario.rol == "admin",
            Usuario.activo.is_(True),
            Usuario.eliminado_en.is_(None),
            Usuario.id != usuario.id,
        ).scalar()
        if not otros:
            raise HTTPException(status_code=422, detail="Es el único administrador activo.")

    # Se guarda antes de vaciarlo: es lo que hace útil la entrada de auditoría.
    huella = {
        "nombre": usuario.nombre,
        "numero_empleado": usuario.numero_empleado,
        "email": usuario.email,
        "rol": usuario.rol,
        "equipos_a_cargo": db.query(func.count(Equipo.id))
            .filter(Equipo.asignado_a == usuario.id).scalar() or 0,
    }

    usuario.eliminado_en = datetime.utcnow()
    usuario.activo = False
    usuario.estado_cuenta = BLOQUEADA
    # Lo que deja entrar.
    usuario.password_hash = None
    usuario.codigo_activacion_hash = None
    usuario.codigo_expira = None
    usuario.debe_cambiar_password = False
    # Lo que identifica. El número de empleado y el correo se sueltan para que
    # puedan volver a usarse en un alta nueva; el índice único los admite en
    # nulo tantas veces como haga falta.
    usuario.numero_empleado = None
    usuario.email = None
    usuario.numero_epp = None
    usuario.fecha_nacimiento = None
    usuario.fecha_ingreso = None
    # Sin datos de verificación no hay activación posible; se cierra igual esa
    # vía por si alguna quedara a medias.
    usuario.verificacion_bloqueada = True
    usuario.intentos_activacion = 0
    # Echa fuera cualquier sesión que esa cuenta tuviera abierta ahora mismo.
    usuario.version_token = (usuario.version_token or 1) + 1

    db.commit()

    AuditoriaService.registrar(db, admin, USUARIO_ELIMINADO, "usuario", usuario.id,
                               huella, peticion)
    logger.info("Cuenta eliminada del padrón",
                extra={"usuario_id": usuario.id, "por": admin.id})
    return {"eliminado": True, "nombre": usuario.nombre}


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
    usuario = _buscar_administrable(db, admin, usuario_id)
    _no_sobre_si_mismo(admin, usuario)

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


@admin_router.post("/{usuario_id}/activacion-asistida", response_model=CodigoResponse)
def activacion_asistida(
    usuario_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Abre una activación para hacerla con la persona enfrente.

    Es la salida para quien no recuerda ninguna fecha y para quien nunca va a
    recibir un papelito: TI comprueba el gafete, abre esto y le gira la pantalla
    para que **la persona teclee su propia contraseña**. TI sigue sin conocerla.

    El código que devuelve dura minutos y no está pensado para entregarse: se
    gasta ahí mismo, en la misma pantalla.
    """
    usuario = _buscar_administrable(db, admin, usuario_id)
    _no_sobre_si_mismo(admin, usuario)

    try:
        codigo, expira = CuentasService.abrir_activacion_asistida(db, usuario)
    except ErrorCuenta as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Queda en bitácora quién asistió a quién: es una acción con poder.
    AuditoriaService.registrar(db, admin, ACTIVACION_ASISTIDA, "usuario", usuario.id,
                               {"numero_empleado": usuario.numero_empleado}, peticion)

    return CodigoResponse(
        usuario_id=usuario.id, numero_empleado=usuario.numero_empleado,
        email=usuario.email, codigo=codigo, expira=expira,
        instrucciones=(
            f"Entregue el teclado a la persona para que escriba su contraseña. "
            f"Tiene {settings.ACTIVACION_ASISTIDA_MINUTOS} minutos."
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
    usuario = _buscar_administrable(db, admin, usuario_id)

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
