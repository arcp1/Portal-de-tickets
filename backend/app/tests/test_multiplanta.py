"""Multi-planta: TI global, personas en una o varias plantas.

Las reglas están en `app/core/plantas.py`. Aquí se prueba que cada ruta las
respeta desde fuera, con dos plantas de verdad (Querétaro, la del conftest, y
Monterrey, la de `otra_planta`):

  * TI (rol admin) no tiene planta y alcanza todas.
  * Una persona de planta solo ve y elige equipos y tickets de las suyas.
  * Lo que no alcanza se responde 404, nunca 403.
"""

import pytest

from app.core.security import get_password_hash
from app.models import Equipo, Sitio, Ticket, Usuario


def _cab(client, email, password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _persona(db, email, numero, plantas):
    usuario = Usuario(sitio_id=plantas[0].id, nombre=f"Persona {numero}", email=email,
                      numero_empleado=numero, password_hash=get_password_hash("Secret123!"),
                      rol="usuario", activo=True, estado_cuenta="activa")
    usuario.plantas = list(plantas)
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def _equipo(db, sitio, serie):
    equipo = Equipo(sitio_id=sitio.id, tipo="activo", categoria="impresora", marca="Zebra",
                    modelo="ZT410", numero_serie=serie, ubicacion="Línea 1", estado="disponible")
    db.add(equipo)
    db.commit()
    db.refresh(equipo)
    return equipo


@pytest.fixture
def qro(db_session):
    return db_session.get(Sitio, 1)


@pytest.fixture
def escenario(db_session, qro, otra_planta):
    """Un equipo en cada planta y una persona que trabaja en las dos."""
    return {
        "eq_qro": _equipo(db_session, qro, "QRO-001"),
        "eq_mty": _equipo(db_session, otra_planta, "MTY-001"),
        "doble": _persona(db_session, "doble@test.com", "5001", [qro, otra_planta]),
        "mty": otra_planta,
    }


# ---------------------------------------------------------------------------
# Quién es quién
# ---------------------------------------------------------------------------

def test_ti_es_global_y_la_persona_trae_sus_plantas(client, escenario):
    yo = client.get("/api/auth/me", headers=_cab(client, "admin@test.com")).json()
    assert yo["es_ti_global"] is True
    assert yo["sitio_id"] is None and yo["plantas"] == []

    yo = client.get("/api/auth/me", headers=_cab(client, "doble@test.com")).json()
    assert yo["es_ti_global"] is False
    assert {p["clave"] for p in yo["plantas"]} == {"QRO", "MTY"}


def test_cada_quien_ve_sus_plantas(client, escenario):
    claves = lambda email: {s["clave"] for s in  # noqa: E731
                            client.get("/api/sitios", headers=_cab(client, email)).json()}
    assert claves("admin@test.com") == {"QRO", "MTY"}
    assert claves("user@test.com") == {"QRO"}
    assert claves("doble@test.com") == {"QRO", "MTY"}


# ---------------------------------------------------------------------------
# Equipos
# ---------------------------------------------------------------------------

def test_la_persona_solo_ve_equipos_de_sus_plantas(client, escenario):
    series = lambda email, q="": {e["numero_serie"] for e in  # noqa: E731
                                  client.get(f"/api/equipos{q}", headers=_cab(client, email)).json()}
    assert series("user@test.com") == {"QRO-001"}
    assert series("doble@test.com") == {"QRO-001", "MTY-001"}
    assert series("admin@test.com") == {"QRO-001", "MTY-001"}
    # Pedir una planta ajena no amplía nada.
    assert series("user@test.com", f"?sitio_id={escenario['mty'].id}") == set()

    ajeno = escenario["eq_mty"].id
    assert client.get(f"/api/equipos/{ajeno}", headers=_cab(client, "user@test.com")).status_code == 404


def test_cada_equipo_trae_la_etiqueta_de_su_planta(client, escenario):
    equipos = client.get("/api/equipos", headers=_cab(client, "admin@test.com")).json()
    assert {e["numero_serie"]: e["sitio"]["clave"] for e in equipos} == {
        "QRO-001": "QRO", "MTY-001": "MTY"}


def test_ti_da_de_alta_equipos_en_la_planta_que_diga(client, escenario):
    cab = _cab(client, "admin@test.com")
    cuerpo = {"tipo": "activo", "categoria": "laptop", "marca": "Dell", "modelo": "5440",
              "numero_serie": "NUEVO-1", "ubicacion": "TI", "estado": "disponible"}
    # Con dos plantas no hay una "suya": se pide.
    assert client.post("/api/equipos", headers=cab, json=cuerpo).status_code == 422
    r = client.post("/api/equipos", headers=cab, json={**cuerpo, "sitio_id": escenario["mty"].id})
    assert r.status_code == 201, r.text
    assert r.json()["sitio"]["clave"] == "MTY"


def test_un_equipo_no_se_asigna_a_quien_no_alcanza_su_planta(client, escenario, db_session):
    cab = _cab(client, "admin@test.com")
    de_qro = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.patch(f"/api/equipos/{escenario['eq_mty'].id}", headers=cab,
                     json={"asignado_a": de_qro.id})
    assert r.status_code == 422, r.text
    # A quien trabaja en las dos, sí.
    r = client.patch(f"/api/equipos/{escenario['eq_mty'].id}", headers=cab,
                     json={"asignado_a": escenario["doble"].id})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------

def _ticket(client, email, **extra):
    return client.post("/api/tickets", headers=_cab(client, email), json={
        "categoria": "impresora", "descripcion_original": "La impresora no imprime etiquetas",
        "prioridad": "media", **extra})


def test_la_persona_levanta_en_sus_plantas_y_no_en_otras(client, escenario):
    mty = escenario["mty"].id
    assert _ticket(client, "user@test.com", sitio_id=mty).status_code == 422

    r = _ticket(client, "doble@test.com", sitio_id=mty, equipo_id=escenario["eq_mty"].id)
    assert r.status_code == 201, r.text
    assert r.json()["folio"].startswith("TICK-MTY-")
    assert r.json()["sitio"]["clave"] == "MTY"


def test_no_se_elige_un_equipo_de_otra_planta(client, escenario):
    # Querétaro, con el equipo de Monterrey: el equipo no está en esa planta.
    r = _ticket(client, "doble@test.com", sitio_id=1, equipo_id=escenario["eq_mty"].id)
    assert r.status_code == 422, r.text


def test_ti_ve_todos_los_tickets_y_puede_filtrar(client, escenario):
    assert _ticket(client, "user@test.com").status_code == 201
    assert _ticket(client, "doble@test.com", sitio_id=escenario["mty"].id).status_code == 201

    cab = _cab(client, "admin@test.com")
    todos = client.get("/api/tickets", headers=cab).json()["items"]
    assert sorted(t["sitio"]["clave"] for t in todos) == ["MTY", "QRO"]
    de_mty = client.get(f"/api/tickets?sitio_id={escenario['mty'].id}", headers=cab).json()["items"]
    assert [t["sitio"]["clave"] for t in de_mty] == ["MTY"]

    # La persona, solo los suyos.
    mios = client.get("/api/tickets", headers=_cab(client, "user@test.com")).json()["items"]
    assert len(mios) == 1


def test_ti_solo_asigna_a_ti(client, escenario, db_session):
    r = _ticket(client, "user@test.com")
    tid = r.json()["id"]
    cab = _cab(client, "admin@test.com")
    persona = db_session.query(Usuario).filter_by(email="user@test.com").one()
    assert client.patch(f"/api/tickets/{tid}", headers=cab,
                        json={"asignado_a": persona.id}).status_code == 422


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

def test_alta_de_persona_en_varias_plantas_y_de_ti_sin_planta(client, escenario):
    cab = _cab(client, "admin@test.com")
    mty = escenario["mty"].id
    r = client.post("/api/admin/usuarios", headers=cab, json={
        "nombre": "Dos Plantas", "numero_empleado": "7001", "plantas": [mty, 1]})
    assert r.status_code == 201, r.text
    lista = client.get("/api/admin/usuarios", headers=cab).json()
    nueva = next(u for u in lista if u["numero_empleado"] == "7001")
    assert nueva["sitio_id"] == mty, "la primera de la lista es la principal"
    assert {p["clave"] for p in nueva["plantas"]} == {"QRO", "MTY"}

    r = client.post("/api/admin/usuarios", headers=cab, json={
        "nombre": "Otra de TI", "numero_empleado": "7002", "rol": "admin", "plantas": [mty]})
    assert r.status_code == 201, r.text
    lista = client.get("/api/admin/usuarios", headers=cab).json()
    ti = next(u for u in lista if u["numero_empleado"] == "7002")
    assert ti["sitio_id"] is None and ti["plantas"] == []


def test_una_persona_de_planta_necesita_una_planta_valida(client, escenario):
    cab = _cab(client, "admin@test.com")
    # Con dos plantas no se adivina.
    r = client.post("/api/admin/usuarios", headers=cab,
                    json={"nombre": "Sin Planta", "numero_empleado": "7003"})
    assert r.status_code == 422
    r = client.post("/api/admin/usuarios", headers=cab,
                    json={"nombre": "Planta Falsa", "numero_empleado": "7004", "plantas": [999]})
    assert r.status_code == 422


def test_cambiar_plantas_y_pasar_a_ti(client, escenario, db_session):
    cab = _cab(client, "admin@test.com")
    persona = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.patch(f"/api/admin/usuarios/{persona.id}", headers=cab,
                     json={"plantas": [escenario["mty"].id]})
    assert r.status_code == 200, r.text
    assert [p["clave"] for p in r.json()["plantas"]] == ["MTY"]
    assert r.json()["sitio_id"] == escenario["mty"].id

    r = client.patch(f"/api/admin/usuarios/{persona.id}", headers=cab, json={"rol": "admin"})
    assert r.status_code == 200, r.text
    assert r.json()["plantas"] == [] and r.json()["sitio_id"] is None


def test_ti_ve_a_las_personas_de_todas_las_plantas(client, escenario):
    cab = _cab(client, "admin@test.com")
    correos = {u["email"] for u in client.get("/api/admin/usuarios", headers=cab).json()}
    assert {"user@test.com", "doble@test.com"} <= correos
    de_mty = client.get(f"/api/admin/usuarios?sitio_id={escenario['mty'].id}", headers=cab).json()
    assert {u["email"] for u in de_mty} == {"doble@test.com"}


# ---------------------------------------------------------------------------
# Plantas
# ---------------------------------------------------------------------------

def test_ti_administra_plantas_y_la_clave_no_se_repite(client, escenario):
    cab = _cab(client, "admin@test.com")
    r = client.post("/api/sitios", headers=cab, json={"clave": "slp", "nombre": "Planta San Luis"})
    assert r.status_code == 201, r.text
    assert r.json()["clave"] == "SLP"
    assert client.post("/api/sitios", headers=cab,
                       json={"clave": "SLP", "nombre": "Repetida"}).status_code == 409
    assert client.post("/api/sitios", headers=cab,
                       json={"clave": "S L", "nombre": "Con espacio"}).status_code == 422
    assert client.post("/api/sitios", headers=_cab(client, "user@test.com"),
                       json={"clave": "XX", "nombre": "De persona"}).status_code == 403

    nueva = r.json()["id"]
    r = client.patch(f"/api/sitios/{nueva}", headers=cab, json={"activo": False})
    assert r.status_code == 200 and r.json()["activo"] is False
    conteos = {s["clave"]: s for s in client.get("/api/sitios/admin", headers=cab).json()}
    assert conteos["SLP"]["activo"] is False
    assert conteos["QRO"]["equipos"] == 1


def test_no_se_desactiva_la_unica_planta(client):
    cab = _cab(client, "admin@test.com")
    assert client.patch("/api/sitios/1", headers=cab, json={"activo": False}).status_code == 409
