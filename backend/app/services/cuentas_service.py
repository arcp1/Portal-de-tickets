"""Alta y activación de cuentas.

**Por qué este flujo y no otro.** Había dos opciones sobre la mesa:

  a) TI genera una contraseña aleatoria y se la reparte a la gente.
  b) Cualquiera con correo del dominio corporativo se da de alta solo.

Ninguna de las dos sirve. La (a) obliga a transmitir contraseñas por WhatsApp o
en papel —que es exactamente donde se filtran— y deja a TI conociendo la
contraseña de todos. La (b) deja entrar a cualquiera que adivine el patrón de
correos de la empresa.

Lo que se implementa es una tercera: **TI da de alta a la persona sin contraseña
y genera un código de activación de un solo uso.** La persona lo usa una vez
para crear su propia contraseña. Resultado:

  - TI nunca conoce la contraseña de nadie.
  - El código sirve una sola vez y caduca, así que si se filtra el daño es
    acotado y temporal.
  - Solo entra quien TI dio de alta.

El dominio corporativo se valida **al dar de alta**, no al entrar: evita que se
registre un correo personal por equivocación, sin convertir el dominio en la
única credencial.
"""

import re
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import get_password_hash, verify_password
from app.models import Usuario

PENDIENTE = "pendiente_activacion"
ACTIVA = "activa"
BLOQUEADA = "bloqueada"

# Sin I, O, 0, 1: se dictan por teléfono y se copian a mano de un papel.
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _leer_fecha_simple(texto: str):
    """Fecha tal como la teclearía alguien: 2021-03-15 o 15/03/2021."""
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime((texto or "").strip(), formato)
        except ValueError:
            continue
    return None


class ErrorCuenta(Exception):
    """Problema de negocio al operar una cuenta. El API lo traduce a 4xx."""


def generar_codigo() -> str:
    """Código de activación legible: 4+4 caracteres."""
    crudo = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(8))
    return f"{crudo[:4]}-{crudo[4:]}"


def normalizar_codigo(codigo: str) -> str:
    """Acepta el código como lo teclee la persona: con o sin guion, en minúsculas."""
    return re.sub(r"[^A-Z0-9]", "", (codigo or "").upper())


def dominios_permitidos() -> list:
    return [d.strip().lower().lstrip("@") for d in settings.DOMINIOS_PERMITIDOS.split(",") if d.strip()]


def dominio_valido(email: str) -> bool:
    """Vacío en la configuración = sin restricción."""
    permitidos = dominios_permitidos()
    if not permitidos:
        return True
    dominio = email.split("@")[-1].lower()
    return dominio in permitidos


def validar_password(password: str) -> Optional[str]:
    """Devuelve el motivo del rechazo, o None si la contraseña sirve.

    No se pide un zoo de símbolos: la longitud es lo que más aporta y lo que la
    gente sí cumple sin apuntarla en un papel pegado al monitor.
    """
    if len(password) < settings.PASSWORD_MIN_LONGITUD:
        return f"La contraseña debe tener al menos {settings.PASSWORD_MIN_LONGITUD} caracteres."
    if password.isdigit():
        return "La contraseña no puede ser solo números."
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", password):
        return "La contraseña debe incluir al menos una letra."
    if password.lower() in ("contraseña", "password", "12345678", "cgrmexico", "querataro"):
        return "Esa contraseña es demasiado común. Elija otra."
    return None


# Datos con los que una persona puede demostrar que es ella sin código, en
# orden de preferencia. El de EPP va primero porque es el que mejor cumple las
# dos condiciones: la persona se lo sabe de memoria (lo usa para sacar su
# equipo) y no está a la vista de sus compañeros.
FACTORES_VERIFICACION = ("numero_epp", "fecha_nacimiento", "fecha_ingreso")

# De los tres, solo dos los recuerda la persona sin pensarlo: el número de EPP
# porque lo usa para sacar su equipo, y su cumpleaños. La fecha de ingreso es la
# excepción, y por eso **nunca se exige como segundo factor**: pedirla sería
# repetir el error que dejó fuera a media planta. Solo se usa cuando es lo único
# que hay en el padrón.
FACTORES_MEMORABLES = ("numero_epp", "fecha_nacimiento")


def normalizar_epp(valor: Optional[str]) -> Optional[str]:
    """Deja el número de EPP comparable: solo dígitos, sin ceros de más.

    La misma persona lo escribe "0421", "421" o "04 21" según el día, y las
    tres deberían valer.
    """
    if valor is None:
        return None
    digitos = "".join(c for c in str(valor) if c.isdigit())
    return digitos.lstrip("0") or ("0" if digitos else None)


def _coincide(usuario: Usuario, factor: str, declarado: str) -> bool:
    """Si lo que la persona escribió corresponde a lo que hay en el padrón."""
    esperado = getattr(usuario, factor, None)
    if not esperado or not declarado:
        return False
    if factor == "numero_epp":
        return normalizar_epp(declarado) == normalizar_epp(esperado)
    fecha = _leer_fecha_simple(declarado)
    return bool(fecha and fecha.date() == esperado.date())


def factores_de(usuario: Usuario) -> list:
    """Qué datos de verificación tiene registrados esta cuenta."""
    return [f for f in FACTORES_VERIFICACION if getattr(usuario, f, None)]


def factores_a_pedir(usuario: Usuario) -> list:
    """Cuáles se le van a pedir a esta persona para activarse sin código.

    Los memorables que tenga, hasta el tope configurado. Si no tiene ninguno,
    queda la fecha de ingreso como último recurso —mejor un factor débil que
    mandar a todo el mundo al mostrador—.

    Cuando solo hay uno, se pide uno: no se puede exigir un dato que nadie
    capturó. Esas cuentas salen marcadas en el panel para que TI sepa cuáles
    quedaron con verificación de un solo factor y le pida a RH la lista de EPP.
    """
    memorables = [f for f in FACTORES_MEMORABLES if getattr(usuario, f, None)]
    if memorables:
        return memorables[:max(1, settings.VERIFICACION_FACTORES)]
    return ["fecha_ingreso"] if usuario.fecha_ingreso else []


class CuentasService:

    @staticmethod
    def crear(
        db: Session,
        nombre: str,
        numero_empleado: str,
        sitio_id: int,
        email: Optional[str] = None,
        rol: str = "usuario",
        area: Optional[str] = None,
        idioma: str = "es",
        fecha_ingreso=None,
        fecha_nacimiento=None,
        numero_epp=None,
    ) -> Tuple[Usuario, str]:
        """Da de alta a una persona. Devuelve (usuario, código en claro).

        El código en claro se devuelve **una sola vez**: no se guarda en ningún
        lado, solo su hash. Si TI lo pierde, se regenera.
        """
        numero_empleado = (numero_empleado or "").strip()
        email = (email or "").strip().lower() or None

        if not numero_empleado:
            raise ErrorCuenta("El número de empleado es obligatorio.")
        if db.query(Usuario).filter(Usuario.numero_empleado == numero_empleado).first():
            raise ErrorCuenta(f"Ya existe una cuenta con el número {numero_empleado}.")

        # El correo es opcional: en planta mucha gente no tiene uno corporativo.
        # Si lo traen, sí se valida el dominio.
        if email:
            if db.query(Usuario).filter(Usuario.email == email).first():
                raise ErrorCuenta("Ya existe una cuenta con ese correo.")
            if not dominio_valido(email):
                permitidos = ", ".join("@" + d for d in dominios_permitidos())
                raise ErrorCuenta(f"El correo debe ser de un dominio de la empresa ({permitidos}).")

        if rol not in ("admin", "usuario"):
            raise ErrorCuenta("Rol inválido.")

        codigo = generar_codigo()
        usuario = Usuario(
            nombre=nombre.strip(),
            numero_empleado=numero_empleado,
            email=email,
            numero_epp=normalizar_epp(numero_epp),
            fecha_nacimiento=fecha_nacimiento,
            fecha_ingreso=fecha_ingreso,
            sitio_id=sitio_id,
            rol=rol,
            area=(area or "").strip() or None,
            idioma_preferido=idioma,
            activo=True,
            password_hash=None,
            estado_cuenta=PENDIENTE,
            codigo_activacion_hash=get_password_hash(normalizar_codigo(codigo)),
            codigo_expira=datetime.utcnow() + timedelta(hours=settings.CODIGO_ACTIVACION_HORAS),
            creado_en=datetime.utcnow(),
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)

        logger.info("Cuenta creada, pendiente de activación",
                    extra={"numero_empleado": numero_empleado, "rol": rol})
        return usuario, codigo

    @staticmethod
    def regenerar_codigo(db: Session, usuario: Usuario) -> str:
        """Nuevo código: el anterior deja de servir."""
        if usuario.estado_cuenta == ACTIVA:
            raise ErrorCuenta("La cuenta ya está activa. Use el restablecimiento de contraseña.")

        codigo = generar_codigo()
        usuario.codigo_activacion_hash = get_password_hash(normalizar_codigo(codigo))
        usuario.codigo_expira = datetime.utcnow() + timedelta(hours=settings.CODIGO_ACTIVACION_HORAS)
        usuario.estado_cuenta = PENDIENTE
        db.commit()
        return codigo

    @staticmethod
    def buscar_por_identificador(db: Session, identificador: str) -> Optional[Usuario]:
        """Encuentra a alguien por su número de empleado o por su correo.

        El número es lo normal; el correo se acepta porque quien ya lo usaba
        antes de este cambio no tiene por qué aprenderse otra cosa.
        """
        valor = (identificador or "").strip()
        if not valor:
            return None
        usuario = db.query(Usuario).filter(Usuario.numero_empleado == valor).first()
        if usuario:
            return usuario
        return db.query(Usuario).filter(Usuario.email == valor.lower()).first()

    @staticmethod
    def activar(
        db: Session,
        identificador: str,
        password: str,
        codigo: Optional[str] = None,
        fecha_ingreso: Optional[str] = None,
        fecha_nacimiento: Optional[str] = None,
        numero_epp: Optional[str] = None,
    ) -> Usuario:
        """Activa la cuenta por código o por datos de verificación.

        El **código** es lo más seguro y sirve para altas individuales, y es lo
        que usa por debajo la activación asistida en mostrador.

        Los **datos de verificación** existen para la carga inicial de cientos
        de personas, donde repartir un papelito a cada quien no es viable. Se
        piden **dos** (los que la cuenta tenga, hasta `VERIFICACION_FACTORES`):
        con uno solo, quien viera la lista de RH podría activar cuentas ajenas.

        Cuáles dos, importa. El número de EPP y la fecha de nacimiento los sabe
        la persona de memoria; la fecha de ingreso casi nadie la recuerda, así
        que queda de última y solo para quien no tenga las otras.
        """
        usuario = CuentasService.buscar_por_identificador(db, identificador)

        # Mismo mensaje siempre: no se le confirma a nadie quién está dado de alta.
        generico = "Datos incorrectos. Solicite ayuda al área de TI."

        if not usuario or not usuario.activo or usuario.estado_cuenta != PENDIENTE:
            raise ErrorCuenta(generico)

        if codigo:
            if not usuario.codigo_activacion_hash:
                raise ErrorCuenta(generico)
            if usuario.codigo_expira and usuario.codigo_expira < datetime.utcnow():
                raise ErrorCuenta("El código venció. Solicite uno nuevo al área de TI.")
            if not verify_password(normalizar_codigo(codigo), usuario.codigo_activacion_hash):
                raise ErrorCuenta(generico)

        elif numero_epp or fecha_nacimiento or fecha_ingreso:
            declarados = {"numero_epp": numero_epp,
                          "fecha_nacimiento": fecha_nacimiento,
                          "fecha_ingreso": fecha_ingreso}
            exigidos = factores_a_pedir(usuario)
            if not exigidos:
                raise ErrorCuenta(generico)

            # La ventana acota el riesgo del modo sin código: pasada la fecha,
            # lo que quede sin activar necesita que TI entregue un código.
            if usuario.codigo_expira and usuario.codigo_expira < datetime.utcnow():
                raise ErrorCuenta(
                    "El periodo de activación terminó. Solicite un código al área de TI."
                )

            # Hay que acertarlos todos. Nada de crédito parcial: acertar uno de
            # dos no acerca a nadie a demostrar que es quien dice.
            if not all(_coincide(usuario, f, declarados.get(f)) for f in exigidos):
                raise ErrorCuenta(generico)

        else:
            raise ErrorCuenta("Faltan los datos de verificación.")

        problema = validar_password(password)
        if problema:
            raise ErrorCuenta(problema)

        usuario.password_hash = get_password_hash(password)
        usuario.estado_cuenta = ACTIVA
        # El código se quema: sirvió una vez y ya.
        usuario.codigo_activacion_hash = None
        usuario.codigo_expira = None
        usuario.debe_cambiar_password = False
        db.commit()
        db.refresh(usuario)

        logger.info("Cuenta activada",
                    extra={"numero_empleado": usuario.numero_empleado,
                           "via": "codigo" if codigo else "+".join(factores_a_pedir(usuario))})
        return usuario

    @staticmethod
    def abrir_activacion_asistida(db: Session, usuario: Usuario) -> Tuple[str, datetime]:
        """Código de vida corta para activar a alguien en mostrador.

        Es la salida para quien no recuerda ninguna fecha y para quien nunca va
        a recibir un papelito: TI lo tiene enfrente, comprueba el gafete y le
        gira la pantalla para que **la persona teclee su propia contraseña**.
        TI sigue sin conocerla.

        El código dura minutos, no días: no está pensado para entregarse, sino
        para gastarse ahí mismo.
        """
        if usuario.estado_cuenta == BLOQUEADA:
            raise ErrorCuenta("La cuenta está bloqueada.")
        if not usuario.activo:
            raise ErrorCuenta("La cuenta está desactivada.")

        codigo = generar_codigo()
        expira = datetime.utcnow() + timedelta(minutes=settings.ACTIVACION_ASISTIDA_MINUTOS)
        usuario.password_hash = None
        usuario.estado_cuenta = PENDIENTE
        usuario.codigo_activacion_hash = get_password_hash(normalizar_codigo(codigo))
        usuario.codigo_expira = expira
        usuario.debe_cambiar_password = False
        db.commit()

        logger.info("Activación asistida abierta",
                    extra={"numero_empleado": usuario.numero_empleado})
        return codigo, expira

    @staticmethod
    def cambiar_password(db: Session, usuario: Usuario, actual: str, nueva: str) -> Usuario:
        """Cambio hecho por la propia persona, verificando la contraseña vigente."""
        if not usuario.password_hash or not verify_password(actual, usuario.password_hash):
            raise ErrorCuenta("La contraseña actual no es correcta.")

        problema = validar_password(nueva)
        if problema:
            raise ErrorCuenta(problema)
        if verify_password(nueva, usuario.password_hash):
            raise ErrorCuenta("La contraseña nueva debe ser distinta de la actual.")

        usuario.password_hash = get_password_hash(nueva)
        usuario.debe_cambiar_password = False
        db.commit()
        db.refresh(usuario)
        return usuario

    @staticmethod
    def restablecer(db: Session, usuario: Usuario) -> str:
        """TI regresa la cuenta a 'pendiente' con un código nuevo.

        No se genera una contraseña temporal: eso volvería a poner a TI en el
        negocio de transmitir contraseñas. La persona vuelve a definir la suya.
        """
        codigo = generar_codigo()
        usuario.password_hash = None
        usuario.estado_cuenta = PENDIENTE
        usuario.codigo_activacion_hash = get_password_hash(normalizar_codigo(codigo))
        usuario.codigo_expira = datetime.utcnow() + timedelta(hours=settings.CODIGO_ACTIVACION_HORAS)
        usuario.debe_cambiar_password = False
        db.commit()

        logger.info("Contraseña restablecida por TI",
                    extra={"numero_empleado": usuario.numero_empleado})
        return codigo

    @staticmethod
    def estado_publico(db: Session, identificador: str) -> dict:
        """Qué le toca hacer a alguien que llega con su correo.

        Nunca revela si el correo existe: si no está dado de alta, responde lo
        mismo que si estuviera activo. Así la pantalla de entrada no sirve para
        averiguar quién trabaja aquí.
        """
        usuario = CuentasService.buscar_por_identificador(db, identificador)

        if usuario and usuario.activo and usuario.estado_cuenta == PENDIENTE:
            # Se le dice qué campos llenar, sin revelar su contenido: la
            # pantalla necesita saber qué preguntar, no qué contestar.
            pedir = factores_a_pedir(usuario)
            return {
                "accion": "activar",
                "acepta_codigo": usuario.codigo_activacion_hash is not None,
                "acepta_verificacion": bool(pedir),
                "datos_verificacion": pedir,
            }
        return {"accion": "iniciar_sesion", "acepta_codigo": False,
                "acepta_verificacion": False, "datos_verificacion": []}
