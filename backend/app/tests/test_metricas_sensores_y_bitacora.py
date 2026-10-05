"""Lo que se añadió con la reorganización del menú (2026-10-05).

  * Métricas trae un resumen de los sensores: cuántos reportan ahora y cuántas
    alertas dieron en el periodo, por planta.
  * El centro de alertas pide historia: atendidas, por periodo y por páginas,
    con el nombre de quien la atendió.
  * La bitácora tiene pantalla: filtros que se leen de la tabla y páginas por
    cursor.
"""

from datetime import datetime, timedelta

from app.models import Alerta, Auditoria, DispositivoIoT, Sitio, Usuario


def cab(client, identificador="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sensores(db, otra_planta):
    qro = db.query(Sitio).filter_by(clave="QRO").one()
    ahora = datetime.utcnow()
    db.add_all([
        DispositivoIoT(clave="qro-1", sitio_id=qro.id, activo=True, ultimo_contacto=ahora),
        DispositivoIoT(clave="qro-2", sitio_id=qro.id, activo=True, ultimo_contacto=ahora - timedelta(hours=3)),
        DispositivoIoT(clave="qro-3", sitio_id=qro.id, activo=False, ultimo_contacto=ahora),
        DispositivoIoT(clave="mty-1", sitio_id=otra_planta.id, activo=True, ultimo_contacto=ahora),
    ])
    db.add_all([
        Alerta(tipo="iot_umbral", clave="a", sitio_id=qro.id, titulo="x", creado_en=ahora - timedelta(days=2)),
        Alerta(tipo="iot_sin_senal", clave="b", sitio_id=qro.id, titulo="x", creado_en=ahora - timedelta(days=20),
               atendida_en=ahora),
        Alerta(tipo="iot_umbral", clave="c", sitio_id=otra_planta.id, titulo="x", creado_en=ahora),
        Alerta(tipo="sla_vencido", clave="d", sitio_id=qro.id, titulo="x", creado_en=ahora),
    ])
    db.commit()
    return qro


def test_metricas_traen_el_resumen_de_sensores(client, db_session, otra_planta):
    qro = _sensores(db_session, otra_planta)
    s = client.get("/api/metricas", params={"dias": 7, "sitio_id": qro.id}, headers=cab(client)).json()["sensores"]
    assert s["dispositivos"] == 2            # el inactivo no cuenta
    assert s["en_linea"] == 1                # el de hace tres horas, sin señal
    assert s["alertas_periodo"] == 1         # la de hace 20 días queda fuera de 7
    assert s["alertas_por_tipo"] == {"iot_umbral": 1, "iot_sin_senal": 0}
    assert s["alertas_pendientes"] == 1      # las de SLA no son de sensores
    todas = client.get("/api/metricas", params={"dias": 30}, headers=cab(client)).json()["sensores"]
    assert todas["dispositivos"] == 3 and todas["alertas_periodo"] == 3


def test_historial_de_alertas(client, db_session, otra_planta):
    _sensores(db_session, otra_planta)
    admin = db_session.query(Usuario).filter_by(email="admin@test.com").one()
    alerta = db_session.query(Alerta).filter_by(clave="b").one()
    alerta.atendida_por = admin.id
    db_session.commit()

    atendidas = client.get("/api/admin/alertas", params={"pendientes": False, "atendidas": True},
                           headers=cab(client)).json()
    assert [a["id"] for a in atendidas] == [alerta.id]
    assert atendidas[0]["atendida_por_nombre"] == "Admin Test"

    ultimos_7 = client.get("/api/admin/alertas", params={"pendientes": False, "dias": 7}, headers=cab(client)).json()
    assert alerta.id not in [a["id"] for a in ultimos_7]

    pagina = client.get("/api/admin/alertas", params={"pendientes": False, "limite": 2}, headers=cab(client)).json()
    siguiente = client.get("/api/admin/alertas", params={"pendientes": False, "limite": 2,
                                                         "antes_de": pagina[-1]["id"]}, headers=cab(client)).json()
    ids = [a["id"] for a in pagina + siguiente]
    assert len(ids) == len(set(ids)) == 4
    assert ids == sorted(ids, reverse=True)


def test_bitacora_filtros_y_paginas(client, db_session):
    admin = db_session.query(Usuario).filter_by(email="admin@test.com").one()
    for i in range(5):
        db_session.add(Auditoria(usuario_id=admin.id, accion="regla.creada" if i % 2 else "kb.creada",
                                 entidad="regla" if i % 2 else "kb", entidad_id=i + 1,
                                 creado_en=datetime.utcnow()))
    db_session.commit()

    opciones = client.get("/api/auditoria/opciones", headers=cab(client)).json()
    assert opciones["acciones"] == ["kb.creada", "regla.creada"]
    assert opciones["personas"] == [{"id": admin.id, "nombre": "Admin Test"}]

    primera = client.get("/api/auditoria", params={"limite": 3}, headers=cab(client)).json()
    resto = client.get("/api/auditoria", params={"limite": 3, "antes_de": primera[-1]["id"]},
                       headers=cab(client)).json()
    assert len(primera) == 3 and len(resto) == 2
    assert not {f["id"] for f in primera} & {f["id"] for f in resto}

    solo_kb = client.get("/api/auditoria", params={"accion": "kb.creada", "usuario_id": admin.id},
                         headers=cab(client)).json()
    assert {f["accion"] for f in solo_kb} == {"kb.creada"} and len(solo_kb) == 3


def test_bitacora_solo_ti(client):
    assert client.get("/api/auditoria/opciones", headers=cab(client, "user@test.com")).status_code == 403
