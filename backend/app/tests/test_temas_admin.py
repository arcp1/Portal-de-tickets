"""Administración de temas: pasos de checklist y base de conocimiento.

Lo que el admin tiene que poder hacer sin tocar la base de datos.
"""

import pytest

from app.models import Checklist


def token(client, email="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


def cab(client, email="admin@test.com"):
    return {"Authorization": f"Bearer {token(client, email=email)}"}


PASO = {
    "categoria": "equipo",
    "pregunta_texto": "¿El cable de video está bien puesto en los dos extremos?",
    "accion_si_no": "Desconéctelo y vuelva a conectarlo firmemente.",
    "resuelve": True,
}


# ----------------------------------------------------------------------
# Pasos de checklist
# ----------------------------------------------------------------------
def test_el_admin_crea_un_paso(client):
    r = client.post("/api/admin/pasos", json=PASO, headers=cab(client))

    assert r.status_code == 201
    datos = r.json()
    assert datos["pregunta_texto"] == PASO["pregunta_texto"]
    assert datos["resuelve"] is True
    assert datos["activo"] is True


def test_el_paso_nuevo_le_aparece_al_usuario(client):
    """De nada sirve crearlo si no llega al flujo del usuario."""
    client.post("/api/admin/pasos", json=PASO, headers=cab(client))

    pasos = client.get("/api/checklists?categoria=equipo", headers=cab(client, "user@test.com")).json()
    assert any(p["pregunta_texto"] == PASO["pregunta_texto"] for p in pasos)


def test_el_admin_edita_un_paso(client):
    creado = client.post("/api/admin/pasos", json=PASO, headers=cab(client)).json()

    r = client.patch(
        f"/api/admin/pasos/{creado['id']}",
        json={"pregunta_texto": "Texto corregido", "resuelve": False},
        headers=cab(client),
    )

    assert r.status_code == 200
    assert r.json()["pregunta_texto"] == "Texto corregido"
    assert r.json()["resuelve"] is False


def test_dar_de_baja_lo_oculta_pero_conserva_el_historial(client, db_session):
    creado = client.post("/api/admin/pasos", json=PASO, headers=cab(client)).json()

    assert client.delete(f"/api/admin/pasos/{creado['id']}", headers=cab(client)).status_code == 204

    # Ya no se le muestra al usuario...
    pasos = client.get("/api/checklists?categoria=equipo", headers=cab(client, "user@test.com")).json()
    assert all(p["id"] != creado["id"] for p in pasos)
    # ...pero la fila sigue ahí con su historial.
    assert db_session.query(Checklist).filter(Checklist.id == creado["id"]).first() is not None


def test_se_puede_reactivar_un_paso(client):
    creado = client.post("/api/admin/pasos", json=PASO, headers=cab(client)).json()
    client.delete(f"/api/admin/pasos/{creado['id']}", headers=cab(client))

    r = client.patch(f"/api/admin/pasos/{creado['id']}", json={"activo": True}, headers=cab(client))
    assert r.json()["activo"] is True

    pasos = client.get("/api/checklists?categoria=equipo", headers=cab(client, "user@test.com")).json()
    assert any(p["id"] == creado["id"] for p in pasos)


def test_no_se_acepta_una_categoria_inventada(client):
    malo = {**PASO, "categoria": "cafetera"}
    assert client.post("/api/admin/pasos", json=malo, headers=cab(client)).status_code == 422


def test_un_usuario_normal_no_administra_pasos(client):
    usuario = cab(client, "user@test.com")
    assert client.post("/api/admin/pasos", json=PASO, headers=usuario).status_code == 403
    assert client.get("/api/admin/pasos", headers=usuario).status_code == 403


def test_el_orden_se_asigna_solo(client):
    primero = client.post("/api/admin/pasos", json=PASO, headers=cab(client)).json()
    segundo = client.post("/api/admin/pasos", json={**PASO, "pregunta_texto": "Otra pregunta más"},
                          headers=cab(client)).json()
    assert segundo["orden"] == primero["orden"] + 1


# ----------------------------------------------------------------------
# Base de conocimiento
# ----------------------------------------------------------------------
ENTRADA = {
    "titulo": "Monitor sin imagen",
    "contenido": "Revisar que el cable de video esté firme en los dos extremos antes de cualquier otra cosa.",
    "categoria": "equipo",
}


def test_el_admin_crea_conocimiento_a_mano(client):
    """Sin esperar a que ocurra un ticket."""
    r = client.post("/api/admin/kb", json=ENTRADA, headers=cab(client))

    assert r.status_code == 201
    assert r.json()["titulo"] == ENTRADA["titulo"]
    # La suite corre sin IA, así que queda sin vector y pendiente de indexar.
    assert r.json()["tiene_embedding"] is False


def test_el_admin_edita_y_borra_conocimiento(client):
    creada = client.post("/api/admin/kb", json=ENTRADA, headers=cab(client)).json()

    r = client.patch(f"/api/admin/kb/{creada['id']}", json={"titulo": "Título nuevo"}, headers=cab(client))
    assert r.status_code == 200
    assert r.json()["titulo"] == "Título nuevo"

    assert client.delete(f"/api/admin/kb/{creada['id']}", headers=cab(client)).status_code == 204
    assert client.get("/api/admin/kb", headers=cab(client)).json() == []


def test_una_entrada_sin_contenido_util_se_rechaza(client):
    corta = {**ENTRADA, "contenido": "poco"}
    assert client.post("/api/admin/kb", json=corta, headers=cab(client)).status_code == 422


def test_un_usuario_normal_no_administra_conocimiento(client):
    assert client.post("/api/admin/kb", json=ENTRADA, headers=cab(client, "user@test.com")).status_code == 403


def test_la_tasa_de_utilidad_es_nula_sin_datos(client):
    """None y no 0: nunca se ha mostrado, no es que no sirva."""
    creada = client.post("/api/admin/kb", json=ENTRADA, headers=cab(client)).json()
    assert creada["tasa_utilidad"] is None


# ----------------------------------------------------------------------
# Temas detectados
# ----------------------------------------------------------------------
def test_sin_ia_no_se_detectan_temas(client):
    """La suite corre con IA apagada: no se agrupa nada y nada se rompe."""
    client.post("/api/tickets", json={
        "sitio_id": 1, "categoria": "otro",
        "descripcion_original": "El lector de gafetes del almacén no abre la puerta",
        "prioridad": "media",
    }, headers=cab(client, "user@test.com"))

    assert client.get("/api/admin/temas-sugeridos", headers=cab(client)).json() == []


def test_promover_un_tema_inexistente(client):
    r = client.post("/api/admin/temas-sugeridos/9999/promover",
                    json={"categoria": "otro", "pasos": []}, headers=cab(client))
    assert r.status_code == 404


def test_un_usuario_normal_no_ve_los_temas_detectados(client):
    assert client.get("/api/admin/temas-sugeridos", headers=cab(client, "user@test.com")).status_code == 403
