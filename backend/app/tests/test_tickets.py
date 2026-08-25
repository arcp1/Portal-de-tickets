def get_user_token(client, email="user@test.com", password="Secret123!"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]

def test_create_ticket(client):
    token = get_user_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "sitio_id": 1,
        "categoria": "red",
        "descripcion_original": "Falla de señal wifi en estación de trabajo 4",
        "prioridad": "media"
    }
    
    response = client.post("/api/tickets", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["folio"].startswith("TICK-QRO-")
    assert data["categoria"] == "red"
    assert data["estado"] == "abierto"
