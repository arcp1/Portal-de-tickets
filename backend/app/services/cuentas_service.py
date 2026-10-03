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
import unicodedata
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import HASH_SENUELO, get_password_hash, verify_password
from app.models import Usuario

PENDIENTE = "pendiente_activacion"
ACTIVA = "activa"
BLOQUEADA = "bloqueada"

# Sin I, O, 0, 1: se dictan por teléfono y se copian a mano de un papel.
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


#: Lo que trae un gafete: letras y dígitos, con los separadores de siempre.
#: Se aceptaba cualquier cosa —"🔥🔥" se dio de alta— y con eso la persona no
#: podía activarse ni entrar: el número de empleado es lo que teclea en ambas
#: pantallas, y nadie teclea emojis desde un gafete.
NUMERO_EMPLEADO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,18}[A-Za-z0-9])?")
NUMERO_EMPLEADO_INVALIDO = ("solo admite letras y dígitos, con guion, punto, diagonal o "
                            "guion bajo entre ellos")


def numero_empleado_valido(numero: str) -> bool:
    return bool(NUMERO_EMPLEADO.fullmatch(numero or ""))


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


# Lo que la gente teclea cuando le piden "una contraseña" y no quiere pensarla.
# Se comparan en minusculas y sin espacios.
PASSWORDS_PROHIBIDAS = {
    "contraseña", "contrasena", "password", "12345678", "123456789", "1234567890",
    "cgrmexico", "cgrdemexico", "querataro", "queretaro", "portaltickets",
    "sistemas", "administrador", "bienvenido", "temporal1", "cambiar123",
}


def validar_password(password: str, usuario: Optional[Usuario] = None) -> Optional[str]:
    """Devuelve el motivo del rechazo, o None si la contraseña sirve.

    No se pide un zoo de símbolos: la longitud es lo que más aporta y lo que la
    gente sí cumple sin apuntarla en un papel pegado al monitor.

    Con `usuario` se rechaza además lo que salga de sus propios datos. Importa
    más de lo que parece: quien acaba de activarse tecleando su número de EPP y
    su fecha de nacimiento tiende a poner justo eso como contraseña, y son
    precisamente los dos datos que están en la lista de RH. Sería dejar la
    puerta con la misma llave con la que se abrió.
    """
    if len(password) < settings.PASSWORD_MIN_LONGITUD:
        return f"La contraseña debe tener al menos {settings.PASSWORD_MIN_LONGITUD} caracteres."
    if password.isdigit():
        return "La contraseña no puede ser solo números."
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", password):
        return "La contraseña debe incluir al menos una letra."
    if password.lower().strip() in PASSWORDS_PROHIBIDAS:
        return "Esa contraseña es demasiado común. Elija otra."

    if usuario is not None:
        motivo = _huele_a_datos_propios(password, usuario)
        if motivo:
            return motivo
    return None


def _sin_acentos(texto: str) -> str:
    """Minusculas y sin tildes, para comparar nombres como se teclean.

    Aqui casi todos los apellidos llevan acento —Perez, Martinez, Rios— y nadie
    lo escribe al elegir una contrasena. Comparando en crudo, "Rios2026" pasaba
    tan campante para alguien apellidado "Rios": la regla del nombre no servia
    para media planta.
    """
    limpio = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


def _huele_a_datos_propios(password: str, usuario: Usuario) -> Optional[str]:
    """Si la contraseña contiene datos que cualquiera puede consultar de esa persona."""
    plano = _sin_acentos(password)
    solo_digitos = "".join(c for c in password if c.isdigit())

    # Numero de empleado y de EPP. Se exige un minimo de tres digitos para no
    # rechazar por casualidad a quien tenga un "12" suelto en su contrasena.
    for valor, etiqueta in ((usuario.numero_empleado, "su número de empleado"),
                            (usuario.numero_epp, "su número de EPP")):
        digitos = "".join(c for c in str(valor or "") if c.isdigit())
        if len(digitos) >= 3 and digitos in solo_digitos:
            return f"La contraseña no puede contener {etiqueta}. Es un dato que otros conocen."

    # Fechas propias, en los formatos que la gente escribe.
    for fecha, etiqueta in ((usuario.fecha_nacimiento, "su fecha de nacimiento"),
                            (usuario.fecha_ingreso, "su fecha de ingreso")):
        if not fecha:
            continue
        piezas = {
            f"{fecha.day:02d}{fecha.month:02d}{fecha.year}",
            f"{fecha.day:02d}{fecha.month:02d}{fecha.year % 100:02d}",
            f"{fecha.year}{fecha.month:02d}{fecha.day:02d}",
        }
        if any(p in solo_digitos for p in piezas):
            return f"La contraseña no puede contener {etiqueta}. Es un dato que otros conocen."

    # El propio nombre, pero solo cuando la contraseña **se apoya** en el.
    #
    # Rechazar cualquier contraseña que contenga un trozo del nombre de cuatro
    # letras es demasiado: media planta se apellida Cruz, Luna, Mora, Rosa o
    # Leon, que ademas son palabras corrientes, y "ClaveNuevaSegura" acabaria
    # rechazada por llevar dentro un apellido por casualidad. Lo que se quiere
    # evitar es "Perez2026", no que la palabra aparezca de pasada.
    #
    # El corte es proporcional y **suma todas las partes**: si entre nombre y
    # apellidos cubren la mitad o mas de lo tecleado, la contraseña es el nombre
    # con adornos. Mirar cada parte por separado dejaba pasar "JuanPerez12",
    # donde ninguna llega a la mitad pero las dos juntas son casi todo.
    partes = [p for p in _sin_acentos(usuario.nombre).split() if len(p) >= 4]

    # Dos señales, y hacen falta las dos porque cada una sola se queda corta.
    #
    #   1. Cuanto del total cubre el nombre. Corta "JuanPerez12", donde ninguna
    #      parte llega a la mitad pero juntas son casi todo.
    #
    #   2. Si empieza por el nombre. Es la que atrapa el patron de verdad
    #      frecuente —apellido + año, "Rios2026xx"— que por proporcion se
    #      escapaba: el apellido era solo el 40% y pasaba. Quien construye su
    #      contrasena sobre su nombre lo pone delante; a quien le sale de
    #      casualidad, en medio.
    cubierto = sum(len(p) for p in partes if p in plano)
    if cubierto * 2 >= len(plano):
        return "La contraseña no puede ser básicamente su nombre."
    if any(plano.startswith(p) for p in partes):
        return "La contraseña no puede empezar con su nombre o su apellido."
    return None


# Datos con los que una persona puede demostrar que es ella sin código, en
# orden de preferencia. El de EPP va primero porque es el que mejor cumple las
# dos condiciones: la persona se lo sabe de memoria (lo usa para sacar su
# equipo) y no está a la vista de sus compañeros.
FACTORES_VERIFICACION = ("nombre_completo", "numero_epp", "fecha_nacimiento", "fecha_ingreso")

# De los tres, solo dos los recuerda la persona sin pensarlo: el número de EPP
# porque lo usa para sacar su equipo, y su cumpleaños. La fecha de ingreso es la
# excepción, y por eso **nunca se exige como segundo factor**: pedirla sería
# repetir el error que dejó fuera a media planta. Solo se usa cuando es lo único
# que hay en el padrón.
FACTORES_MEMORABLES = ("nombre_completo", "numero_epp", "fecha_nacimiento")

#: Lo que la pantalla de activacion pide **siempre**, exista la cuenta o no.
#: Es una lista fija a proposito: si dependiera de la cuenta, su longitud ya
#: seria un dato sobre esa persona.
CAMPOS_QUE_SE_PIDEN = ("nombre_completo", "numero_epp", "fecha_nacimiento")


def normalizar_epp(valor: Optional[str]) -> Optional[str]:
    """Deja el número de EPP comparable: solo dígitos, sin ceros de más.

    La misma persona lo escribe "0421", "421" o "04 21" según el día, y las
    tres deberían valer.
    """
    if valor is None:
        return None
    digitos = "".join(c for c in str(valor) if c.isdigit())
    return digitos.lstrip("0") or ("0" if digitos else None)


def _coincide_nombre(esperado: str, declarado: str) -> bool:
    """El nombre, comparado como lo teclea la gente.

    Tolerante a proposito: sin acentos, sin importar mayusculas y sin exigir el
    orden ni los apellidos completos. Quien esta registrada como "María López
    Herrera" puede escribir "maria lopez" y pasa. Pedir la cadena exacta habria
    dejado fuera a media planta por una tilde.

    Se exigen al menos dos palabras: con una sola, "Maria" acertaria en decenas
    de cuentas y el dato dejaria de aportar nada.

    **No es un secreto y no se cuenta como tal.** El nombre esta en el gafete.
    Lo que aporta es que quien solo tenga una lista de numeros no pueda avanzar,
    y que la persona confirme que activa la cuenta correcta y no la del vecino.
    """
    partes_declaradas = [p for p in _sin_acentos(declarado).split() if len(p) >= 2]
    if len(partes_declaradas) < 2:
        return False
    registradas = set(_sin_acentos(esperado).split())
    return all(p in registradas for p in partes_declaradas)


def _coincide(usuario: Usuario, factor: str, declarado: str) -> bool:
    """Si lo que la persona escribió corresponde a lo que hay en el padrón."""
    esperado = getattr(usuario, "nombre" if factor == "nombre_completo" else factor, None)
    if not esperado or not declarado:
        return False
    if factor == "nombre_completo":
        return _coincide_nombre(esperado, declarado)
    if factor == "numero_epp":
        return normalizar_epp(declarado) == normalizar_epp(esperado)
    fecha = _leer_fecha_simple(declarado)
    return bool(fecha and fecha.date() == esperado.date())


def _tiene(usuario: Usuario, factor: str):
    """El valor registrado de un factor. El nombre vive en otra columna."""
    return getattr(usuario, "nombre" if factor == "nombre_completo" else factor, None)


def factores_de(usuario: Usuario) -> list:
    """Qué datos de verificación tiene registrados esta cuenta."""
    return [f for f in FACTORES_VERIFICACION if _tiene(usuario, f)]


def factores_secretos(usuario: Usuario) -> list:
    """Los factores de esta cuenta que de verdad protegen algo.

    El nombre completo queda fuera **a proposito**: va en el gafete, asi que no
    es un secreto. Se pide para que quien solo tenga una lista de numeros no
    pueda avanzar y para que la persona confirme que activa su cuenta y no la
    del vecino, pero no fortalece nada.

    Contarlo como factor seria enganarse en el sitio que peor duele: el panel de
    TI existe justo para senalar quien quedo con verificacion debil, y sumarle a
    todos un factor que todos tienen esconderia exactamente esas cuentas.
    """
    return [f for f in factores_a_pedir(usuario) if f != "nombre_completo"]


def factores_a_pedir(usuario: Usuario) -> list:
    """Cuáles se le van a pedir a esta persona para activarse sin código.

    Los memorables que tenga, hasta el tope configurado. Si no tiene ninguno,
    queda la fecha de ingreso como último recurso —mejor un factor débil que
    mandar a todo el mundo al mostrador—.

    Cuando solo hay uno, se pide uno: no se puede exigir un dato que nadie
    capturó. Esas cuentas salen marcadas en el panel para que TI sepa cuáles
    quedaron con verificación de un solo factor y le pida a RH la lista de EPP.
    """
    # **La decision se toma sobre los secretos, nunca sobre el nombre.**
    #
    # El nombre lo tiene todo el mundo, asi que si contara para "esta cuenta
    # tiene con que verificarse" la respuesta seria siempre que si. Una cuenta
    # sin EPP ni fecha registrados habria quedado activable con numero de
    # empleado y nombre: los dos van en el gafete. Eso no es verificar a nadie,
    # es regalar la cuenta a quien pase por el pasillo.
    secretos = [f for f in FACTORES_MEMORABLES
                if f != "nombre_completo" and _tiene(usuario, f)]

    if not secretos and usuario.fecha_ingreso:
        # Ultimo recurso: la de ingreso casi nadie la recuerda, pero es mejor
        # que mandar a esa persona al mostrador.
        secretos = ["fecha_ingreso"]

    if not secretos:
        # Sin nada que comprobar, esta via no existe para esta cuenta.
        return []

    elegidos = secretos[:max(1, settings.VERIFICACION_FACTORES)]
    # El nombre se suma encima sin ocupar una plaza: no fortalece, pero obliga a
    # tener algo mas que una lista de numeros y evita activar la cuenta del
    # vecino por teclear mal el numero.
    if _tiene(usuario, "nombre_completo"):
        elegidos = ["nombre_completo"] + elegidos
    return elegidos


class CuentasService:

    @staticmethod
    def crear(
        db: Session,
        nombre: str,
        numero_empleado: str,
        sitio_id: Optional[int],
        email: Optional[str] = None,
        rol: str = "usuario",
        area: Optional[str] = None,
        idioma: str = "es",
        fecha_ingreso=None,
        fecha_nacimiento=None,
        numero_epp=None,
        plantas=None,
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
        # TI es global y no lleva planta; una persona de planta, al menos una.
        if rol == "admin":
            sitio_id, plantas = None, []
        else:
            plantas = list(plantas or ([sitio_id] if sitio_id else []))
            if not plantas:
                raise ErrorCuenta("Indique al menos una planta.")
            sitio_id = sitio_id or plantas[0]

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
        if plantas:
            from app.core.plantas import asignar_plantas
            asignar_plantas(db, usuario, plantas)
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
        # Las cuentas eliminadas quedan sin número ni correo, así que no
        # entrarían aquí de todas formas; el filtro está escrito para que la
        # regla no dependa de ese efecto secundario.
        usuario = db.query(Usuario).filter(
            Usuario.numero_empleado == valor, Usuario.eliminado_en.is_(None)).first()
        if usuario:
            return usuario
        return db.query(Usuario).filter(
            Usuario.email == valor.lower(), Usuario.eliminado_en.is_(None)).first()

    @staticmethod
    def activar(
        db: Session,
        identificador: str,
        password: str,
        codigo: Optional[str] = None,
        nombre_completo: Optional[str] = None,
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
        # **Un solo mensaje para todo lo que no sea acertar**: la cuenta no
        # existe, no está pendiente, la credencial no coincide o la vía está
        # cerrada. Si cada caso tuviera el suyo, la pantalla de activación
        # serviría para averiguar quién está dado de alta —justo lo que
        # `estado_publico` se cuida de no hacer—. Nombra el código porque es la
        # salida de todos esos casos, sea cual sea el que le tocó a quien lo lee.
        #
        # Los dos avisos específicos que quedan —código vencido, plazo
        # terminado— solo salen **después** de acertar. Antes salían primero, y
        # un código inventado contra una cuenta vencida contestaba "venció":
        # confirmaba la cuenta sin saber nada de ella.
        generico = ("Los datos no coinciden. Si no logra activar su cuenta, "
                    "solicite un código al área de TI.")

        declarados = {"nombre_completo": nombre_completo,
                      "numero_epp": numero_epp,
                      "fecha_nacimiento": fecha_nacimiento,
                      "fecha_ingreso": fecha_ingreso}

        # Se mira **antes** de buscar la cuenta. Después contestaba distinto
        # según existiera, y un cuerpo vacío bastaba para recorrer el padrón.
        if not codigo and not any(declarados.values()):
            raise ErrorCuenta("Faltan los datos de verificación.")

        usuario = CuentasService.buscar_por_identificador(db, identificador)
        if usuario:
            # La fila queda bloqueada hasta el commit. Dos activaciones a la vez
            # con el mismo código —un doble clic, o quien lo interceptó— se
            # ponen en fila, y la segunda ya encuentra la cuenta activa. Sin
            # esto las dos pasaban y ganaba la última contraseña. Lo mismo vale
            # para el contador de intentos, que perdía fallos simultáneos.
            db.refresh(usuario, with_for_update=True)

        vigente = bool(usuario and usuario.activo and usuario.estado_cuenta == PENDIENTE)
        vencida = bool(vigente and usuario.codigo_expira
                       and usuario.codigo_expira < datetime.utcnow())

        if codigo:
            # Se compara siempre contra algo, exista la cuenta o no: bcrypt
            # tarda ~250 ms, y responder al instante cuando no hay cuenta
            # delataba las que sí. Es lo mismo que hace el inicio de sesión.
            real = usuario.codigo_activacion_hash if vigente else None
            acierta = verify_password(normalizar_codigo(codigo), real or HASH_SENUELO)
            if not (real and acierta):
                raise ErrorCuenta(generico)
            if vencida:
                raise ErrorCuenta("El código venció. Solicite uno nuevo al área de TI.")

        else:
            exigidos = factores_a_pedir(usuario) if vigente else []

            # Vía cerrada —por cinco fallos, o porque TI restableció la cuenta—:
            # se contesta como a una cuenta que no existe y **sin mirar los
            # datos**. Mirarlos aunque no activaran convertiría esto en un
            # oráculo para confirmar cumpleaños sin límite de intentos.
            if not exigidos or usuario.verificacion_bloqueada:
                raise ErrorCuenta(generico)

            # Hay que acertarlos todos. Nada de crédito parcial: acertar uno de
            # dos no acerca a nadie a demostrar que es quien dice.
            if not all(_coincide(usuario, f, declarados.get(f)) for f in exigidos):
                # Cuenta aunque el plazo ya haya pasado: el freno de cinco
                # intentos no puede tener una ventana en la que no frena.
                usuario.intentos_activacion = (usuario.intentos_activacion or 0) + 1
                if usuario.intentos_activacion >= settings.ACTIVACION_MAX_INTENTOS:
                    usuario.verificacion_bloqueada = True
                    logger.warning(
                        "Verificación por datos personales bloqueada tras varios fallos",
                        extra={"numero_empleado": usuario.numero_empleado,
                               "intentos": usuario.intentos_activacion},
                    )
                db.commit()
                raise ErrorCuenta(generico)

            # La ventana acota el riesgo del modo sin código: pasada la fecha,
            # lo que quede sin activar necesita que TI entregue un código.
            if vencida:
                raise ErrorCuenta(
                    "El periodo de activación terminó. Solicite un código al área de TI."
                )

        problema = validar_password(password, usuario)
        if problema:
            raise ErrorCuenta(problema)

        usuario.password_hash = get_password_hash(password)
        usuario.version_token = (usuario.version_token or 1) + 1
        usuario.intentos_activacion = 0
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
        usuario.version_token = (usuario.version_token or 1) + 1
        # La persona está enfrente con este código: nadie más necesita la vía
        # de los datos personales mientras tanto. Ver `restablecer`.
        usuario.verificacion_bloqueada = True
        db.commit()

        logger.info("Activación asistida abierta",
                    extra={"numero_empleado": usuario.numero_empleado})
        return codigo, expira

    @staticmethod
    def cambiar_password(db: Session, usuario: Usuario, actual: str, nueva: str) -> Usuario:
        """Cambio hecho por la propia persona, verificando la contraseña vigente."""
        if not usuario.password_hash or not verify_password(actual, usuario.password_hash):
            raise ErrorCuenta("La contraseña actual no es correcta.")

        problema = validar_password(nueva, usuario)
        if problema:
            raise ErrorCuenta(problema)
        if verify_password(nueva, usuario.password_hash):
            raise ErrorCuenta("La contraseña nueva debe ser distinta de la actual.")

        usuario.password_hash = get_password_hash(nueva)
        usuario.debe_cambiar_password = False
        # Cambiar la contrasena echa fuera cualquier sesion abierta con la
        # anterior. Es lo que uno espera al cambiarla porque cree que se la
        # vieron: sin esto, el token robado seguia entrando ocho horas mas.
        usuario.version_token = (usuario.version_token or 1) + 1
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
        # Restablecer es justo el caso de "creemos que alguien mas entro":
        # cualquier sesion viva deja de valer en el acto.
        usuario.version_token = (usuario.version_token or 1) + 1
        # **Y solo vuelve a entrar quien reciba este codigo.** Sin esto la
        # cuenta quedaba pendiente con la via de los datos personales abierta
        # una semana: el EPP y el cumpleaños salen de la misma lista de RH que
        # probablemente tiene quien entro sin permiso, asi que podia volver a
        # quedarse con la cuenta antes de que la persona recibiera su codigo.
        usuario.verificacion_bloqueada = True
        db.commit()

        logger.info("Contraseña restablecida por TI",
                    extra={"numero_empleado": usuario.numero_empleado})
        return codigo

    @staticmethod
    def estado_publico() -> dict:
        """Qué le toca hacer a alguien que llega con su correo.

        Nunca revela si el correo existe: si no está dado de alta, responde lo
        mismo que si estuviera activo. Así la pantalla de entrada no sirve para
        averiguar quién trabaja aquí.

        **Por eso ni siquiera se busca la cuenta.** Se buscaba y el resultado
        no se usaba: una consulta por cada visita a una ruta pública, y una
        diferencia de tiempo —poca, pero medible— entre el número que existe y
        el que no. Lo que no decide nada no se consulta.
        """
        # **La respuesta es la misma exista o no la cuenta.**
        #
        # Antes, una cuenta pendiente contestaba distinto de una activa y de una
        # inexistente. Con numeros de empleado del 1 al 600, recorrer el rango
        # devolvia quien trabaja aqui y en que estado esta cada quien: 600
        # peticiones y tienes el padron.
        #
        # El asistente de activacion avanza siempre, y si los datos no cuadran
        # se entera al final, con un mensaje que no distingue "no existe" de
        # "te equivocaste". Cuesta un paso de mas a quien se equivoco de numero;
        # a cambio, la pantalla de entrada deja de ser un directorio.
        # **Siempre la misma lista**, sin mirar la cuenta.
        #
        # Devolver los factores reales seguia delatando: una cuenta con solo
        # nombre respondia una lista de uno, y una completa de tres. El numero
        # de campos bastaba para distinguirlas, asi que la fuga no desaparecia,
        # cambiaba de forma. Se piden siempre los mismos tres y la validacion de
        # verdad ocurre despues, contra lo que esa cuenta tenga registrado.
        #
        # A quien no tenga EPP ni fecha en el padron le fallara al final y
        # tendra que pedir codigo a TI, que es justo lo que ya le tocaba.
        return {
            "accion": "activar",
            "acepta_codigo": True,
            "acepta_verificacion": True,
            "datos_verificacion": list(CAMPOS_QUE_SE_PIDEN),
        }
