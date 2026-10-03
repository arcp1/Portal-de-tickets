from app.tests.test_tickets import get_user_token

def test_get_equipos(client):
    token = get_user_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/equipos", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_create_regla(client):
    token = get_user_token(client, email="admin@test.com", password="Secret123!")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "sitio_id": 1,
        "categoria": "impresora",
        "condicion": "hardware",
        "accion": "proveedor",
        "destinatario": "soporte@hp.com",
        "activa": True
    }
    response = client.post("/api/reglas", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["categoria"] == "impresora"
    assert data["condicion"] == "hardware"

def test_get_checklists(client):
    token = get_user_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/checklists?categoria=impresora", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ----------------------------------------------------------------------
# El rol de admin no cruza de planta
# ----------------------------------------------------------------------

def _cab_admin(client):
    token = get_user_token(client, email="admin@test.com", password="Secret123!")
    return {"Authorization": f"Bearer {token}"}



def test_una_regla_exige_una_planta_que_exista(client, db_session, otra_planta):
    """TI es global: escribe la regla en la planta que diga, si existe.

    Un número inventado se guardaba y la regla no casaba con nada; con varias
    plantas y sin decir cuál, se pide en vez de adivinar.
    """
    base = {"categoria": "red", "condicion": "wifi", "accion": "escalar", "activa": True}
    cab = _cab_admin(client)
    assert client.post("/api/reglas", headers=cab, json={**base, "sitio_id": 999}).status_code == 422
    assert client.post("/api/reglas", headers=cab, json=base).status_code == 422

    r = client.post("/api/reglas", headers=cab, json={**base, "sitio_id": otra_planta.id})
    assert r.status_code == 201, r.text
    assert r.json()["sitio_id"] == otra_planta.id



def test_ti_borra_reglas_de_cualquier_planta_y_nadie_mas(client, db_session, otra_planta):
    from app.models import ReglaNegocio

    regla = ReglaNegocio(sitio_id=otra_planta.id, categoria="impresora", condicion="x",
                         accion="escalar", activa=True)
    db_session.add(regla)
    db_session.commit()
    db_session.refresh(regla)

    persona = {"Authorization": f"Bearer {get_user_token(client)}"}
    assert client.delete(f"/api/reglas/{regla.id}", headers=persona).status_code == 403
    assert client.delete(f"/api/reglas/{regla.id}", headers=_cab_admin(client)).status_code == 204
    assert db_session.query(ReglaNegocio).filter_by(id=regla.id).first() is None



def test_indexar_un_ticket_es_solo_de_ti(client, db_session, otra_planta):
    """El conocimiento se comparte entre plantas y lo cura TI, que es global.

    Una persona de planta no indexa nada, ni de la suya.
    """
    from app.models import Ticket

    ticket = Ticket(sitio_id=otra_planta.id, usuario_id=2, folio="TICK-MTY-2026-0001",
                    descripcion_original="la impresora de la otra planta falla",
                    categoria="impresora", estado="resuelto",
                    solucion="Se limpió el cabezal con alcohol y quedó bien.")
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)

    persona = {"Authorization": f"Bearer {get_user_token(client)}"}
    assert client.post(f"/api/kb/indexar/{ticket.id}", headers=persona).status_code == 403
    r = client.post(f"/api/kb/indexar/{ticket.id}", headers=_cab_admin(client))
    assert r.status_code == 200, r.text


