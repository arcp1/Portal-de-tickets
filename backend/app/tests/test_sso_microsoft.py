"""Inicio de sesión con Microsoft: el flujo entero contra un Microsoft de
mentira que firma de verdad.

La suite no sale a la red (conftest.py). Aquí se sustituyen las tres
llamadas a Microsoft —canje del código, llaves públicas y Graph— por dobles
que se comportan como el real: el `id_token` va firmado con RS256 por una
llave generada en la prueba, y el doble del canje **comprueba el PKCE** (que
el verificador que manda el portal corresponda al reto que puso en la URL).
Así lo que se prueba es la validación del portal, no la de un doble.
"""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core.config import settings
from app.models import Auditoria, Usuario
from app.services import sso_microsoft as sso

INQUILINO = "0b6f5c1e-7d2a-4c3b-9e8f-1a2b3c4d5e6f"
OTRO_INQUILINO = "11111111-2222-3333-4444-555555555555"
CLIENTE = "cliente-de-prueba"
OID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA_LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def microsoft_configurado(monkeypatch):
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", CLIENTE)
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", "secreto-de-prueba")
    monkeypatch.setattr(settings, "MICROSOFT_TENANT_ID", INQUILINO)
    monkeypatch.setattr(settings, "MICROSOFT_REDIRECT_URI", "http://testserver/api/auth/microsoft/callback")
    # El .env de la máquina dice cgr.mx; las cuentas de prueba son @test.com.
    monkeypatch.setattr(settings, "DOMINIOS_PERMITIDOS", "test.com")
    sso.llavero.olvidar()
    sso._canjeados.clear()
    yield
    sso.llavero.olvidar()


class Microsoft:
    """El Microsoft de mentira. `perfil` y `afirmaciones` se cambian por
    prueba para producir cada caso."""

    def __init__(self, monkeypatch):
        self.reto = None
        self.nonce = None
        self.llamadas = 0
        self.llave = LLAVE
        self.afirmaciones = {}
        self.perfil = {"id": OID, "mail": "user@test.com", "userPrincipalName": "user@test.com",
                       "userType": "Member"}
        publica = json.loads(RSAAlgorithm.to_jwk(LLAVE.public_key()))
        monkeypatch.setattr(sso, "_descargar_llaves", lambda: {"k1": RSAAlgorithm.from_jwk(json.dumps(publica))})
        monkeypatch.setattr(sso, "_pedir_tokens", self._tokens)
        monkeypatch.setattr(sso, "_perfil_graph", lambda acceso: dict(self.perfil))

    def _tokens(self, codigo, verificador):
        self.llamadas += 1
        reto = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        assert reto == self.reto, "el verificador PKCE no corresponde al reto"
        ahora = int(time.time())
        datos = {"iss": f"https://login.microsoftonline.com/{INQUILINO}/v2.0", "aud": CLIENTE,
                 "exp": ahora + 3600, "iat": ahora, "nbf": ahora, "nonce": self.nonce,
                 "oid": OID, "tid": INQUILINO, "name": "User Test", "sub": "x"}
        datos.update(self.afirmaciones)
        token = jwt.encode(datos, self.llave, algorithm="RS256", headers={"kid": "k1"})
        return {"id_token": token, "access_token": "token-de-graph"}

    def entrar(self, client, **parametros):
        """El navegador: botón, Microsoft y vuelta. Devuelve la redirección final."""
        r = client.get("/api/auth/microsoft/login", follow_redirects=False)
        assert r.status_code == 302
        consulta = parse_qs(urlsplit(r.headers["location"]).query)
        self.reto, self.nonce = consulta["code_challenge"][0], consulta["nonce"][0]
        estado = parametros.pop("state", consulta["state"][0])
        return client.get("/api/auth/microsoft/callback",
                          params={"code": "codigo-de-microsoft", "state": estado, **parametros},
                          headers={"User-Agent": "Navegador de prueba/1.0"}, follow_redirects=False)


@pytest.fixture
def microsoft(monkeypatch):
    return Microsoft(monkeypatch)


def _fragmento(respuesta):
    assert respuesta.status_code == 303, respuesta.text
    destino = respuesta.headers["location"]
    assert destino.startswith("/login#")
    return dict(p.split("=", 1) for p in destino.split("#", 1)[1].split("&"))


def _canje(client, respuesta):
    return client.post("/api/auth/microsoft/canje", json={"codigo": _fragmento(respuesta)["sso"]})


# ----------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------

def test_sin_configurar_el_boton_no_aparece_y_la_entrada_avisa(client, monkeypatch):
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", "")
    assert client.get("/api/auth/microsoft/config").json() == {"activo": False, "url": None}
    r = client.get("/api/auth/microsoft/login", follow_redirects=False)
    assert _fragmento(r) == {"sso_error": "no_configurado"}
    # El login de siempre sigue igual.
    assert client.post("/api/auth/login", json={"email": "user@test.com", "password": "Secret123!"}).status_code == 200


@pytest.mark.parametrize("inquilino", ["common", "organizations", "cgr.mx", ""])
def test_un_inquilino_que_no_es_un_guid_no_cuenta_como_configurado(client, monkeypatch, inquilino):
    monkeypatch.setattr(settings, "MICROSOFT_TENANT_ID", inquilino)
    assert client.get("/api/auth/microsoft/config").json()["activo"] is False


def test_el_boton_lleva_al_origen_del_callback(client, monkeypatch):
    monkeypatch.setattr(settings, "MICROSOFT_REDIRECT_URI", "https://portal.cgr.mx/api/auth/microsoft/callback")
    assert client.get("/api/auth/microsoft/config").json() == {
        "activo": True, "url": "https://portal.cgr.mx/api/auth/microsoft/login"}


def test_la_ida_lleva_pkce_state_y_nonce_y_la_cookie_va_cerrada(client):
    r = client.get("/api/auth/microsoft/login", follow_redirects=False)
    destino = urlsplit(r.headers["location"])
    consulta = parse_qs(destino.query)
    assert destino.netloc == "login.microsoftonline.com" and destino.path.startswith(f"/{INQUILINO}/")
    assert consulta["code_challenge_method"] == ["S256"] and consulta["response_type"] == ["code"]
    assert len(consulta["state"][0]) >= 40 and len(consulta["nonce"][0]) >= 40
    galleta = r.headers["set-cookie"].lower()
    assert "httponly" in galleta and "samesite=lax" in galleta and "path=/api/auth/microsoft" in galleta
    # El verificador PKCE no viaja a la vista de nadie: la cookie va cifrada.
    assert consulta["state"][0] not in r.headers["set-cookie"]


def test_con_https_la_cookie_va_marcada_segura(client, monkeypatch):
    monkeypatch.setattr(settings, "MICROSOFT_REDIRECT_URI", "https://portal.cgr.mx/api/auth/microsoft/callback")
    r = client.get("/api/auth/microsoft/login", follow_redirects=False)
    assert "secure" in r.headers["set-cookie"].lower()


# ----------------------------------------------------------------------
# El flujo bueno
# ----------------------------------------------------------------------

def test_primera_entrada_vincula_por_correo_y_entrega_la_sesion(client, db_session, microsoft):
    r = microsoft.entrar(client)
    sesion = _canje(client, r)
    assert sesion.status_code == 200, sesion.text
    assert sesion.json()["user"]["email"] == "user@test.com"
    assert sesion.json()["user"]["microsoft_vinculada"] is True
    # El token es una sesión normal del portal.
    yo = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sesion.json()['access_token']}"})
    assert yo.status_code == 200 and yo.json()["email"] == "user@test.com"

    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    assert usuario.microsoft_oid == OID and usuario.ultimo_acceso is not None
    entradas = db_session.query(Auditoria).filter(Auditoria.usuario_id == usuario.id).all()
    acciones = {a.accion for a in entradas}
    assert {"auth.microsoft", "usuario.microsoft_vinculada"} <= acciones
    entrada = next(a for a in entradas if a.accion == "auth.microsoft")
    assert entrada.ip and entrada.detalle["navegador"] == "Navegador de prueba/1.0"


def test_despues_entra_por_oid_aunque_cambie_el_correo(client, db_session, microsoft):
    assert _canje(client, microsoft.entrar(client)).status_code == 200
    # Le cambian el correo en Microsoft: sigue siendo la misma persona.
    microsoft.perfil.update(mail="otro.buzon@test.com", userPrincipalName="otro.buzon@test.com")
    sesion = _canje(client, microsoft.entrar(client))
    assert sesion.status_code == 200 and sesion.json()["user"]["email"] == "user@test.com"


def test_el_codigo_de_canje_sirve_una_sola_vez(client, microsoft):
    r = microsoft.entrar(client)
    assert _canje(client, r).status_code == 200
    assert _canje(client, r).status_code == 401


def test_el_codigo_de_canje_no_sirve_como_sesion(client, microsoft):
    codigo = _fragmento(microsoft.entrar(client))["sso"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {codigo}"})
    assert r.status_code == 401


def test_el_codigo_caduca_al_minuto(client, microsoft, monkeypatch):
    codigo = _fragmento(microsoft.entrar(client))["sso"]
    monkeypatch.setattr(sso, "VIDA_CANJE_S", -1)
    assert client.post("/api/auth/microsoft/canje", json={"codigo": codigo}).status_code == 401


def test_si_lo_dan_de_baja_entre_la_vuelta_y_el_canje_no_entra(client, db_session, microsoft):
    r = microsoft.entrar(client)
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    usuario.activo = False
    db_session.commit()
    assert _canje(client, r).status_code == 401


@pytest.mark.terminos_pendientes
def test_quien_entra_con_microsoft_tambien_pasa_por_los_terminos(client, microsoft):
    sesion = _canje(client, microsoft.entrar(client))
    assert sesion.status_code == 200
    assert sesion.json()["user"]["terminos_vigentes"] is False
    cab = {"Authorization": f"Bearer {sesion.json()['access_token']}"}
    r = client.get("/api/tickets", headers=cab)
    assert r.status_code == 403 and r.json()["codigo"] == "terminos_pendientes"


def test_una_cuenta_sin_activar_entra_con_microsoft(client, db_session, microsoft):
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    usuario.password_hash, usuario.estado_cuenta = None, "pendiente_activacion"
    db_session.commit()
    assert _canje(client, microsoft.entrar(client)).status_code == 200


# ----------------------------------------------------------------------
# Lo que se rechaza
# ----------------------------------------------------------------------

def test_un_state_ajeno_se_rechaza_sin_hablar_con_microsoft(client, microsoft):
    r = microsoft.entrar(client, state="state-de-otro-navegador-" + "x" * 20)
    assert _fragmento(r) == {"sso_error": "estado_invalido"}
    assert microsoft.llamadas == 0


def test_sin_la_cookie_del_intento_se_rechaza(client, microsoft):
    r = client.get("/api/auth/microsoft/callback", params={"code": "c", "state": "s" * 43},
                   follow_redirects=False)
    assert _fragmento(r) == {"sso_error": "estado_invalido"}
    assert microsoft.llamadas == 0


def test_cancelar_en_microsoft_vuelve_con_su_aviso(client, microsoft):
    r = microsoft.entrar(client, error="access_denied", error_description="AADSTS65004: el usuario canceló")
    assert _fragmento(r) == {"sso_error": "cancelado"}


def test_un_correo_que_no_existe_se_rechaza_y_queda_en_la_bitacora(client, db_session, microsoft):
    microsoft.perfil.update(mail="nadie@test.com", userPrincipalName="nadie@test.com")
    r = microsoft.entrar(client)
    assert _fragmento(r) == {"sso_error": "no_registrada"}
    fila = db_session.query(Auditoria).filter(Auditoria.accion == "auth.microsoft_rechazado").one()
    assert fila.usuario_id is None and fila.detalle["correo"] == "nadie@test.com"
    assert fila.detalle["motivo"] == "no_registrada" and fila.ip
    # Y se ve en la bitácora aunque no tenga cuenta.
    cab = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "admin@test.com", "password": "Secret123!"}).json()["access_token"]}
    filas = client.get("/api/auditoria", params={"accion": "auth.microsoft_rechazado"}, headers=cab).json()
    assert len(filas) == 1 and filas[0]["usuario"] is None


def test_una_cuenta_dada_de_baja_se_rechaza_y_queda_en_la_bitacora(client, db_session, microsoft):
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    usuario.activo = False
    db_session.commit()
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "cuenta_inactiva"}
    fila = db_session.query(Auditoria).filter(Auditoria.accion == "auth.microsoft_rechazado").one()
    assert fila.usuario_id == usuario.id and fila.detalle["motivo"] == "cuenta_inactiva"
    assert usuario.microsoft_oid is None


def test_un_correo_de_otro_dominio_no_vincula(client, db_session, microsoft, monkeypatch):
    monkeypatch.setattr(settings, "DOMINIOS_PERMITIDOS", "cgr.mx")
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "no_registrada"}


def test_otro_inquilino_se_rechaza(client, microsoft):
    microsoft.afirmaciones = {"iss": f"https://login.microsoftonline.com/{OTRO_INQUILINO}/v2.0",
                              "tid": OTRO_INQUILINO}
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "tenant_invalido"}


def test_las_cuentas_de_invitado_no_entran(client, db_session, microsoft):
    microsoft.perfil["userType"] = "Guest"
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "tenant_invalido"}
    assert db_session.query(Usuario).filter(Usuario.microsoft_oid.isnot(None)).count() == 0


def test_un_token_firmado_con_otra_llave_se_rechaza(client, microsoft):
    microsoft.llave = OTRA_LLAVE
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "fallo"}


def test_un_token_para_otra_aplicacion_se_rechaza(client, microsoft):
    microsoft.afirmaciones = {"aud": "otra-aplicacion"}
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "fallo"}


def test_un_nonce_distinto_se_rechaza(client, microsoft):
    microsoft.afirmaciones = {"nonce": "nonce-de-otro-intento"}
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "estado_invalido"}


def test_una_cuenta_ya_vinculada_a_otra_cuenta_de_microsoft_no_se_toma(client, db_session, microsoft):
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    usuario.microsoft_oid = "99999999-9999-9999-9999-999999999999"
    db_session.commit()
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "conflicto"}
    db_session.refresh(usuario)
    assert usuario.microsoft_oid == "99999999-9999-9999-9999-999999999999"


def test_demasiadas_vueltas_desde_una_ip_se_frenan(client, microsoft, monkeypatch):
    from app.core import limitador
    monkeypatch.setattr(limitador.limitador_sso_ip, "maximo", 2)
    assert "sso" in _fragmento(microsoft.entrar(client))
    assert "sso" in _fragmento(microsoft.entrar(client))
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "demasiados"}


# ----------------------------------------------------------------------
# Administración
# ----------------------------------------------------------------------

def _admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_ti_puede_desvincular_y_queda_en_la_bitacora(client, db_session, microsoft):
    assert _canje(client, microsoft.entrar(client)).status_code == 200
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    personas = client.get("/api/admin/usuarios", headers=_admin(client)).json()
    assert next(p for p in personas if p["id"] == usuario.id)["microsoft_vinculada"] is True
    r = client.delete(f"/api/admin/usuarios/{usuario.id}/microsoft", headers=_admin(client))
    assert r.status_code == 200 and r.json() == {"microsoft_vinculada": False}
    db_session.refresh(usuario)
    assert usuario.microsoft_oid is None
    assert db_session.query(Auditoria).filter(Auditoria.accion == "usuario.microsoft_desvinculada").count() == 1


def test_desvincular_es_solo_de_ti(client, db_session):
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    r = client.post("/api/auth/login", json={"email": "user@test.com", "password": "Secret123!"})
    cab = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.delete(f"/api/admin/usuarios/{usuario.id}/microsoft", headers=cab).status_code == 403


def test_eliminar_la_cuenta_suelta_la_de_microsoft(client, db_session, microsoft):
    assert _canje(client, microsoft.entrar(client)).status_code == 200
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    assert client.delete(f"/api/admin/usuarios/{usuario.id}", headers=_admin(client)).status_code == 200
    db_session.refresh(usuario)
    assert usuario.microsoft_oid is None
    # Y ya no entra: el correo se borró con la cuenta.
    assert _fragmento(microsoft.entrar(client)) == {"sso_error": "no_registrada"}
