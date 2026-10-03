"""El botón de '¿te sirvió?' y la tasa de utilidad que calibra el umbral.

Sin este registro no hay forma de saber si las sugerencias sirven, y el umbral
de similitud se queda a ciegas.
"""

import pytest

from app.models import BaseConocimiento, SugerenciaKB, Usuario


def get_token(client, email="admin@test.com", password="Secret123!"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


@pytest.fixture
def sugerencia(db_session):
    """Una entrada de base de conocimiento ya mostrada una vez al usuario.

    La fila lleva `usuario_id` porque en produccion siempre lo lleva: la crea
    `KBService.buscar_similares` a nombre de quien recibio la sugerencia. Sin
    ese dato no se puede comprobar que quien vota sea quien la recibio, y el
    voto de cualquiera contaria para calibrar el umbral de toda la planta.
    """
    entrada = BaseConocimiento(
        sitio_id=1,
        titulo="Impresora de embarques no responde",
        contenido="impresora\nNo imprime\nSe reinstaló el driver y se reinició el spooler.",
        categoria="impresora",
        veces_sugerida=1,
        veces_util=0,
    )
    db_session.add(entrada)
    db_session.commit()
    db_session.refresh(entrada)

    duenio = db_session.query(Usuario).filter(Usuario.email == "admin@test.com").first()
    fila = SugerenciaKB(kb_id=entrada.id, usuario_id=duenio.id,
                        similitud=0.88, fue_util=None)
    db_session.add(fila)
    db_session.commit()
    db_session.refresh(fila)

    return {"entrada": entrada, "sugerencia": fila}


def test_marcar_sugerencia_como_util(client, db_session, sugerencia):
    headers = {"Authorization": f"Bearer {get_token(client)}"}

    response = client.post(
        "/api/kb/feedback",
        json={"sugerencia_id": sugerencia["sugerencia"].id, "fue_util": True},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["fue_util"] is True

    db_session.refresh(sugerencia["entrada"])
    assert sugerencia["entrada"].veces_util == 1


def test_marcar_sugerencia_como_no_util(client, db_session, sugerencia):
    headers = {"Authorization": f"Bearer {get_token(client)}"}

    response = client.post(
        "/api/kb/feedback",
        json={"sugerencia_id": sugerencia["sugerencia"].id, "fue_util": False},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["fue_util"] is False

    db_session.refresh(sugerencia["entrada"])
    # Se registra la respuesta, pero no cuenta como útil.
    assert sugerencia["entrada"].veces_util == 0
    db_session.refresh(sugerencia["sugerencia"])
    assert sugerencia["sugerencia"].fue_util is False


def test_cambiar_de_opinion_no_duplica_el_conteo(client, db_session, sugerencia):
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    payload = {"sugerencia_id": sugerencia["sugerencia"].id, "fue_util": True}

    client.post("/api/kb/feedback", json=payload, headers=headers)
    client.post("/api/kb/feedback", json=payload, headers=headers)

    db_session.refresh(sugerencia["entrada"])
    assert sugerencia["entrada"].veces_util == 1

    # Y al revertir, el contador baja.
    client.post(
        "/api/kb/feedback",
        json={"sugerencia_id": sugerencia["sugerencia"].id, "fue_util": False},
        headers=headers,
    )
    db_session.refresh(sugerencia["entrada"])
    assert sugerencia["entrada"].veces_util == 0


def test_feedback_de_sugerencia_inexistente(client):
    headers = {"Authorization": f"Bearer {get_token(client)}"}

    response = client.post(
        "/api/kb/feedback",
        json={"sugerencia_id": 99999, "fue_util": True},
        headers=headers,
    )
    assert response.status_code == 404


def test_tasa_de_utilidad_en_metricas(client, db_session, sugerencia):
    headers = {"Authorization": f"Bearer {get_token(client)}"}

    antes = client.get("/api/kb/metricas", headers=headers).json()
    assert antes["sugerencias_mostradas"] == 1
    assert antes["sugerencias_utiles"] == 0
    assert antes["tasa_utilidad"] == 0.0
    assert antes["sugerencias_respondidas"] == 0

    client.post(
        "/api/kb/feedback",
        json={"sugerencia_id": sugerencia["sugerencia"].id, "fue_util": True},
        headers=headers,
    )

    despues = client.get("/api/kb/metricas", headers=headers).json()
    assert despues["sugerencias_utiles"] == 1
    assert despues["tasa_utilidad"] == 1.0
    assert despues["sugerencias_respondidas"] == 1


def test_tasa_de_utilidad_sin_sugerencias_es_nula(client):
    """Sin sugerencias mostradas la tasa no existe todavía: None, no 0."""
    headers = {"Authorization": f"Bearer {get_token(client)}"}

    metricas = client.get("/api/kb/metricas", headers=headers).json()
    assert metricas["sugerencias_mostradas"] == 0
    assert metricas["tasa_utilidad"] is None


def test_metricas_solo_para_admin(client):
    headers = {"Authorization": f"Bearer {get_token(client, email='user@test.com')}"}
    assert client.get("/api/kb/metricas", headers=headers).status_code == 403
