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


# ----------------------------------------------------------------------
# Renovación de la sesión mientras se trabaja (2026-10-02)
# ----------------------------------------------------------------------

def test_pasada_la_mitad_de_su_vida_el_token_se_renueva(client, db_session):
    """El turno largo se topaba con el login a media tarde, al pulsar Guardar."""
    from datetime import timedelta
    import jwt as pyjwt
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.models import Usuario

    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    viejo = create_access_token(subject=usuario.id, version_token=usuario.version_token,
                                expires_delta=timedelta(minutes=30))
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {viejo}"})
    assert r.status_code == 200
    nuevo = r.headers.get("x-token-renovado")
    assert nuevo and nuevo != viejo

    datos = pyjwt.decode(nuevo, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert datos["sub"] == str(usuario.id)
    assert datos["ver"] == usuario.version_token
    # El nuevo sirve.
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {nuevo}"}).status_code == 200


def test_un_token_reciente_no_se_renueva(client):
    r = client.post("/api/auth/login", json={"email": "user@test.com", "password": "Secret123!"})
    token = r.json()["access_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert "x-token-renovado" not in r.headers


def test_la_renovacion_no_salva_un_token_revocado(client, db_session):
    """El nuevo lleva la misma versión: un cambio de contraseña lo tumba igual."""
    from datetime import timedelta
    from app.core.security import create_access_token
    from app.models import Usuario

    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    viejo = create_access_token(subject=usuario.id, version_token=usuario.version_token,
                                expires_delta=timedelta(minutes=30))
    nuevo = client.get("/api/auth/me", headers={"Authorization": f"Bearer {viejo}"}).headers["x-token-renovado"]
    usuario.version_token = (usuario.version_token or 1) + 1
    db_session.commit()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {nuevo}"}).status_code == 401


def test_la_sesion_no_se_renueva_mas_alla_de_su_vida_maxima(client, db_session):
    """Sin tope, un token copiado vivía para siempre con solo usarlo cada pocas
    horas (auditoría de seguridad, 2026-10-03)."""
    import time
    from datetime import timedelta
    import jwt as pyjwt
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.models import Usuario

    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    hace = time.time() - settings.SESION_MAXIMA_HORAS * 3600 - 60
    viejo = create_access_token(subject=usuario.id, version_token=usuario.version_token,
                                expires_delta=timedelta(minutes=30), inicio=hace)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {viejo}"})
    # Sigue valiendo hasta su vencimiento, pero ya no se renueva.
    assert r.status_code == 200
    assert "x-token-renovado" not in r.headers

    # Una sesión dentro de su vida se renueva, y la renovación conserva la
    # hora de entrada: renovar no reinicia la cuenta.
    entrada = time.time() - 3600
    reciente = create_access_token(subject=usuario.id, version_token=usuario.version_token,
                                   expires_delta=timedelta(minutes=30), inicio=entrada)
    nuevo = client.get("/api/auth/me",
                       headers={"Authorization": f"Bearer {reciente}"}).headers["x-token-renovado"]
    datos = pyjwt.decode(nuevo, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert datos["ini"] == int(entrada)
