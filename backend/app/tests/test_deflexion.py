"""Auto-resolución y tasa de deflexión.

Una incidencia que el usuario resolvió solo —con el checklist o con una
sugerencia de la base de conocimiento— tiene que dejar rastro. Sin ese
registro la tasa de deflexión, que es el argumento entero del sistema, no se
puede calcular.
"""

import pytest

from app.models import Ticket

SOLUCION = "La impresora estaba apagada; se encendió y volvió a imprimir sin más ajustes."


def get_token(client, email="user@test.com", password="Secret123!"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def headers(client, email="user@test.com"):
    return {"Authorization": f"Bearer {get_token(client, email=email)}"}


def crear(client, cabeceras, **extra):
    payload = {
        "sitio_id": 1,
        "categoria": "impresora",
        "descripcion_original": "La impresora de embarques no imprimía",
        "prioridad": "baja",
    }
    payload.update(extra)
    return client.post("/api/tickets", json=payload, headers=cabeceras)


@pytest.mark.parametrize("canal", ["checklist", "kb"])
def test_auto_resolucion_queda_registrada(client, canal):
    respuesta = crear(client, headers(client), canal_auto_resolucion=canal, solucion=SOLUCION)

    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["estado"] == "resuelto"
    assert datos["canal_resolucion"] == canal
    assert datos["solucion"] == SOLUCION
    assert datos["resuelto_en"] is not None
    # No se indexa: el checklist ya existe y la sugerencia de KB ya está indexada.
    assert datos["indexado_kb"] is False


def test_no_se_puede_falsear_el_canal(client):
    """Un usuario no puede declarar que lo resolvió un técnico o un proveedor."""
    for canal in ("tecnico", "proveedor", "ia"):
        respuesta = crear(client, headers(client), canal_auto_resolucion=canal, solucion=SOLUCION)
        assert respuesta.status_code == 422, canal


def test_una_auto_resolucion_sin_explicacion_se_rechaza(client):
    """Mismo criterio que al cerrar: sin explicación no sirve de nada."""
    respuesta = crear(client, headers(client), canal_auto_resolucion="checklist", solucion="ok")
    assert respuesta.status_code == 422


def test_un_ticket_normal_no_se_marca_resuelto(client):
    """Sin canal de auto-resolución, el flujo de siempre no cambia."""
    respuesta = crear(client, headers(client))

    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "abierto"
    assert respuesta.json()["solucion"] is None


def test_la_tasa_de_deflexion_cuenta_las_auto_resoluciones(client, db_session):
    cabeceras = headers(client)
    admin = headers(client, "admin@test.com")

    # Dos deflectadas y una que necesita técnico.
    crear(client, cabeceras, canal_auto_resolucion="checklist", solucion=SOLUCION)
    crear(client, cabeceras, canal_auto_resolucion="kb", solucion=SOLUCION)
    crear(client, cabeceras, categoria="software")

    metricas = client.get("/api/metricas", headers=admin).json()["tickets"]

    assert metricas["tickets_total"] == 3
    assert metricas["tickets_deflectados"] == 2
    assert metricas["tasa_deflexion"] == pytest.approx(66.7, abs=0.1)
    assert metricas["por_canal"]["checklist"] == 1
    assert metricas["por_canal"]["kb"] == 1


def test_sin_tickets_la_tasa_es_nula_y_no_cero(client):
    """None y no 0: un cero falso se lee como mal resultado."""
    metricas = client.get("/api/metricas", headers=headers(client, "admin@test.com")).json()

    assert metricas["tickets"]["tickets_total"] == 0
    assert metricas["tickets"]["tasa_deflexion"] is None


def test_las_metricas_son_solo_del_admin(client):
    assert client.get("/api/metricas", headers=headers(client)).status_code == 403


def test_la_sesion_de_chat_se_enlaza_al_ticket(client, db_session, monkeypatch):
    """Sin ese enlace no se puede medir la precisión del clasificador."""
    from app.core.config import settings
    from app.services.ollama_client import ollama

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(ollama, "disponible", lambda: True)
    monkeypatch.setattr(ollama, "clasificar_categoria",
                        lambda texto: {"categoria": "impresora", "confianza": 0.95})

    cabeceras = headers(client)
    chat = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "la etiquetadora de embarques no saca etiquetas"},
        headers=cabeceras,
    ).json()

    ticket = crear(client, cabeceras, chat_sesion_id=chat["sesion_id"]).json()

    metricas = client.get("/api/metricas", headers=headers(client, "admin@test.com")).json()["chatbot"]
    assert metricas["sesiones_con_ticket"] == 1
    assert metricas["clasificaciones_comparables"] == 1
    # Detectó "impresora" y el ticket quedó en "impresora": acierto.
    assert metricas["precision_clasificacion"] == 100.0
    assert db_session.query(Ticket).filter(Ticket.id == ticket["id"]).first() is not None


def test_no_se_enlaza_la_sesion_de_otro_usuario(client, monkeypatch):
    from app.core.config import settings
    from app.services.ollama_client import ollama

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(ollama, "disponible", lambda: True)
    monkeypatch.setattr(ollama, "clasificar_categoria", lambda texto: None)

    ajena = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "algo que escribio alguien mas en su sesion"},
        headers=headers(client, "admin@test.com"),
    ).json()["sesion_id"]

    crear(client, headers(client), chat_sesion_id=ajena)

    metricas = client.get("/api/metricas", headers=headers(client, "admin@test.com")).json()["chatbot"]
    assert metricas["sesiones_con_ticket"] == 0
