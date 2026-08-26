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
