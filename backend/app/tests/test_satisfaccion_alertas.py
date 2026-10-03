"""Encuesta de satisfacción, alertas de TI y el vigilante del SLA."""

from datetime import datetime, timedelta

from app.core.config import settings
from app.models import Alerta, Ticket, Usuario


def _cab(client, email="user@test.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ticket(db, estado="resuelto", canal="tecnico", usuario_id=2, vence_en=None, folio="TICK-QRO-2026-0901"):
    ticket = Ticket(sitio_id=1, usuario_id=usuario_id, folio=folio, categoria="impresora",
                    descripcion_original="No imprime", prioridad="alta", estado=estado,
                    canal_resolucion=canal, vence_en=vence_en,
                    solucion="Se cambió el cabezal térmico de la impresora." if estado == "resuelto" else None,
                    resuelto_en=datetime.utcnow() if estado == "resuelto" else None)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


# ---------------------------------------------------------------------------
# Encuesta
# ---------------------------------------------------------------------------

def test_quien_reporto_califica_una_vez(client, db_session):
    ticket = _ticket(db_session)
    r = client.post(f"/api/tickets/{ticket.id}/satisfaccion", headers=_cab(client),
                    json={"estrellas": 5, "comentario": "  Rápido y amable  "})
    assert r.status_code == 200, r.text
    assert r.json()["satisfaccion"] == 5
    assert r.json()["satisfaccion_comentario"] == "Rápido y amable"

    otra = client.post(f"/api/tickets/{ticket.id}/satisfaccion", headers=_cab(client),
                       json={"estrellas": 1})
    assert otra.status_code == 409
    db_session.refresh(ticket)
    assert ticket.satisfaccion == 5


def test_solo_se_califica_lo_resuelto_por_ti_y_entre_1_y_5(client, db_session):
    abierto = _ticket(db_session, estado="abierto", folio="TICK-QRO-2026-0902")
    autoservicio = _ticket(db_session, canal="checklist", folio="TICK-QRO-2026-0903")
    bueno = _ticket(db_session, folio="TICK-QRO-2026-0904")
    cab = _cab(client)
    assert client.post(f"/api/tickets/{abierto.id}/satisfaccion", headers=cab,
                       json={"estrellas": 4}).status_code == 409
    assert client.post(f"/api/tickets/{autoservicio.id}/satisfaccion", headers=cab,
                       json={"estrellas": 4}).status_code == 409
    for malas in (0, 6, "cinco", None):
        assert client.post(f"/api/tickets/{bueno.id}/satisfaccion", headers=cab,
                           json={"estrellas": malas}).status_code == 422


def test_ni_ti_ni_otra_persona_califican_por_quien_reporto(client, db_session):
    ticket = _ticket(db_session)
    assert client.post(f"/api/tickets/{ticket.id}/satisfaccion", headers=_cab(client, "admin@test.com"),
                       json={"estrellas": 5}).status_code == 403
    ajeno = _ticket(db_session, usuario_id=1, folio="TICK-QRO-2026-0905")
    # Una persona no ve el ticket de otra: 404, no 403.
    assert client.post(f"/api/tickets/{ajeno.id}/satisfaccion", headers=_cab(client),
                       json={"estrellas": 5}).status_code == 404


def test_una_calificacion_baja_abre_una_alerta_para_ti(client, db_session):
    ticket = _ticket(db_session)
    client.post(f"/api/tickets/{ticket.id}/satisfaccion", headers=_cab(client),
                json={"estrellas": settings.SATISFACCION_ALERTA_MAXIMA, "comentario": "Tardaron días"})
    alertas = client.get("/api/admin/alertas", headers=_cab(client, "admin@test.com")).json()
    assert [a["tipo"] for a in alertas] == ["satisfaccion_baja"]
    assert alertas[0]["ticket_id"] == ticket.id
    assert alertas[0]["datos"]["estrellas"] == settings.SATISFACCION_ALERTA_MAXIMA
    assert alertas[0]["detalle"] == "Tardaron días"


def test_las_metricas_cuentan_la_satisfaccion(client, db_session):
    for i, estrellas in enumerate((5, 4, 1)):
        t = _ticket(db_session, folio=f"TICK-QRO-2026-091{i}")
        client.post(f"/api/tickets/{t.id}/satisfaccion", headers=_cab(client), json={"estrellas": estrellas})
    m = client.get("/api/metricas", headers=_cab(client, "admin@test.com")).json()
    sat = m["tickets"]["satisfaccion"] if "tickets" in m else m["satisfaccion"]
    assert sat["respuestas"] == 3
    assert sat["promedio"] == round(10 / 3, 2)
    assert sat["distribucion"]["1"] == 1 and sat["distribucion"]["5"] == 1


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------

def test_las_alertas_son_solo_de_ti(client, db_session):
    assert client.get("/api/admin/alertas", headers=_cab(client)).status_code == 403
    assert client.get("/api/admin/alertas/resumen", headers=_cab(client)).status_code == 403


def test_atender_una_alerta_y_vaciar_la_campana(client, db_session):
    from app.services.alertas_service import AlertasService

    a = AlertasService.abrir(db_session, "sla_vencido", "ticket:1", "uno", sitio_id=1)
    AlertasService.abrir(db_session, "sla_vencido", "ticket:2", "dos", sitio_id=1)
    AlertasService.abrir(db_session, "sla_por_vencer", "ticket:3", "tres", sitio_id=1)
    cab = _cab(client, "admin@test.com")
    assert client.get("/api/admin/alertas/resumen", headers=cab).json() == {
        "pendientes": 3, "por_tipo": {"sla_vencido": 2, "sla_por_vencer": 1}}

    r = client.post(f"/api/admin/alertas/{a.id}/atender", headers=cab)
    assert r.status_code == 200 and r.json()["atendida_en"]
    assert r.json()["atendida_por"] == 1
    r = client.post("/api/admin/alertas/atender-todas?tipo=sla_vencido", headers=cab)
    assert r.json()["atendidas"] == 1
    assert client.get("/api/admin/alertas/resumen", headers=cab).json()["pendientes"] == 1
    assert client.post("/api/admin/alertas/999999/atender", headers=cab).status_code == 404
    assert client.get("/api/admin/alertas?tipo=inventado", headers=cab).status_code == 422


def test_la_misma_alerta_no_se_abre_dos_veces(db_session):
    from app.services.alertas_service import AlertasService

    assert AlertasService.abrir(db_session, "sla_vencido", "ticket:7", "x") is not None
    assert AlertasService.abrir(db_session, "sla_vencido", "ticket:7", "x") is None
    assert db_session.query(Alerta).count() == 1


# ---------------------------------------------------------------------------
# El vigilante del SLA
# ---------------------------------------------------------------------------

def test_el_vigilante_avisa_antes_y_despues_de_vencer_sin_repetir(db_session):
    from app.services.alertas_service import AlertasService

    ahora = datetime.utcnow()
    pronto = _ticket(db_session, estado="abierto", vence_en=ahora + timedelta(minutes=20),
                     folio="TICK-QRO-2026-0921")
    vencido = _ticket(db_session, estado="en_proceso", vence_en=ahora - timedelta(minutes=5),
                      folio="TICK-QRO-2026-0922")
    _ticket(db_session, estado="abierto", vence_en=ahora + timedelta(hours=10),
            folio="TICK-QRO-2026-0923")  # lejos: nada
    _ticket(db_session, estado="espera_proveedor", vence_en=ahora - timedelta(hours=1),
            folio="TICK-QRO-2026-0924")  # en proveedor: no depende de TI

    assert AlertasService.vigilar_sla(db_session, ahora) == {"abiertas": 2, "cerradas": 0}
    # Un minuto después no se repite nada.
    assert AlertasService.vigilar_sla(db_session, ahora + timedelta(minutes=1))["abiertas"] == 0
    tipos = {(a.tipo, a.ticket_id) for a in db_session.query(Alerta).all()}
    assert tipos == {("sla_por_vencer", pronto.id), ("sla_vencido", vencido.id)}

    # Pasa el tiempo: el que estaba por vencer vence, y eso sí es nuevo.
    assert AlertasService.vigilar_sla(db_session, ahora + timedelta(minutes=30))["abiertas"] == 1

    # Se resuelve: sus alertas se cierran solas.
    pronto.estado = "resuelto"
    db_session.commit()
    resultado = AlertasService.vigilar_sla(db_session, ahora + timedelta(minutes=31))
    assert resultado["cerradas"] == 2
