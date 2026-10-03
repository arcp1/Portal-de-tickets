"""Avisos por correo.

Dos garantías: sin SMTP configurado no hace nada, y un fallo de correo nunca
tumba la operación que lo originó.
"""


from app.core.config import settings
from app.services.notificaciones_service import NotificacionesService


def token(client, email="user@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


def cab(client, email="user@test.com"):
    return {"Authorization": f"Bearer {token(client, email=email)}"}


def crear(client, cabeceras, **extra):
    payload = {
        "sitio_id": 1, "categoria": "red",
        "descripcion_original": "Sin internet en el área de calidad",
        "prioridad": "alta",
    }
    payload.update(extra)
    return client.post("/api/tickets", json=payload, headers=cabeceras)


def test_sin_smtp_el_servicio_esta_inactivo(monkeypatch):
    """Sin configurar no intenta nada ni ensucia los logs."""
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert NotificacionesService.activo() is False


def test_se_puede_apagar_aun_con_smtp(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.cgr.local")
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", False)
    assert NotificacionesService.activo() is False


def test_un_smtp_caido_no_impide_crear_el_ticket(client, monkeypatch):
    """La garantía importante: el correo es accesorio, el ticket no."""
    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_PUERTO", 1)  # puerto cerrado
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", True)

    r = crear(client, cab(client))

    assert r.status_code == 201
    assert r.json()["folio"].startswith("TICK-QRO-")


def test_un_smtp_caido_no_impide_cerrar_el_ticket(client, monkeypatch):
    cabeceras_admin = cab(client, "admin@test.com")
    ticket = crear(client, cab(client)).json()

    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_PUERTO", 1)
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", True)

    r = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"estado": "cerrado",
              "solucion": "Se reemplazó el cable de red del switch de piso del área."},
        headers=cabeceras_admin,
    )

    assert r.status_code == 200
    assert r.json()["estado"] == "cerrado"


def test_un_smtp_caido_no_impide_comentar(client, monkeypatch):
    ticket = crear(client, cab(client)).json()

    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_PUERTO", 1)
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", True)

    r = client.post(
        f"/api/tickets/{ticket['id']}/comments",
        json={"comentario": "Ya vamos para allá"},
        headers=cab(client, "admin@test.com"),
    )

    assert r.status_code == 201


def test_el_envio_devuelve_false_en_lugar_de_reventar(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_PUERTO", 1)
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", True)

    assert NotificacionesService._enviar("alguien@cgr.mx", "Prueba", "Cuerpo") is False


def test_no_se_avisa_de_las_notas_internas(client, db_session, monkeypatch):
    """Una nota interna es para el equipo de TI, no para quien reportó."""
    enviados = []
    monkeypatch.setattr(NotificacionesService, "_enviar",
                        staticmethod(lambda d, a, c: enviados.append(a) or True))
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.cgr.local")
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", True)

    ticket = crear(client, cab(client)).json()
    enviados.clear()

    client.post(
        f"/api/tickets/{ticket['id']}/comments",
        json={"comentario": "Revisar el rack antes de ir", "es_interno": True},
        headers=cab(client, "admin@test.com"),
    )

    assert enviados == []


def test_si_se_avisa_de_un_comentario_normal(client, monkeypatch):
    enviados = []
    monkeypatch.setattr(NotificacionesService, "_enviar",
                        staticmethod(lambda d, a, c: enviados.append(a) or True))
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.cgr.local")
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", True)

    ticket = crear(client, cab(client)).json()
    enviados.clear()

    client.post(
        f"/api/tickets/{ticket['id']}/comments",
        json={"comentario": "Ya lo estamos viendo"},
        headers=cab(client, "admin@test.com"),
    )

    assert len(enviados) == 1
    assert ticket["folio"] in enviados[0]


def test_nadie_se_avisa_a_si_mismo(client, monkeypatch):
    """Quien escribe el comentario no recibe correo de su propio comentario."""
    enviados = []
    monkeypatch.setattr(NotificacionesService, "_enviar",
                        staticmethod(lambda d, a, c: enviados.append(d) or True))
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.cgr.local")
    monkeypatch.setattr(settings, "NOTIFICACIONES_ACTIVAS", True)

    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()
    enviados.clear()

    client.post(f"/api/tickets/{ticket['id']}/comments",
                json={"comentario": "Sigo sin poder trabajar"}, headers=cabeceras)

    assert enviados == []
