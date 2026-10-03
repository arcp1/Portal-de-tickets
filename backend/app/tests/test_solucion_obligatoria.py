"""La solución es obligatoria al cerrar un ticket.

Sin este campo no se puede indexar nada en la base de conocimiento, así que la
Fase 2 completa se apoya en esta validación.
"""

import pytest

SOLUCION_VALIDA = "Se reinstaló el driver de la impresora y se reinició el spooler de impresión."


def get_token(client, email="admin@test.com", password="Secret123!"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def crear_ticket(client, headers):
    payload = {
        "sitio_id": 1,
        "categoria": "impresora",
        "descripcion_original": "La impresora de embarques no responde",
        "prioridad": "media",
    }
    response = client.post("/api/tickets", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_no_se_puede_cerrar_sin_solucion(client):
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    ticket_id = crear_ticket(client, headers)

    response = client.patch(f"/api/tickets/{ticket_id}", json={"estado": "cerrado"}, headers=headers)

    assert response.status_code == 422
    assert "solución" in response.json()["detail"].lower()

    # El ticket sigue abierto: el intento fallido no cambió nada.
    actual = client.get(f"/api/tickets/{ticket_id}", headers=headers).json()
    assert actual["estado"] == "abierto"
    assert actual["resuelto_en"] is None


def test_no_se_puede_resolver_sin_solucion(client):
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    ticket_id = crear_ticket(client, headers)

    response = client.patch(f"/api/tickets/{ticket_id}", json={"estado": "resuelto"}, headers=headers)
    assert response.status_code == 422


def test_una_solucion_trivial_no_cuenta(client):
    """'ok' no explica cómo se resolvió: no sirve para la base de conocimiento."""
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    ticket_id = crear_ticket(client, headers)

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"estado": "cerrado", "solucion": "ok"},
        headers=headers,
    )
    assert response.status_code == 422


def test_se_cierra_con_solucion_documentada(client):
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    ticket_id = crear_ticket(client, headers)

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"estado": "cerrado", "solucion": SOLUCION_VALIDA},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["estado"] == "cerrado"
    assert data["solucion"] == SOLUCION_VALIDA
    assert data["resuelto_en"] is not None
    assert data["tiempo_resolucion"] is not None


def test_solucion_documentada_antes_permite_cerrar_despues(client):
    """Se puede documentar la solución primero y cerrar en otra petición."""
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    ticket_id = crear_ticket(client, headers)

    documentar = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"solucion": SOLUCION_VALIDA},
        headers=headers,
    )
    assert documentar.status_code == 200
    assert documentar.json()["estado"] == "abierto"

    cerrar = client.patch(f"/api/tickets/{ticket_id}", json={"estado": "cerrado"}, headers=headers)
    assert cerrar.status_code == 200
    assert cerrar.json()["estado"] == "cerrado"


def test_estados_intermedios_no_exigen_solucion(client):
    """Pasar a en_proceso o espera_proveedor no requiere documentar nada."""
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    ticket_id = crear_ticket(client, headers)

    for estado in ("en_proceso", "espera_proveedor"):
        response = client.patch(
            f"/api/tickets/{ticket_id}", json={"estado": estado}, headers=headers
        )
        assert response.status_code == 200, estado
        assert response.json()["estado"] == estado


# ----------------------------------------------------------------------
# Quién puede cerrar
#
# Cerrar es una acción del equipo de TI. La solución que se escribe al cerrar
# no se queda en el ticket: se indexa en la base de conocimiento y se le sugiere
# al resto de la planta, así que la escribe quien resolvió la incidencia y no
# quien la reportó. El frontend ya lo asume —el selector de estado de
# TicketDetail.jsx solo se renderiza para admin—; esto lo hace valer también
# contra la API directa.
# ----------------------------------------------------------------------

def headers_de(client, email):
    return {"Authorization": f"Bearer {get_token(client, email=email)}"}


def test_el_usuario_no_puede_cerrar_su_propio_ticket(client):
    headers = headers_de(client, "user@test.com")
    ticket_id = crear_ticket(client, headers)

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"estado": "cerrado", "solucion": SOLUCION_VALIDA},
        headers=headers,
    )

    assert response.status_code == 403
    assert "equipo de TI" in response.json()["detail"]

    # Ni el estado ni la solución se movieron, y no se sembró nada en la KB.
    actual = client.get(f"/api/tickets/{ticket_id}", headers=headers).json()
    assert actual["estado"] == "abierto"
    assert actual["solucion"] is None
    assert actual["resuelto_en"] is None
    assert actual["indexado_kb"] is False


def test_el_usuario_no_puede_resolver_su_propio_ticket(client):
    headers = headers_de(client, "user@test.com")
    ticket_id = crear_ticket(client, headers)

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"estado": "resuelto", "solucion": SOLUCION_VALIDA},
        headers=headers,
    )
    assert response.status_code == 403


def test_el_usuario_no_puede_escribir_la_solucion(client):
    """Ni aunque no toque el estado: ese campo es lo que alimenta la KB."""
    headers = headers_de(client, "user@test.com")
    ticket_id = crear_ticket(client, headers)

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"solucion": SOLUCION_VALIDA},
        headers=headers,
    )

    assert response.status_code == 403
    assert client.get(f"/api/tickets/{ticket_id}", headers=headers).json()["solucion"] is None


def test_al_usuario_se_le_niega_el_cierre_antes_de_pedirle_la_solucion(client):
    """403 y no 422: a quien no puede cerrar no se le pide que documente."""
    headers = headers_de(client, "user@test.com")
    ticket_id = crear_ticket(client, headers)

    response = client.patch(f"/api/tickets/{ticket_id}", json={"estado": "cerrado"}, headers=headers)
    assert response.status_code == 403


def test_el_dueno_no_cambia_la_prioridad(client):
    """Regla de negocio desde 2026-09-30: la prioridad la decide Soporte.

    Antes esta prueba fijaba lo contrario —"la restricción es sobre el cierre,
    no sobre el ticket entero"— y el dueño podía subir la suya a crítica."""
    headers = headers_de(client, "user@test.com")
    ticket_id = crear_ticket(client, headers)

    response = client.patch(f"/api/tickets/{ticket_id}", json={"prioridad": "critica"}, headers=headers)

    assert response.status_code == 403
    assert "comentario" in response.json()["detail"]
    assert client.get(f"/api/tickets/{ticket_id}", headers=headers).json()["prioridad"] == "media"


@pytest.mark.parametrize("estado", ["en_proceso", "espera_proveedor", "abierto"])
def test_el_dueno_no_mueve_su_ticket_de_estado(client, estado):
    """Tampoco a los intermedios: "en proceso" dice que alguien de TI lo está
    atendiendo, y eso solo lo puede decir TI."""
    headers = headers_de(client, "user@test.com")
    ticket_id = crear_ticket(client, headers)

    response = client.patch(f"/api/tickets/{ticket_id}", json={"estado": estado}, headers=headers)

    assert response.status_code == 403


def test_el_dueno_sigue_comentando(client):
    """Lo que sí conserva: seguir su ticket y añadir lo que sepa."""
    headers = headers_de(client, "user@test.com")
    ticket_id = crear_ticket(client, headers)

    response = client.post(f"/api/tickets/{ticket_id}/comments",
                           json={"comentario": "Sigue fallando después de reiniciar."}, headers=headers)

    assert response.status_code == 201


def test_el_admin_cierra_el_ticket_de_otro(client):
    """El flujo normal: el usuario reporta, TI resuelve y documenta."""
    ticket_id = crear_ticket(client, headers_de(client, "user@test.com"))

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"estado": "cerrado", "solucion": SOLUCION_VALIDA},
        headers=headers_de(client, "admin@test.com"),
    )

    assert response.status_code == 200
    assert response.json()["estado"] == "cerrado"
    assert response.json()["solucion"] == SOLUCION_VALIDA
