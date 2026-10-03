"""Prioridad alta revocable, y tickets que su dueño cancela.

Dos reglas de negocio del 2026-09-30:

  * Quien reporta indica la urgencia al crear —alta y crítica incluidas—, pero
    TI puede revocarle ese uso. Con el permiso revocado el ticket nace en
    "media" aunque se pida más, se pida desde la pantalla o por la API.
  * El dueño puede cancelar su ticket mientras siga en la cola. Cancelar
    detiene el reloj del SLA en el acto y no cuenta como resolución.
"""

import pytest

from app.models import Auditoria, Ticket, TicketComentario, Usuario


def _cab(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _crear(client, cabeceras, prioridad="media", **extra):
    datos = {"sitio_id": 1, "categoria": "red", "descripcion_original": "Sin red en mi lugar",
             "prioridad": prioridad}
    datos.update(extra)
    return client.post("/api/tickets", json=datos, headers=cabeceras)


def _revocar(client, db_session, permitida=False):
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.patch(f"/api/admin/usuarios/{usuario.id}",
                     json={"puede_usar_prioridad_alta": permitida},
                     headers=_cab(client, "admin@test.com"))
    assert r.status_code == 200, r.text
    return usuario, r.json()


# ======================================================================
# Prioridad alta revocable
# ======================================================================

def test_la_prioridad_alta_esta_permitida_de_entrada(client):
    yo = client.get("/api/auth/me", headers=_cab(client, "user@test.com")).json()
    assert yo["puede_usar_prioridad_alta"] is True

    r = _crear(client, _cab(client, "user@test.com"), prioridad="critica")
    assert r.status_code == 201
    assert r.json()["prioridad"] == "critica"


@pytest.mark.parametrize("pedida", ["alta", "critica"])
def test_con_el_permiso_revocado_nace_en_media(client, db_session, pedida):
    """Aunque se salte la pantalla y lo pida directo a la API."""
    _revocar(client, db_session)

    r = _crear(client, _cab(client, "user@test.com"), prioridad=pedida)
    assert r.status_code == 201, r.text
    ticket = r.json()
    assert ticket["prioridad"] == "media"

    # El compromiso es el de "media", no el de lo que se pidió.
    referencia = _crear(client, _cab(client, "admin@test.com"), prioridad="media").json()
    assert ticket["vence_en"][:13] == referencia["vence_en"][:13]

    # TI queda enterada de lo que se pidió; quien reporta no ve la nota.
    nota = db_session.query(TicketComentario).filter_by(ticket_id=ticket["id"]).one()
    assert nota.es_interno is True
    assert pedida in nota.comentario
    visto = client.get(f"/api/tickets/{ticket['id']}", headers=_cab(client, "user@test.com")).json()
    assert visto["comentarios"] == []


def test_con_el_permiso_revocado_baja_y_media_siguen_igual(client, db_session):
    _revocar(client, db_session)
    cab = _cab(client, "user@test.com")
    assert _crear(client, cab, prioridad="baja").json()["prioridad"] == "baja"
    assert _crear(client, cab, prioridad="media").json()["prioridad"] == "media"


def test_la_revocacion_no_toca_a_ti(client, db_session):
    admin = db_session.query(Usuario).filter_by(email="admin@test.com").one()
    admin.puede_usar_prioridad_alta = False
    db_session.commit()
    r = _crear(client, _cab(client, "admin@test.com"), prioridad="critica")
    assert r.json()["prioridad"] == "critica"


def test_ti_revoca_y_devuelve_el_permiso_y_queda_en_bitacora(client, db_session):
    usuario, respuesta = _revocar(client, db_session, permitida=False)
    assert respuesta["puede_usar_prioridad_alta"] is False
    yo = client.get("/api/auth/me", headers=_cab(client, "user@test.com")).json()
    assert yo["puede_usar_prioridad_alta"] is False

    _, respuesta = _revocar(client, db_session, permitida=True)
    assert respuesta["puede_usar_prioridad_alta"] is True
    assert _crear(client, _cab(client, "user@test.com"), prioridad="alta").json()["prioridad"] == "alta"

    registros = (db_session.query(Auditoria)
                 .filter_by(accion="usuario.prioridad_alta", entidad_id=usuario.id)
                 .order_by(Auditoria.id).all())
    assert [r.detalle["permitida"] for r in registros] == [False, True]
    # Sin una entrada genérica de "editado" duplicando la misma sanción.
    assert db_session.query(Auditoria).filter_by(accion="usuario.editado",
                                                 entidad_id=usuario.id).count() == 0


def test_el_permiso_es_cosa_de_ti(client, db_session):
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.patch(f"/api/admin/usuarios/{usuario.id}", json={"puede_usar_prioridad_alta": True},
                     headers=_cab(client, "user@test.com"))
    assert r.status_code == 403


def test_una_prioridad_inventada_se_rechaza_al_crear(client):
    r = _crear(client, _cab(client, "user@test.com"), prioridad="urgentisima")
    assert r.status_code == 422


# ======================================================================
# Cancelar un ticket
# ======================================================================

def test_el_dueno_cancela_y_el_sla_se_detiene(client, db_session):
    cab = _cab(client, "user@test.com")
    ticket = _crear(client, cab, prioridad="alta").json()
    assert ticket["vence_en"] is not None

    r = client.post(f"/api/tickets/{ticket['id']}/cancelar", headers=cab)
    assert r.status_code == 200, r.text
    cancelado = r.json()
    assert cancelado["estado"] == "cancelado"
    assert cancelado["vence_en"] is None          # el reloj del SLA se detuvo
    assert cancelado["cancelado_en"] is not None
    # No es una resolución: nada de eso se toca.
    assert cancelado["resuelto_en"] is None
    assert cancelado["tiempo_resolucion"] is None
    assert cancelado["solucion"] is None

    # Queda dicho en el ticket, a la vista de TI y de quien reportó.
    assert "canceló" in cancelado["comentarios"][-1]["comentario"]
    assert db_session.query(Auditoria).filter_by(accion="ticket.cancelado",
                                                 entidad_id=ticket["id"]).count() == 1


def test_un_cancelado_no_es_trabajo_pendiente_de_nadie(client, db_session):
    cab = _cab(client, "user@test.com")
    ticket = _crear(client, cab).json()
    client.post(f"/api/tickets/{ticket['id']}/cancelar", headers=cab)

    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    fila = next(u for u in client.get("/api/admin/usuarios", headers=_cab(client, "admin@test.com")).json()
                if u["id"] == usuario.id)
    assert fila["tickets_abiertos"] == 0


def test_los_cancelados_van_aparte_en_las_metricas(client):
    cab = _cab(client, "user@test.com")
    atendido = _crear(client, cab).json()
    retirado = _crear(client, cab).json()
    client.post(f"/api/tickets/{retirado['id']}/cancelar", headers=cab)
    assert atendido["estado"] == "abierto"

    tickets = client.get("/api/metricas", headers=_cab(client, "admin@test.com")).json()["tickets"]
    assert tickets["tickets_total"] == 1
    assert tickets["tickets_abiertos"] == 1
    assert tickets["tickets_cancelados"] == 1
    assert tickets["tickets_cancelados_periodo"] == 1
    # Ni en el reparto por canal —un cancelado nace con canal "tecnico"—
    # ni en las categorías.
    assert sum(tickets["por_canal"].values()) == 1
    assert sum(c["total"] for c in tickets["por_categoria"]) == 1


@pytest.mark.parametrize("estado", ["resuelto", "cerrado", "cancelado"])
def test_no_se_cancela_lo_que_ya_termino(client, db_session, estado):
    cab = _cab(client, "user@test.com")
    ticket = _crear(client, cab).json()
    fila = db_session.get(Ticket, ticket["id"])
    fila.estado = estado
    db_session.commit()

    r = client.post(f"/api/tickets/{ticket['id']}/cancelar", headers=cab)
    assert r.status_code == 409


def test_solo_el_dueno_cancela(client, db_session):
    ticket = _crear(client, _cab(client, "user@test.com")).json()
    # TI lo ve, pero no es suyo: lo cierra con solución, no lo cancela.
    r = client.post(f"/api/tickets/{ticket['id']}/cancelar", headers=_cab(client, "admin@test.com"))
    assert r.status_code == 403
    assert db_session.get(Ticket, ticket["id"]).estado == "abierto"


def test_un_cancelado_ya_no_se_edita_pero_si_se_comenta(client):
    cab = _cab(client, "user@test.com")
    ticket = _crear(client, cab).json()
    client.post(f"/api/tickets/{ticket['id']}/cancelar", headers=cab)

    admin = _cab(client, "admin@test.com")
    r = client.patch(f"/api/tickets/{ticket['id']}", json={"estado": "abierto"}, headers=admin)
    assert r.status_code == 409
    r = client.post(f"/api/tickets/{ticket['id']}/comments", json={"comentario": "Enterados."},
                    headers=admin)
    assert r.status_code == 201


def test_el_filtro_del_tablero_encuentra_los_cancelados(client):
    cab = _cab(client, "user@test.com")
    ticket = _crear(client, cab).json()
    _crear(client, cab)
    client.post(f"/api/tickets/{ticket['id']}/cancelar", headers=cab)

    pagina = client.get("/api/tickets", params={"estado": "cancelado"}, headers=cab).json()
    assert pagina["total"] == 1
    assert pagina["items"][0]["id"] == ticket["id"]


# ======================================================================
# Reintentos tras un corte de red (clave de envío)
# ======================================================================

def test_el_reintento_con_la_misma_clave_devuelve_el_mismo_ticket(client, db_session):
    """Si la red se corta después de crearlo, la pantalla dice "no se pudo" y la
    persona vuelve a pulsar: antes eran dos tickets, dos folios, dos SLA."""
    cab = {**_cab(client, "user@test.com"), "Idempotency-Key": "a1b2c3d4-0001-4bcd-9e8f-000000000001"}
    primero = _crear(client, cab)
    segundo = _crear(client, cab)
    assert primero.status_code == 201 and segundo.status_code == 201
    assert primero.json()["id"] == segundo.json()["id"]
    assert primero.json()["folio"] == segundo.json()["folio"]
    assert db_session.query(Ticket).count() == 1


def test_la_clave_es_de_cada_quien(client, db_session):
    clave = {"Idempotency-Key": "clave-compartida-0001"}
    uno = _crear(client, {**_cab(client, "user@test.com"), **clave}).json()
    otro = _crear(client, {**_cab(client, "admin@test.com"), **clave}).json()
    assert uno["id"] != otro["id"]


def test_sin_clave_cada_envio_es_un_ticket(client, db_session):
    cab = _cab(client, "user@test.com")
    _crear(client, cab)
    _crear(client, cab)
    assert db_session.query(Ticket).count() == 2


@pytest.mark.parametrize("clave", ["corta", "con espacios dentro", "x" * 65, "<script>"])
def test_una_clave_malformada_se_rechaza(client, clave):
    r = _crear(client, {**_cab(client, "user@test.com"), "Idempotency-Key": clave})
    assert r.status_code == 422


def test_la_respuesta_de_crear_no_trae_notas_internas(client, db_session):
    """Con el permiso revocado, el sistema deja una nota interna al degradar la
    prioridad; la respuesta del alta se la mandaba a quien reportó."""
    _revocar(client, db_session)
    r = _crear(client, _cab(client, "user@test.com"), prioridad="critica")
    assert r.status_code == 201
    assert r.json()["comentarios"] == []
    assert db_session.query(TicketComentario).filter_by(es_interno=True).count() == 1
