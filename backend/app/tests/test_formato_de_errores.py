"""Todo error del API tiene la misma forma: `detail` en texto y un `codigo`.

Ver `app/core/errores.py`. El frontend decide qué enseñar leyendo esos dos
campos, así que una ruta que responda con otra forma es una pantalla que se
queda sin mensaje —o que revienta intentando pintar una lista—.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _cab(client, email="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _tiene_la_forma(cuerpo, codigo):
    assert isinstance(cuerpo["detail"], str) and cuerpo["detail"]
    assert cuerpo["codigo"] == codigo


def test_un_404_propio(client):
    r = client.get("/api/tickets/99999", headers=_cab(client))
    assert r.status_code == 404
    _tiene_la_forma(r.json(), "no_encontrado")


def test_una_ruta_que_no_existe_contesta_en_espanol(client):
    """Starlette pone "Not Found" por su cuenta, sin pasar por el portal."""
    r = client.get("/api/esto-no-existe")
    assert r.status_code == 404
    _tiene_la_forma(r.json(), "no_encontrado")
    assert r.json()["detail"] != "Not Found"


def test_sin_sesion(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    _tiene_la_forma(r.json(), "sesion_invalida")


def test_sin_permiso(client):
    r = client.get("/api/admin/usuarios", headers=_cab(client, "user@test.com"))
    assert r.status_code == 403
    _tiene_la_forma(r.json(), "sin_permiso")


def test_una_validacion_dice_que_campo_y_en_espanol(client):
    r = client.post("/api/admin/usuarios", headers=_cab(client),
                    json={"nombre": "ab", "numero_empleado": "5001"})
    assert r.status_code == 422
    cuerpo = r.json()
    _tiene_la_forma(cuerpo, "validacion")
    assert {"campo": "nombre", "mensaje": "debe tener al menos 3 caracteres"} in cuerpo["errores"]
    assert "nombre" in cuerpo["detail"]


def test_una_validacion_no_devuelve_lo_que_se_mando(client):
    """La respuesta de Pydantic traía `input`: lo enviado, contraseña incluida."""
    r = client.post("/api/auth/activar",
                    json={"identificador": "", "password": "MiSecretoPersonal2026"})
    assert r.status_code == 422
    assert "MiSecretoPersonal2026" not in r.text
    assert all(set(e) == {"campo", "mensaje"} for e in r.json()["errores"])


@pytest.fixture
def ruta_que_falla():
    def revienta():
        raise RuntimeError("fallo de prueba")

    app.add_api_route("/api/_prueba_de_error_interno", revienta)
    yield
    app.router.routes[:] = [r for r in app.router.routes
                            if getattr(r, "path", None) != "/api/_prueba_de_error_interno"]


def test_un_error_no_previsto_es_json_con_referencia(ruta_que_falla):
    """Antes: `Internal Server Error` en texto plano, sin nada que buscar."""
    cliente = TestClient(app, raise_server_exceptions=False)
    r = cliente.get("/api/_prueba_de_error_interno")
    assert r.status_code == 500
    cuerpo = r.json()
    _tiene_la_forma(cuerpo, "error_interno")
    assert len(cuerpo["referencia"]) == 8
    assert cuerpo["referencia"] in cuerpo["detail"]
    assert "fallo de prueba" not in r.text   # el detalle interno no sale
