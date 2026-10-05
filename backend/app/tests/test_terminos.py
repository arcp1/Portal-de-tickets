"""Términos y Condiciones: nadie usa el portal sin aceptarlos, y la aceptación
deja constancia de qué texto exacto se aceptó, cuándo y desde dónde.

Las cuentas de este archivo nacen **sin** los términos aceptados (la marca
`terminos_pendientes`; ver conftest.py), que es como estarán todas las cuentas
de producción al desplegar.
"""

import asyncio
import dataclasses
import hashlib

import pytest

from app.core import terminos
from app.models import Auditoria, Usuario

pytestmark = pytest.mark.terminos_pendientes


def _sesion(client, email="user@test.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    assert r.status_code == 200
    return r.json(), {"Authorization": f"Bearer {r.json()['access_token']}"}


def _aceptar(client, cabeceras, **cambios):
    vigente = client.get("/api/terminos").json()
    cuerpo = {"version": vigente["version"], "huella": vigente["huella"], **cambios}
    return client.post("/api/auth/terminos", headers=cabeceras, json=cuerpo)


# ----------------------------------------------------------------------
# El texto
# ----------------------------------------------------------------------

def test_el_texto_vigente_se_lee_sin_sesion_y_es_el_del_archivo(client):
    r = client.get("/api/terminos")
    assert r.status_code == 200
    doc = r.json()
    assert doc["version"] == "1.0" and doc["vigente_desde"] == "2026-10-05"
    assert len(doc["secciones"]) == 12
    # La huella es la del archivo: lo que se muestra es lo que se registra.
    crudo = terminos.ARCHIVO.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert doc["huella"] == hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def test_las_clausulas_de_proteccion_cubren_al_desarrollador_y_a_ti(client):
    secciones = {s["titulo"].split(".")[0]: " ".join(s["parrafos"])
                 for s in client.get("/api/terminos").json()["secciones"]}
    assert "ALEX RIOS CARBALLO" in secciones["SEGUNDA"]
    for clausula in ("CUARTA", "QUINTA", "SEXTA", "SÉPTIMA"):
        assert "Departamento de TI" in secciones[clausula], clausula
        assert "Desarrollador" in secciones[clausula] or "Equipo Técnico" in secciones[clausula]
    assert "paros de línea" in secciones["QUINTA"] and "dolo" in secciones["QUINTA"]
    assert "Inteligencia Artificial" in secciones["SEXTA"]
    assert "paros de emergencia" in secciones["SÉPTIMA"]


def test_un_archivo_mal_formado_no_se_acepta_en_silencio():
    with pytest.raises(ValueError):
        terminos.leer("Sin cabecera.\n")
    with pytest.raises(ValueError):
        terminos.leer("---\nversion: 1.0\nvigente_desde: hoy\ntitulo: T\n---\n\nTexto suelto.\n")
    with pytest.raises(ValueError):
        terminos.leer("---\nversion: 1.0\ntitulo: T\n---\n## UNA\nTexto.\n")


def test_la_huella_no_depende_de_los_saltos_de_linea():
    texto = "---\nversion: 1\nvigente_desde: hoy\ntitulo: T\n---\n## UNA\nTexto.\n"
    assert terminos.leer(texto).huella == terminos.leer(texto.replace("\n", "\r\n")).huella


# ----------------------------------------------------------------------
# El bloqueo
# ----------------------------------------------------------------------

def test_sin_aceptar_la_api_responde_terminos_pendientes(client):
    sesion, cab = _sesion(client)
    assert sesion["user"]["terminos_vigentes"] is False

    r = client.get("/api/tickets", headers=cab)
    assert r.status_code == 403
    assert r.json()["codigo"] == "terminos_pendientes"

    # Lo que sí puede: saber quién es, leer los términos y salir.
    yo = client.get("/api/auth/me", headers=cab)
    assert yo.status_code == 200 and yo.json()["terminos_vigentes"] is False
    assert client.get("/api/terminos").status_code == 200
    assert client.post("/api/auth/logout", headers=cab).status_code == 200


def test_ti_tampoco_entra_sin_aceptar(client):
    _, cab = _sesion(client, "admin@test.com")
    r = client.get("/api/admin/usuarios", headers=cab)
    assert r.status_code == 403 and r.json()["codigo"] == "terminos_pendientes"


def test_un_403_de_permisos_sigue_siendo_otro_codigo(client):
    """El código propio es solo para los términos: un usuario normal que pide
    algo de TI sigue recibiendo el 403 de siempre."""
    _, cab = _sesion(client)
    assert _aceptar(client, cab).status_code == 200
    r = client.get("/api/admin/usuarios", headers=cab)
    assert r.status_code == 403 and r.json()["codigo"] != "terminos_pendientes"


# ----------------------------------------------------------------------
# La aceptación y su constancia
# ----------------------------------------------------------------------

def test_aceptar_abre_el_portal_y_deja_constancia(client, db_session):
    _, cab = _sesion(client)
    vigente = client.get("/api/terminos").json()
    r = _aceptar(client, {**cab, "X-Forwarded-For": "203.0.113.50",
                          "User-Agent": "Navegador de prueba"})
    assert r.status_code == 200
    yo = r.json()
    assert yo["terminos_vigentes"] is True
    assert yo["terminos_version"] == "1.0" and yo["terminos_aceptados_en"]

    assert client.get("/api/tickets", headers=cab).status_code == 200

    constancia = db_session.query(Auditoria).filter_by(accion="terminos.aceptados").one()
    assert constancia.usuario_id == yo["id"] and constancia.entidad_id == yo["id"]
    assert constancia.ip == "203.0.113.50"
    assert constancia.detalle["version"] == "1.0"
    assert constancia.detalle["huella_sha256"] == vigente["huella"]
    assert constancia.detalle["navegador"] == "Navegador de prueba"


@pytest.mark.parametrize("cambio", [{"version": "0.9"}, {"huella": "0" * 64}])
def test_no_se_acepta_un_texto_distinto_del_vigente(client, db_session, cambio):
    """La pantalla manda la versión y la huella de lo que mostró. Si no son las
    vigentes, la persona leyó otra cosa: no se registra nada."""
    _, cab = _sesion(client)
    r = _aceptar(client, cab, **cambio)
    assert r.status_code == 409
    assert client.get("/api/tickets", headers=cab).status_code == 403
    assert db_session.query(Auditoria).filter_by(accion="terminos.aceptados").count() == 0


def test_aceptar_otra_vez_no_cambia_la_fecha_ni_duplica_la_constancia(client, db_session):
    _, cab = _sesion(client)
    primera = _aceptar(client, cab).json()["terminos_aceptados_en"]
    segunda = _aceptar(client, cab).json()["terminos_aceptados_en"]
    assert primera == segunda
    assert db_session.query(Auditoria).filter_by(accion="terminos.aceptados").count() == 1


def test_una_version_nueva_vuelve_a_pedir_la_aceptacion(client, monkeypatch):
    _, cab = _sesion(client)
    assert _aceptar(client, cab).status_code == 200
    assert client.get("/api/tickets", headers=cab).status_code == 200

    nueva = dataclasses.replace(terminos.documento(), version="1.1", huella="f" * 64)
    monkeypatch.setattr(terminos, "documento", lambda: nueva)
    assert client.get("/api/tickets", headers=cab).status_code == 403
    assert client.get("/api/auth/me", headers=cab).json()["terminos_vigentes"] is False
    assert _aceptar(client, cab).status_code == 200
    assert client.get("/api/tickets", headers=cab).status_code == 200


def test_la_activacion_entrega_la_sesion_con_los_terminos_pendientes(client, db_session):
    from app.tests.test_seguridad import _pendiente

    _pendiente(db_session, numero="4501")
    r = client.post("/api/auth/activar", json={
        "identificador": "4501", "password": "UnaClaveLarga1",
        "nombre_completo": "Operador Nuevo", "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"})
    assert r.status_code == 200
    assert r.json()["user"]["terminos_vigentes"] is False


# ----------------------------------------------------------------------
# El grafo en vivo (WebSocket)
# ----------------------------------------------------------------------

class WebSocketFalso:
    """Lo justo de un WebSocket para `_autenticar`: un mensaje y un cierre.
    Uno de verdad dentro de TestClient cuelga la suite (ver test_eventos.py)."""

    def __init__(self, mensaje):
        self.mensaje = mensaje
        self.cierre = None

    async def receive_json(self):
        return self.mensaje

    async def close(self, code=1000, reason=None):
        self.cierre = (code, reason)


def _autenticar_ws(db_session, monkeypatch, token):
    from sqlalchemy.orm import sessionmaker

    from app.api import conciencia

    # La misma base de la prueba. Importar la del conftest no sirve: el módulo
    # se cargaría otra vez, con otra base en memoria, vacía.
    monkeypatch.setattr(conciencia, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    ws = WebSocketFalso({"token": token})
    return asyncio.run(conciencia._autenticar(ws)), ws


def test_el_grafo_en_vivo_tampoco_se_abre_sin_aceptar(client, db_session, monkeypatch):
    sesion, cab = _sesion(client)
    usuario, ws = _autenticar_ws(db_session, monkeypatch, sesion["access_token"])
    assert usuario is None and ws.cierre == (1008, "terminos_pendientes")

    assert _aceptar(client, cab).status_code == 200
    usuario, ws = _autenticar_ws(db_session, monkeypatch, sesion["access_token"])
    assert isinstance(usuario, Usuario) and ws.cierre is None
