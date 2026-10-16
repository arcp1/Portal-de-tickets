"""Inicio de sesión con Microsoft (Entra ID): OpenID Connect, código con PKCE.

**El camino, de punta a punta.**

1. `GET /api/auth/microsoft/login` genera tres secretos de un solo uso —el
   `state` (contra CSRF), el `nonce` (ata el `id_token` a este intento) y el
   verificador PKCE— y los guarda **cifrados y firmados** en una cookie
   `HttpOnly` de diez minutos, limitada a `/api/auth/microsoft`. Después manda
   el navegador a Microsoft con el `state`, el `nonce` y el reto PKCE.
2. Microsoft vuelve a `/api/auth/microsoft/callback` con un código. Se
   comprueba que el `state` es el de la cookie, se canjea el código (con el
   secreto de la aplicación **y** el verificador PKCE) y se valida el
   `id_token`: firma contra las llaves públicas de Microsoft, emisor y
   audiencia, vigencia, `nonce` y que el inquilino sea el de la empresa.
3. Con el token de acceso se le pregunta a Graph (`/me`) el correo y el tipo
   de cuenta. **Los invitados no entran**: una cuenta de invitado puede traer
   cualquier correo, y es la manera de colarse que quedaría abierta.
4. La cuenta del portal se busca por el `oid` de Microsoft; si todavía no lo
   tiene, por el correo, y entonces se vincula (ver `resolver_cuenta`).
5. El token del portal **no viaja en la URL**. El callback redirige a
   `/login#sso=<código>`: un código de un minuto y un solo uso que la pantalla
   cambia por la sesión con un POST. En el fragmento no llega a ningún
   servidor ni a ningún registro, y aunque quedara en el historial del
   navegador ya no serviría.

**El inquilino va fijo** (`MICROSOFT_TENANT_ID`, un GUID). Con `common` u
`organizations` entraría cualquier cuenta de cualquier empresa, y el correo
de una cuenta ajena lo escribe quien administra la otra empresa: con eso
bastaría para entrar como cualquiera del portal.

**Por qué la cookie va cifrada y no solo firmada.** Lleva el verificador
PKCE, que es lo único que le falta a quien intercepte el código de Microsoft.
Fernet (de `cryptography`, que ya estaba) cifra, firma y caduca a la vez.

**Toda la conversación con Microsoft sale de aquí**, para que las pruebas la
sustituyan en un solo sitio: la suite no sale a la red (ver conftest.py).
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import redis_cliente
from app.core.config import settings
from app.core.logging import logger
from app.models import Usuario

AUTORIDAD = "https://login.microsoftonline.com"
GRAPH_ME = "https://graph.microsoft.com/v1.0/me"
# `User.Read` es lo mínimo para leer el propio perfil en Graph y no pide
# consentimiento de administrador.
ALCANCES = "openid profile email User.Read"

COOKIE = "portal_sso_ms"
COOKIE_RUTA = "/api/auth/microsoft"
VIDA_ESTADO_S = 600
VIDA_CANJE_S = 60
_TIEMPO = httpx.Timeout(10.0)
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Lo que la pantalla de entrada sabe explicar (`auth.sso_error_*`).
CODIGOS = ("no_configurado", "cancelado", "estado_invalido", "tenant_invalido",
           "no_registrada", "cuenta_inactiva", "conflicto", "demasiados", "fallo")


class ErrorSSO(Exception):
    """El intento no sigue. `codigo` es uno de `CODIGOS`; `usuario`, la cuenta
    del portal si se llegó a saber cuál era (para la bitácora)."""

    def __init__(self, codigo: str, motivo: str = "", usuario: Optional[Usuario] = None):
        super().__init__(motivo or codigo)
        self.codigo = codigo if codigo in CODIGOS else "fallo"
        self.motivo = motivo
        self.usuario = usuario


@dataclass
class Identidad:
    """Lo que Microsoft confirma de quien acaba de entrar."""
    oid: str
    tid: str
    nombre: str = ""
    correos: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------

def _inquilino() -> str:
    return (settings.MICROSOFT_TENANT_ID or "").strip().lower()


def motivo_inactivo() -> Optional[str]:
    """Por qué el inicio de sesión con Microsoft no está disponible, o None."""
    faltan = [n for n in ("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET",
                          "MICROSOFT_TENANT_ID", "MICROSOFT_REDIRECT_URI")
              if not (getattr(settings, n) or "").strip()]
    if faltan:
        return "faltan " + ", ".join(faltan)
    if not _GUID.match(_inquilino()):
        return "MICROSOFT_TENANT_ID tiene que ser el Id. de directorio (un GUID)"
    destino = urlsplit(settings.MICROSOFT_REDIRECT_URI.strip())
    if destino.scheme not in ("https", "http") or not destino.netloc:
        return "MICROSOFT_REDIRECT_URI no es una dirección completa"
    return None


def activo() -> bool:
    return motivo_inactivo() is None


def url_de_entrada() -> str:
    """Dónde empieza el inicio de sesión, **en el origen del callback**.

    La cookie del `state` se pone en el origen donde se abre esta ruta, y
    Microsoft vuelve al de `MICROSOFT_REDIRECT_URI`. Si fueran distintos —se
    entra al portal por la IP de la red interna y el callback es el nombre
    público con HTTPS— la cookie no volvería y todo intento fallaría. Así que
    el botón lleva directo al origen del callback, y la persona termina con
    su sesión ahí.
    """
    destino = urlsplit(settings.MICROSOFT_REDIRECT_URI.strip())
    return f"{destino.scheme}://{destino.netloc}{COOKIE_RUTA}/login"


def cookie_segura() -> bool:
    return settings.MICROSOFT_REDIRECT_URI.strip().lower().startswith("https://")


# ----------------------------------------------------------------------
# El estado del intento, en la cookie
# ----------------------------------------------------------------------

def _fernet(proposito: bytes) -> Fernet:
    """Una llave por propósito, derivada del secreto de las sesiones: un
    código de canje no se puede presentar como cookie de estado, ni al revés."""
    llave = hashlib.sha256(b"portal-sso-microsoft:" + proposito + b":" +
                           settings.JWT_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(llave))


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


@dataclass
class Estado:
    state: str
    nonce: str
    verificador: str


def nuevo_estado() -> Tuple[Estado, str]:
    """Los tres secretos de un intento y la cookie que los guarda."""
    estado = Estado(state=secrets.token_urlsafe(32), nonce=secrets.token_urlsafe(32),
                    verificador=secrets.token_urlsafe(64))
    galleta = _fernet(b"estado").encrypt(json.dumps(
        {"s": estado.state, "n": estado.nonce, "v": estado.verificador}).encode("utf-8"))
    return estado, galleta.decode("ascii")


def leer_estado(galleta: Optional[str]) -> Optional[Estado]:
    """El estado de la cookie, o None si falta, está alterada o caducó."""
    if not galleta:
        return None
    try:
        datos = json.loads(_fernet(b"estado").decrypt(galleta.encode("ascii"), ttl=VIDA_ESTADO_S))
        return Estado(state=datos["s"], nonce=datos["n"], verificador=datos["v"])
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        return None


def mismo_state(recibido: Optional[str], estado: Estado) -> bool:
    return bool(recibido) and hmac.compare_digest(recibido.encode("utf-8"), estado.state.encode("utf-8"))


def url_de_autorizacion(estado: Estado) -> str:
    reto = _b64(hashlib.sha256(estado.verificador.encode("ascii")).digest())
    parametros = {
        "client_id": settings.MICROSOFT_CLIENT_ID.strip(),
        "response_type": "code",
        "response_mode": "query",
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI.strip(),
        "scope": ALCANCES,
        "state": estado.state,
        "nonce": estado.nonce,
        "code_challenge": reto,
        "code_challenge_method": "S256",
        # En las computadoras compartidas de planta, que pregunte con qué
        # cuenta en vez de entrar con la del turno anterior.
        "prompt": "select_account",
    }
    return f"{AUTORIDAD}/{_inquilino()}/oauth2/v2.0/authorize?{urlencode(parametros)}"


# ----------------------------------------------------------------------
# Microsoft: canje del código, llaves públicas y Graph
# ----------------------------------------------------------------------

def _pedir_tokens(codigo: str, verificador: str) -> dict:
    respuesta = httpx.post(
        f"{AUTORIDAD}/{_inquilino()}/oauth2/v2.0/token",
        data={
            "client_id": settings.MICROSOFT_CLIENT_ID.strip(),
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": codigo,
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI.strip(),
            "code_verifier": verificador,
            "scope": ALCANCES,
        },
        timeout=_TIEMPO,
    )
    if respuesta.status_code != 200:
        # Solo el código de error de Microsoft (AADSTS…): la descripción
        # puede repetir el correo de la persona.
        try:
            cuerpo = respuesta.json()
        except ValueError:
            cuerpo = {}
        raise ErrorSSO("fallo", f"token {respuesta.status_code} {cuerpo.get('error')} "
                                f"{cuerpo.get('error_codes')}")
    return respuesta.json()


def _descargar_llaves() -> Dict[str, object]:
    respuesta = httpx.get(f"{AUTORIDAD}/{_inquilino()}/discovery/v2.0/keys", timeout=_TIEMPO)
    respuesta.raise_for_status()
    llaves = {}
    for jwk in respuesta.json().get("keys", []):
        if jwk.get("kty") == "RSA" and jwk.get("kid") and jwk.get("use", "sig") == "sig":
            llaves[jwk["kid"]] = RSAAlgorithm.from_jwk(json.dumps(jwk))
    return llaves


class _Llavero:
    """Las llaves públicas de Microsoft, en memoria un día.

    Microsoft las rota sin avisar: una `kid` desconocida obliga a volver a
    descargarlas, pero como mucho una vez por minuto, para que un token con
    una `kid` inventada no convierta cada intento en una descarga.
    """
    VIDA_S = 24 * 3600
    PAUSA_S = 60

    def __init__(self):
        self._candado = threading.Lock()
        self._llaves: Dict[str, object] = {}
        self._vencen = 0.0
        self._ultima = 0.0

    def llave(self, kid: Optional[str]):
        with self._candado:
            ahora = time.monotonic()
            vencidas = ahora > self._vencen
            if (kid not in self._llaves or vencidas) and (ahora - self._ultima > self.PAUSA_S or vencidas):
                self._ultima = ahora
                try:
                    self._llaves = _descargar_llaves()
                    self._vencen = ahora + self.VIDA_S
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("No se pudieron descargar las llaves de Microsoft",
                                   extra={"error": str(exc)})
            llave = self._llaves.get(kid)
        if llave is None:
            raise ErrorSSO("fallo", f"llave de firma desconocida: {kid}")
        return llave

    def olvidar(self):
        with self._candado:
            self._llaves, self._vencen, self._ultima = {}, 0.0, 0.0


llavero = _Llavero()


def validar_id_token(id_token: str, nonce: str) -> dict:
    """Las afirmaciones del `id_token`, o `ErrorSSO` si algo no cuadra."""
    try:
        cabecera = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise ErrorSSO("fallo", f"id_token ilegible: {exc}")
    # Solo RS256: ni `none` ni un HS256 firmado con la llave pública.
    if cabecera.get("alg") != "RS256":
        raise ErrorSSO("fallo", f"algoritmo inesperado: {cabecera.get('alg')}")
    llave = llavero.llave(cabecera.get("kid"))
    inquilino = _inquilino()
    try:
        datos = jwt.decode(
            id_token, llave, algorithms=["RS256"],
            audience=settings.MICROSOFT_CLIENT_ID.strip(),
            issuer=f"{AUTORIDAD}/{inquilino}/v2.0",
            leeway=120,
            options={"require": ["exp", "iat", "aud", "iss", "nonce", "oid", "tid"]},
        )
    except jwt.InvalidIssuerError:
        raise ErrorSSO("tenant_invalido", "emisor de otro inquilino")
    except jwt.PyJWTError as exc:
        raise ErrorSSO("fallo", f"id_token no válido: {exc}")
    if str(datos.get("tid", "")).lower() != inquilino:
        raise ErrorSSO("tenant_invalido", f"inquilino {datos.get('tid')}")
    if not hmac.compare_digest(str(datos.get("nonce")).encode("utf-8"), nonce.encode("utf-8")):
        raise ErrorSSO("estado_invalido", "nonce distinto")
    if not _GUID.match(str(datos.get("oid", "")).lower()):
        raise ErrorSSO("fallo", "oid ausente")
    return datos


def _perfil_graph(token_de_acceso: str) -> dict:
    respuesta = httpx.get(
        GRAPH_ME, params={"$select": "id,mail,userPrincipalName,userType"},
        headers={"Authorization": f"Bearer {token_de_acceso}"}, timeout=_TIEMPO,
    )
    if respuesta.status_code != 200:
        raise ErrorSSO("fallo", f"graph {respuesta.status_code}")
    return respuesta.json()


def identidad_desde_codigo(codigo: str, estado: Estado) -> Identidad:
    """Del código que devolvió Microsoft a una identidad confirmada."""
    try:
        tokens = _pedir_tokens(codigo, estado.verificador)
        afirmaciones = validar_id_token(str(tokens.get("id_token") or ""), estado.nonce)
        oid = str(afirmaciones["oid"]).lower()
        identidad = Identidad(oid=oid, tid=str(afirmaciones["tid"]).lower(),
                              nombre=str(afirmaciones.get("name") or "")[:100])
        perfil = _perfil_graph(str(tokens.get("access_token") or ""))
    except httpx.HTTPError as exc:
        raise ErrorSSO("fallo", f"sin respuesta de Microsoft: {type(exc).__name__}")
    if str(perfil.get("id", "")).lower() != oid:
        raise ErrorSSO("fallo", "Graph contestó por otra cuenta")
    # Una cuenta de invitado es de otra organización aunque entre por la
    # nuestra, y su correo lo pone quien la invitó.
    if (perfil.get("userType") or "Member") != "Member":
        raise ErrorSSO("tenant_invalido", f"cuenta {perfil.get('userType')}")
    correos = []
    for valor in (perfil.get("mail"), perfil.get("userPrincipalName")):
        correo = str(valor or "").strip().lower()
        if correo and _CORREO.match(correo) and "#ext#" not in correo and correo not in correos:
            correos.append(correo)
    identidad.correos = correos
    return identidad


# ----------------------------------------------------------------------
# La cuenta del portal
# ----------------------------------------------------------------------

def _puede_entrar(usuario: Usuario) -> bool:
    """Dada de baja (`activo` falso), eliminada o bloqueada: no.

    Una cuenta **dada de alta y sin activar** sí entra. Activar existe para
    que la persona demuestre quién es sin que TI le dé una contraseña, y eso
    es justo lo que acaba de hacer Microsoft con más garantías que una fecha
    de nacimiento. No se toca su estado: si algún día quiere contraseña, la
    activación sigue ahí.
    """
    return bool(usuario.activo) and usuario.eliminado_en is None and usuario.estado_cuenta != "bloqueada"


def _dominio_permitido(correo: str) -> bool:
    permitidos = [d.strip().lower().lstrip("@") for d in (settings.DOMINIOS_PERMITIDOS or "").split(",")
                  if d.strip()]
    return not permitidos or correo.rsplit("@", 1)[-1] in permitidos


def resolver_cuenta(db: Session, identidad: Identidad) -> Tuple[Usuario, bool]:
    """La cuenta del portal de esta identidad y si se acaba de vincular.

    Primero por `oid`: una vez vinculada, cambiarle el correo en el portal o
    en Microsoft no la desata. Si no hay ninguna, por correo **exacto** —sin
    distinguir mayúsculas—, solo de los dominios de la empresa, y solo si esa
    cuenta no está ya atada a otra cuenta de Microsoft.
    """
    usuario = db.query(Usuario).filter(Usuario.microsoft_oid == identidad.oid).first()
    if usuario is not None:
        if not _puede_entrar(usuario):
            raise ErrorSSO("cuenta_inactiva", "cuenta vinculada dada de baja", usuario)
        return usuario, False

    candidatos = [c for c in identidad.correos if _dominio_permitido(c)]
    for correo in candidatos:
        usuario = db.query(Usuario).filter(func.lower(Usuario.email) == correo).first()
        if usuario is None:
            continue
        if not _puede_entrar(usuario):
            raise ErrorSSO("cuenta_inactiva", "cuenta dada de baja", usuario)
        if usuario.microsoft_oid and usuario.microsoft_oid != identidad.oid:
            raise ErrorSSO("conflicto", "la cuenta ya está vinculada a otra cuenta de Microsoft", usuario)
        usuario.microsoft_oid = identidad.oid
        return usuario, True
    raise ErrorSSO("no_registrada", "ningún correo coincide")


# ----------------------------------------------------------------------
# El código de canje: de la redirección a la sesión
# ----------------------------------------------------------------------

_canjeados: Dict[str, float] = {}
_candado_canje = threading.Lock()


def emitir_canje(usuario: Usuario) -> str:
    carga = {"u": usuario.id, "v": int(usuario.version_token or 1), "j": secrets.token_hex(16)}
    return _fernet(b"canje").encrypt(json.dumps(carga).encode("utf-8")).decode("ascii")


def _primera_vez(jti: str) -> bool:
    """Si este código no se había usado. Con Redis vale para todos los
    procesos; sin él, para este, que es el único que hay (un uvicorn)."""
    vida = VIDA_CANJE_S + 60
    con_redis = redis_cliente.usar(
        lambda r: bool(r.set(f"sso:canje:{jti}", "1", nx=True, ex=vida)), None)
    if con_redis is not None:
        return con_redis
    ahora = time.monotonic()
    with _candado_canje:
        for viejo in [k for k, hasta in _canjeados.items() if hasta < ahora]:
            del _canjeados[viejo]
        if jti in _canjeados:
            return False
        _canjeados[jti] = ahora + vida
        return True


def canjear(codigo: str) -> Optional[Tuple[int, int]]:
    """(usuario_id, versión de la cuenta) del código, o None si no vale."""
    try:
        carga = json.loads(_fernet(b"canje").decrypt(codigo.encode("ascii"), ttl=VIDA_CANJE_S))
        usuario_id, version, jti = int(carga["u"]), int(carga["v"]), str(carga["j"])
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        return None
    if not _primera_vez(jti):
        return None
    return usuario_id, version
