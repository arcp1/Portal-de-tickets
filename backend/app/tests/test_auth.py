def test_login_success(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "Secret123!"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "admin@test.com"

def test_login_invalid_password(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "WrongPassword"}
    )
    assert response.status_code == 401
