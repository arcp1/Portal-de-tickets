"""El alta y la activación de una cuenta, de punta a punta.

Las pruebas de `test_cuentas.py` y `test_seguridad.py` miran cada regla por
separado. Esta sigue a una persona entera —TI la da de alta, recibe el código,
lo usa, entra— y comprueba en la base, en cada paso, lo que tiene que haber
cambiado y lo que no.

Debajo van las regresiones de los fallos que salieron al recorrerlo. Casi todos
son de la misma familia: **un mensaje distinto para una cuenta que existe que
para una que no**. La regla del portal es que la puerta no sirve de directorio
—ver `CuentasService.estado_publico`—, y cada uno de esos mensajes la rompía
por un lado distinto. La prueba de cada uno compara la respuesta de una cuenta
real con la de un número que no existe: tienen que ser idénticas.
"""

from datetime import datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.models import Auditoria, Usuario
from app.services.cuentas_service import ACTIVA, PENDIENTE

PASSWORD = "MiClaveSegura1"
NADIE = "99999"

# Lo que la persona teclearía en el asistente, y algo que no es suyo.
SUS_DATOS = {"nombre_completo": "Rosa Campos", "numero_epp": "421",
             "fecha_nacimiento": "02/05/1979"}
DATOS_AJENOS = {"nombre_completo": "Rosa Campos", "numero_epp": "1111",
                "fecha_nacimiento": "1990-01-01"}


@pytest.fixture(autouse=True)
def dominio_de_prueba(monkeypatch):
    monkeypatch.setattr(settings, "DOMINIOS_PERMITIDOS", "test.com")


def _cab(client, identificador="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _alta(client, numero, **extra):
    datos = {"nombre": "Rosa Elena Campos", "numero_empleado": numero,
             "area": "Producción", "numero_epp": "0421",
             "fecha_nacimiento": "1979-05-02"}
    datos.update(extra)
    return client.post("/api/admin/usuarios", json=datos, headers=_cab(client))


def _activar(client, identificador, password=PASSWORD, **credencial):
    r = client.post("/api/auth/activar",
                    json={"identificador": identificador, "password": password, **credencial})
    return r.status_code, r.json().get("detail")


def _vencer(db_session, usuario_id):
    persona = db_session.get(Usuario, usuario_id)
    persona.codigo_expira = datetime.utcnow() - timedelta(hours=1)
    db_session.commit()
    return persona


# ======================================================================
# El recorrido completo
# ======================================================================

def test_de_punta_a_punta(client, db_session):
    # --- 1. TI da de alta. La cuenta nace sin contraseña y con un código que
    #        solo existe, en claro, en esta respuesta.
    r = _alta(client, "30001", email="rosa.campos@test.com")
    assert r.status_code == 201, r.text
    alta = r.json()
    codigo = alta["codigo"]

    persona = db_session.get(Usuario, alta["usuario_id"])
    assert persona.estado_cuenta == PENDIENTE
    assert persona.activo is True
    assert persona.password_hash is None
    assert persona.codigo_activacion_hash
    assert codigo not in persona.codigo_activacion_hash
    assert verify_password(codigo.replace("-", ""), persona.codigo_activacion_hash)
    vida = persona.codigo_expira - datetime.utcnow()
    assert timedelta(hours=settings.CODIGO_ACTIVACION_HORAS - 1) < vida \
        <= timedelta(hours=settings.CODIGO_ACTIVACION_HORAS)
    version_de_alta = persona.version_token
    assert db_session.query(Auditoria).filter_by(
        accion="usuario.creado", entidad_id=persona.id).count() == 1

    # --- 2. Antes de activarse no entra: ni con el código como contraseña ni
    #        con la que piensa ponerse.
    for intento in (codigo, PASSWORD):
        r = client.post("/api/auth/login", json={"email": "30001", "password": intento})
        assert r.status_code == 401

    # --- 3. Paso 1 del asistente.
    r = client.post("/api/auth/estado-cuenta", json={"identificador": "30001"})
    assert r.status_code == 200
    assert r.json()["accion"] == "activar"

    # --- 4. Activa con el código tal como lo teclearía: minúsculas y sin guion.
    r = client.post("/api/auth/activar", json={
        "identificador": "30001", "password": PASSWORD,
        "codigo": codigo.lower().replace("-", "")})
    assert r.status_code == 200, r.text
    sesion = r.json()
    assert sesion["user"]["id"] == persona.id

    db_session.refresh(persona)
    assert persona.estado_cuenta == ACTIVA
    assert verify_password(PASSWORD, persona.password_hash)
    assert persona.codigo_activacion_hash is None      # el código se quemó
    assert persona.codigo_expira is None
    assert persona.intentos_activacion == 0
    assert persona.version_token == version_de_alta + 1
    assert persona.ultimo_acceso is not None

    # --- 5. El token de la activación lleva la versión nueva y abre sesión.
    carga = jwt.decode(sesion["access_token"], settings.JWT_SECRET,
                       algorithms=[settings.JWT_ALGORITHM])
    assert carga["sub"] == str(persona.id)
    assert carga["ver"] == persona.version_token
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sesion['access_token']}"})
    assert r.status_code == 200
    assert r.json()["numero_empleado"] == "30001"

    # Uno emitido con la versión de antes de activarse ya no vale.
    viejo = create_access_token(subject=persona.id, version_token=version_de_alta)
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {viejo}"}).status_code == 401

    # --- 6. Entra con su número y con su correo.
    for identificador in ("30001", "rosa.campos@test.com"):
        r = client.post("/api/auth/login", json={"email": identificador, "password": PASSWORD})
        assert r.status_code == 200, identificador

    # --- 7. El código no sirve una segunda vez, y el intento no toca nada.
    status, _ = _activar(client, "30001", password="OtraClaveLarga9", codigo=codigo)
    assert status == 400
    db_session.refresh(persona)
    assert verify_password(PASSWORD, persona.password_hash)


def test_la_sesion_trae_el_nombre_de_su_planta(client):
    """La barra y los avisos dicen la planta de quien entra, no una escrita en
    las traducciones. El portal está hecho para varias."""
    r = client.post("/api/auth/login", json={"email": "user@test.com", "password": "Secret123!"})
    assert r.json()["user"]["sitio_nombre"] == "Planta Querétaro"

    r = client.get("/api/auth/me", headers=_cab(client, "user@test.com"))
    assert r.json()["sitio_nombre"] == "Planta Querétaro"


# ======================================================================
# La puerta no confirma quién está dado de alta
# ======================================================================

def test_sin_codigo_ni_datos_la_respuesta_no_delata_la_cuenta(client):
    """Antes: «Faltan los datos de verificación» si la cuenta existía y
    «Datos incorrectos» si no. Un cuerpo vacío bastaba para recorrer el padrón."""
    _alta(client, "30010")
    assert _activar(client, "30010") == _activar(client, NADIE)


def test_un_codigo_vencido_no_se_confiesa_sin_tener_el_codigo(client, db_session):
    """Antes el vencimiento se miraba antes que el código: cualquier código
    inventado contra una cuenta vencida contestaba «El código venció»."""
    _vencer(db_session, _alta(client, "30011").json()["usuario_id"])
    assert _activar(client, "30011", codigo="AAAA-AAAA") == \
        _activar(client, NADIE, codigo="AAAA-AAAA")


def test_quien_tiene_su_codigo_vencido_si_se_entera(client, db_session):
    """El aviso útil se conserva para quien demostró tener el código."""
    alta = _alta(client, "30012").json()
    _vencer(db_session, alta["usuario_id"])
    status, detalle = _activar(client, "30012", codigo=alta["codigo"])
    assert status == 400
    assert "venció" in detalle


def test_la_ventana_vencida_no_se_confiesa_con_datos_ajenos(client, db_session):
    """Antes «El periodo de activación terminó» salía antes de mirar los datos:
    delataba a toda cuenta que siguiera pendiente pasado el plazo."""
    _vencer(db_session, _alta(client, "30013").json()["usuario_id"])
    assert _activar(client, "30013", **DATOS_AJENOS) == _activar(client, NADIE, **DATOS_AJENOS)


def test_quien_acierta_sus_datos_fuera_de_plazo_si_se_entera(client, db_session):
    _vencer(db_session, _alta(client, "30014").json()["usuario_id"])
    status, detalle = _activar(client, "30014", **SUS_DATOS)
    assert status == 400
    assert "periodo" in detalle


def test_los_datos_ajenos_fuera_de_plazo_siguen_contando_como_intento(client, db_session):
    """Mover la comprobación del plazo detrás de la de los datos no puede
    abrir un hueco en el freno de cinco intentos."""
    persona = _vencer(db_session, _alta(client, "30019").json()["usuario_id"])
    _activar(client, "30019", **DATOS_AJENOS)
    db_session.refresh(persona)
    assert persona.intentos_activacion == 1


def test_la_via_cerrada_no_se_confiesa(client, db_session):
    """Antes una cuenta bloqueada contestaba «ya no se puede activar con datos
    personales», aunque quien preguntara no supiera nada de esa persona."""
    persona = db_session.get(Usuario, _alta(client, "30015").json()["usuario_id"])
    persona.verificacion_bloqueada = True
    db_session.commit()

    assert _activar(client, "30015", **SUS_DATOS) == _activar(client, NADIE, **SUS_DATOS)


def test_el_mensaje_comun_dice_que_hacer(client):
    """Que sea el mismo para todos no lo puede dejar inútil: quien se quedó
    fuera por la razón que sea tiene que leer que el camino es un código de TI."""
    status, detalle = _activar(client, NADIE, **SUS_DATOS)
    assert status == 400
    assert "código" in detalle


# ======================================================================
# Un restablecimiento no se puede deshacer con la lista de RH
# ======================================================================

@pytest.mark.parametrize("ruta", ["restablecer", "activacion-asistida"])
def test_tras_restablecer_solo_vale_el_codigo_de_ti(client, db_session, ruta):
    """TI restablece cuando cree que alguien más entró. Si después bastaran el
    EPP y el cumpleaños —los dos de la misma lista de RH que ese alguien
    probablemente tiene—, se quedaría con la cuenta otra vez antes de que la
    persona recibiera su código."""
    alta = _alta(client, "30016").json()
    assert _activar(client, "30016", codigo=alta["codigo"])[0] == 200

    r = client.post(f"/api/admin/usuarios/{alta['usuario_id']}/{ruta}", headers=_cab(client))
    assert r.status_code == 200, r.text
    nuevo = r.json()["codigo"]

    status, _ = _activar(client, "30016", password="ClaveDelIntruso9", **SUS_DATOS)
    assert status == 400
    persona = db_session.get(Usuario, alta["usuario_id"])
    db_session.refresh(persona)
    assert persona.estado_cuenta == PENDIENTE
    assert persona.password_hash is None

    assert _activar(client, "30016", password="OtraClaveLarga9", codigo=nuevo)[0] == 200


# ======================================================================
# El alta y la edición validan lo mismo
# ======================================================================

def test_el_alta_no_se_traga_una_fecha_que_no_entiende(client, db_session):
    """Antes una fecha ilegible se descartaba sin avisar: la cuenta nacía sin
    cumpleaños y la persona no podía activarse con él, sin que TI supiera por qué."""
    r = _alta(client, "30017", fecha_nacimiento="31/02/1979")
    assert r.status_code == 422
    assert "fecha de nacimiento" in r.json()["detail"]
    assert db_session.query(Usuario).filter_by(numero_empleado="30017").first() is None


def test_el_alta_no_acepta_un_nombre_en_blanco(client):
    assert _alta(client, "30018", nombre="     ").status_code == 422


def test_editar_no_deja_a_nadie_sin_numero_de_empleado(client):
    """El número es con lo que la persona entra. Vaciarlo la dejaba fuera."""
    usuario_id = _alta(client, "30020").json()["usuario_id"]
    r = client.patch(f"/api/admin/usuarios/{usuario_id}",
                     json={"numero_empleado": "   "}, headers=_cab(client))
    assert r.status_code == 422


@pytest.mark.parametrize("correo", ["esto-no-es-un-correo", "rosa@gmail.com"])
def test_editar_valida_el_correo_como_el_alta(client, correo):
    usuario_id = _alta(client, "30021").json()["usuario_id"]
    r = client.patch(f"/api/admin/usuarios/{usuario_id}",
                     json={"email": correo}, headers=_cab(client))
    assert r.status_code == 422


def test_editar_puede_quitar_el_correo(client):
    usuario_id = _alta(client, "30022", email="rosa@test.com").json()["usuario_id"]
    r = client.patch(f"/api/admin/usuarios/{usuario_id}",
                     json={"email": ""}, headers=_cab(client))
    assert r.status_code == 200
    assert r.json()["email"] is None
