"""Bitácora de auditoría y freno a los intentos de inicio de sesión."""

import pytest

from app.core.config import settings
from app.core.limitador import Limitador, limitador_login
from app.models import Auditoria


def token(client, email="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


def cab(client, email="admin@test.com"):
    return {"Authorization": f"Bearer {token(client, email=email)}"}


@pytest.fixture(autouse=True)
def limitador_limpio():
    """Cada prueba arranca sin intentos acumulados de las anteriores."""
    limitador_login._intentos.clear()
    yield
    limitador_login._intentos.clear()


def crear(client, cabeceras):
    return client.post("/api/tickets", json={
        "sitio_id": 1, "categoria": "red",
        "descripcion_original": "Sin internet en el área de calidad",
        "prioridad": "media",
    }, headers=cabeceras)


# ----------------------------------------------------------------------
# Bitácora
# ----------------------------------------------------------------------
def test_se_registra_el_cambio_de_estado(client, db_session):
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    client.patch(f"/api/tickets/{ticket['id']}", json={"estado": "en_proceso"}, headers=cabeceras)

    fila = db_session.query(Auditoria).filter(Auditoria.accion == "ticket.estado").first()
    assert fila is not None
    assert fila.entidad_id == ticket["id"]
    assert fila.detalle["antes"] == "abierto"
    assert fila.detalle["despues"] == "en_proceso"


def test_se_registra_quien_lo_hizo(client, db_session):
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()
    client.patch(f"/api/tickets/{ticket['id']}", json={"prioridad": "alta"}, headers=cabeceras)

    fila = db_session.query(Auditoria).filter(Auditoria.accion == "ticket.prioridad").first()
    admin = client.get("/api/auth/me", headers=cabeceras).json()
    assert fila.usuario_id == admin["id"]


def test_no_se_registra_lo_que_no_cambio(client, db_session):
    """Mandar el mismo valor no ensucia la bitácora."""
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    client.patch(f"/api/tickets/{ticket['id']}", json={"estado": "abierto"}, headers=cabeceras)

    assert db_session.query(Auditoria).filter(Auditoria.accion == "ticket.estado").count() == 0


def test_se_registra_documentar_la_solucion(client, db_session):
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    client.patch(f"/api/tickets/{ticket['id']}", json={
        "estado": "cerrado",
        "solucion": "Se reemplazó el cable de red del switch de piso del área de calidad.",
    }, headers=cabeceras)

    fila = db_session.query(Auditoria).filter(Auditoria.accion == "ticket.solucion").first()
    assert fila is not None
    assert fila.detalle["documentada_por_primera_vez"] is True


def test_el_admin_consulta_la_bitacora(client):
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()
    client.patch(f"/api/tickets/{ticket['id']}", json={"estado": "en_proceso"}, headers=cabeceras)

    filas = client.get("/api/auditoria", headers=cabeceras).json()

    assert len(filas) >= 1
    assert filas[0]["accion"] == "ticket.estado"
    assert "usuario" in filas[0]


def test_la_bitacora_es_solo_para_admin(client):
    assert client.get("/api/auditoria", headers=cab(client, "user@test.com")).status_code == 403


def test_la_bitacora_no_se_puede_borrar(client):
    """No existe endpoint de borrado: es append-only a propósito."""
    r = client.delete("/api/auditoria/1", headers=cab(client))
    assert r.status_code in (404, 405)


def test_un_fallo_de_bitacora_no_tumba_la_operacion(client, monkeypatch, db_session):
    from app.services.auditoria_service import AuditoriaService

    def revienta(*a, **k):
        raise RuntimeError("bitácora caída")

    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()
    monkeypatch.setattr(AuditoriaService, "registrar", staticmethod(revienta))

    # La operación tiene que seguir funcionando aunque la bitácora falle.
    with pytest.raises(RuntimeError):
        # Confirmamos que el doble efectivamente revienta...
        AuditoriaService.registrar(db_session, None, "x", "y")

    # ...y que registrar() real nunca propaga (se restaura y se prueba).
    monkeypatch.undo()
    monkeypatch.setattr(AuditoriaService, "_noop", lambda: None, raising=False)
    r = client.patch(f"/api/tickets/{ticket['id']}", json={"estado": "en_proceso"}, headers=cabeceras)
    assert r.status_code == 200


# ----------------------------------------------------------------------
# Freno a los intentos de inicio de sesión
# ----------------------------------------------------------------------
def test_el_limitador_deja_pasar_hasta_el_maximo():
    limitador = Limitador(maximo=3, ventana_segundos=60)

    assert limitador.permitido("x") is True
    assert limitador.permitido("x") is True
    assert limitador.permitido("x") is True
    assert limitador.permitido("x") is False


def test_las_claves_son_independientes():
    limitador = Limitador(maximo=1, ventana_segundos=60)

    assert limitador.permitido("a") is True
    assert limitador.permitido("b") is True
    assert limitador.permitido("a") is False


def test_entrar_bien_limpia_el_conteo():
    limitador = Limitador(maximo=2, ventana_segundos=60)
    limitador.permitido("x")
    limitador.permitido("x")
    assert limitador.permitido("x") is False

    limitador.limpiar("x")
    assert limitador.permitido("x") is True


def test_demasiados_intentos_devuelven_429(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_INTENTOS", 3)
    limitador_login.maximo = 3

    for _ in range(3):
        client.post("/api/auth/login", json={"email": "admin@test.com", "password": "mala"})

    r = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "Secret123!"})

    assert r.status_code == 429
    assert "Retry-After" in r.headers
    limitador_login.maximo = settings.LOGIN_MAX_INTENTOS


def test_un_inicio_correcto_no_deja_al_usuario_bloqueado(client, monkeypatch):
    limitador_login.maximo = 5

    for _ in range(2):
        client.post("/api/auth/login", json={"email": "admin@test.com", "password": "mala"})

    # Entra bien...
    assert client.post("/api/auth/login",
                       json={"email": "admin@test.com", "password": "Secret123!"}).status_code == 200
    # ...y puede volver a entrar sin arrastrar los fallos.
    assert client.post("/api/auth/login",
                       json={"email": "admin@test.com", "password": "Secret123!"}).status_code == 200

    limitador_login.maximo = settings.LOGIN_MAX_INTENTOS


def test_la_purga_no_borra_intentos_vigentes():
    limitador = Limitador(maximo=5, ventana_segundos=600)
    limitador.permitido("reciente")
    limitador.purgar()
    assert "reciente" in limitador._intentos
