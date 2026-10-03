"""Un listado cuesta lo mismo con uno que con quinientos registros.

El N+1 no se ve en desarrollo: con tres tickets de prueba, tres consultas de
más no las nota nadie. Con la planta entera —600 personas, miles de tickets— y
el tablero refrescándose en cada pantalla abierta cada vez que alguien mueve un
ticket, son miles de viajes a la base por cada cambio.

Estas pruebas no miden tiempo, que depende de la máquina: **cuentan consultas**
con uno y con cinco registros, y exigen que sean las mismas. Un listado que
crece con los datos las rompe en el acto.
"""

from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import event

from app.core.security import get_password_hash
from app.models import (Equipo, Resguardo, Ticket, TicketAdjunto, TicketComentario,
                        Usuario)

PASSWORD = "Secret123!"


@contextmanager
def contar_consultas(db_session):
    motor = db_session.get_bind()
    cuenta = {"n": 0}

    def contar(*_args, **_kwargs):
        cuenta["n"] += 1

    # Lo que ya está en memoria no cuesta consulta: el cliente de pruebas
    # comparte la sesión, así que se vacía para medir como una petición real.
    db_session.expunge_all()
    event.listen(motor, "before_cursor_execute", contar)
    try:
        yield cuenta
    finally:
        event.remove(motor, "before_cursor_execute", contar)


@pytest.fixture
def cab_admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@test.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_serie = iter(range(1, 10_000))


def _persona(db_session):
    n = next(_serie)
    persona = Usuario(sitio_id=1, nombre=f"Persona {n}", email=f"p{n}@test.com",
                      numero_empleado=f"9{n:04d}", password_hash=get_password_hash(PASSWORD),
                      rol="usuario", activo=True, estado_cuenta="activa")
    db_session.add(persona)
    db_session.flush()
    return persona


def _ticket_completo(db_session):
    """Un ticket con todo lo que el tablero pinta: quien reporta, a quién se
    asignó, comentarios de dos autores distintos y un adjunto."""
    reporta, tecnico, otro = _persona(db_session), _persona(db_session), _persona(db_session)
    n = next(_serie)
    ticket = Ticket(sitio_id=1, folio=f"TICK-QRO-2026-{n:04d}", usuario_id=reporta.id,
                    asignado_a=tecnico.id, categoria="red", descripcion_original="Sin red",
                    prioridad="media", estado="abierto", creado_en=datetime.utcnow())
    db_session.add(ticket)
    db_session.flush()
    db_session.add_all([
        TicketComentario(ticket_id=ticket.id, autor_id=tecnico.id, comentario="Reviso",
                         es_interno=False, creado_en=datetime.utcnow()),
        TicketComentario(ticket_id=ticket.id, autor_id=otro.id, comentario="Nota de TI",
                         es_interno=True, creado_en=datetime.utcnow()),
        TicketAdjunto(ticket_id=ticket.id, subido_por=reporta.id, nombre_original="f.png",
                      nombre_guardado=f"{n}.png", tipo_mime="image/png", tamano_bytes=1,
                      creado_en=datetime.utcnow()),
    ])
    db_session.commit()


def _equipo_asignado(db_session):
    n = next(_serie)
    db_session.add(Equipo(sitio_id=1, tipo="activo", categoria="laptop", marca="HP",
                          modelo=f"M{n}", numero_serie=f"S{n}", estado="asignado",
                          asignado_a=_persona(db_session).id))
    db_session.commit()


def _resguardo(db_session):
    n = next(_serie)
    equipo = Equipo(sitio_id=1, tipo="activo", categoria="laptop", marca="HP",
                    modelo=f"R{n}", numero_serie=f"RS{n}", estado="asignado")
    db_session.add(equipo)
    db_session.flush()
    db_session.add(Resguardo(folio=f"RES-QRO-2026-{n:04d}", sitio_id=1,
                             usuario_id=_persona(db_session).id, equipo_id=equipo.id,
                             creado_por=_persona(db_session).id, estado="pendiente_firma",
                             condiciones="Condiciones", creado_en=datetime.utcnow()))
    db_session.commit()


def _persona_con_cosas(db_session):
    persona = _persona(db_session)
    n = next(_serie)
    db_session.add(Equipo(sitio_id=1, tipo="activo", categoria="laptop", marca="HP",
                          modelo=f"P{n}", numero_serie=f"PS{n}", estado="asignado",
                          asignado_a=persona.id))
    db_session.add(Ticket(sitio_id=1, folio=f"TICK-QRO-2026-{n:04d}", usuario_id=persona.id,
                          categoria="red", descripcion_original="x", prioridad="media",
                          estado="abierto", creado_en=datetime.utcnow()))
    db_session.commit()


@pytest.mark.parametrize("ruta,crear", [
    ("/api/tickets", _ticket_completo),
    ("/api/equipos", _equipo_asignado),
    ("/api/resguardos", _resguardo),
    ("/api/admin/usuarios", _persona_con_cosas),
])
def test_el_listado_no_crece_con_los_registros(client, db_session, cab_admin, ruta, crear):
    crear(db_session)
    with contar_consultas(db_session) as con_uno:
        assert client.get(ruta, headers=cab_admin).status_code == 200

    for _ in range(4):
        crear(db_session)
    with contar_consultas(db_session) as con_cinco:
        r = client.get(ruta, headers=cab_admin)
        assert r.status_code == 200

    assert con_cinco["n"] == con_uno["n"], (
        f"{ruta}: {con_uno['n']} consultas con 1 registro y {con_cinco['n']} con 5")


def test_el_dueno_no_ve_las_notas_internas_y_estas_siguen_en_la_base(client, db_session):
    """La relación `comentarios` borra huérfanos. Filtrarla en el objeto del
    ORM —como se hacía— dejaba las notas internas marcadas para borrarse en
    el siguiente commit de esa sesión."""
    _ticket_completo(db_session)
    ticket = db_session.query(Ticket).order_by(Ticket.id.desc()).first()
    duenio = db_session.get(Usuario, ticket.usuario_id)
    r = client.post("/api/auth/login", json={"email": duenio.email, "password": PASSWORD})
    cab = {"Authorization": f"Bearer {r.json()['access_token']}"}

    visto = client.get(f"/api/tickets/{ticket.id}", headers=cab).json()
    assert [c["comentario"] for c in visto["comentarios"]] == ["Reviso"]

    # La sesión de la petición se sigue usando: si el filtro hubiera tocado el
    # ORM, este commit borraría la nota.
    db_session.commit()
    assert db_session.query(TicketComentario).filter_by(ticket_id=ticket.id).count() == 2
