"""Horario del equipo de TI, SLA en horas hábiles y adjuntos.

En la planta no hay personal después de las 17:00. El portal no finge que sí.
"""

import io
from datetime import datetime

import pytest

from app.core.config import settings
from app.services.horario_service import HorarioService, a_utc


def token(client, email="user@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


def cab(client, email="user@test.com"):
    return {"Authorization": f"Bearer {token(client, email=email)}"}


def crear(client, cabeceras, **extra):
    payload = {
        "sitio_id": 1,
        "categoria": "equipo",
        "descripcion_original": "El monitor de la estación 4 no da imagen",
        "prioridad": "media",
    }
    payload.update(extra)
    return client.post("/api/tickets", json=payload, headers=cabeceras)


# Referencias en hora LOCAL de la planta, convertidas a UTC para las pruebas.
MIERCOLES_10AM = a_utc(datetime(2026, 8, 26, 10, 0))   # laboral
MIERCOLES_20PM = a_utc(datetime(2026, 8, 26, 20, 0))   # ya se fueron
SABADO_11AM = a_utc(datetime(2026, 8, 29, 11, 0))      # fin de semana
VIERNES_1650 = a_utc(datetime(2026, 8, 28, 16, 50))    # a diez minutos de cerrar


# ----------------------------------------------------------------------
# ¿Hay alguien?
# ----------------------------------------------------------------------
@pytest.mark.parametrize("momento,esperado", [
    (MIERCOLES_10AM, True),
    (MIERCOLES_20PM, False),
    (SABADO_11AM, False),
    (VIERNES_1650, True),
    (a_utc(datetime(2026, 8, 26, 7, 59)), False),   # justo antes de abrir
    (a_utc(datetime(2026, 8, 26, 8, 0)), True),     # justo al abrir
    (a_utc(datetime(2026, 8, 26, 17, 0)), False),   # justo al cerrar
])
def test_deteccion_de_horario_laboral(momento, esperado):
    assert HorarioService.es_horario_laboral(momento) is esperado


def test_de_noche_el_proximo_turno_es_la_manana_siguiente():
    proximo = HorarioService.proximo_inicio_laboral(MIERCOLES_20PM)
    assert HorarioService.es_horario_laboral(proximo)
    # Es después del momento consultado y dentro de las próximas 24 horas.
    assert MIERCOLES_20PM < proximo < MIERCOLES_20PM.replace(day=27, hour=23)


def test_el_sabado_el_proximo_turno_es_el_lunes():
    proximo = HorarioService.proximo_inicio_laboral(SABADO_11AM)
    assert HorarioService.es_horario_laboral(proximo)
    # 0 = lunes en hora local.
    from app.services.horario_service import a_hora_local
    assert a_hora_local(proximo).weekday() == 0


# ----------------------------------------------------------------------
# SLA en horas hábiles
# ----------------------------------------------------------------------
def test_el_sla_no_corre_de_madrugada():
    """Un ticket de las 20:00 no consume su SLA mientras nadie trabaja."""
    vence = HorarioService.calcular_vencimiento("critica", MIERCOLES_20PM)

    # Crítica son 2 horas hábiles: abren a las 8, así que vence cerca de las 10.
    from app.services.horario_service import a_hora_local
    local = a_hora_local(vence)
    assert local.hour == pytest.approx(10, abs=1)
    assert HorarioService.es_horario_laboral(vence)


def test_el_viernes_tarde_vence_el_lunes():
    """Ocho horas hábiles desde el viernes 16:50 caen el lunes, no el sábado."""
    vence = HorarioService.calcular_vencimiento("alta", VIERNES_1650)

    from app.services.horario_service import a_hora_local
    assert a_hora_local(vence).weekday() == 0  # lunes


def test_una_prioridad_mas_alta_vence_antes():
    critica = HorarioService.calcular_vencimiento("critica", MIERCOLES_10AM)
    alta = HorarioService.calcular_vencimiento("alta", MIERCOLES_10AM)
    baja = HorarioService.calcular_vencimiento("baja", MIERCOLES_10AM)

    assert critica < alta < baja


def test_una_prioridad_desconocida_usa_la_media():
    """Nunca deja un ticket sin compromiso por un dato mal escrito."""
    assert HorarioService.calcular_vencimiento("urgentisimo", MIERCOLES_10AM) == \
           HorarioService.calcular_vencimiento("media", MIERCOLES_10AM)


# ----------------------------------------------------------------------
# El ticket nace con su compromiso
# ----------------------------------------------------------------------
def test_el_ticket_nace_con_vencimiento(client):
    datos = crear(client, cab(client)).json()

    assert datos["vence_en"] is not None
    assert datetime.fromisoformat(datos["vence_en"]) > datetime.fromisoformat(datos["creado_en"])


def test_una_auto_resolucion_no_tiene_vencimiento(client):
    """Ya está resuelta: no hay compromiso que vencer."""
    datos = crear(
        client, cab(client),
        canal_auto_resolucion="checklist",
        solucion="El cable de video estaba flojo; se reconectó y volvió la imagen.",
    ).json()

    assert datos["estado"] == "resuelto"
    assert datos["vence_en"] is None


def test_subir_la_prioridad_adelanta_el_vencimiento(client):
    ticket = crear(client, cab(client), prioridad="baja").json()
    antes = ticket["vence_en"]

    despues = client.patch(
        f"/api/tickets/{ticket['id']}", json={"prioridad": "critica"},
        headers=cab(client),
    ).json()

    assert despues["vence_en"] < antes


def test_el_endpoint_de_horario_dice_la_verdad(client):
    datos = client.get("/api/estado/horario", headers=cab(client)).json()

    assert "es_horario_laboral" in datos
    assert datos["horario_inicio"] == settings.HORARIO_INICIO
    assert datos["horario_fin"] == settings.HORARIO_FIN
    # Fuera de horario tiene que decir cuándo vuelven.
    if not datos["es_horario_laboral"]:
        assert datos["proximo_inicio"] is not None


def test_fuera_de_horario_se_ofrecen_mas_sugerencias(client, monkeypatch):
    monkeypatch.setattr(HorarioService, "es_horario_laboral", staticmethod(lambda m=None: False))
    datos = client.get("/api/estado/horario", headers=cab(client)).json()

    assert datos["max_sugerencias"] == settings.KB_MAX_SUGERENCIAS_FUERA_HORARIO
    assert datos["max_sugerencias"] > settings.KB_MAX_SUGERENCIAS


# ----------------------------------------------------------------------
# Adjuntos
# ----------------------------------------------------------------------
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def subir(client, ticket_id, cabeceras, nombre="foto.png", contenido=PNG, tipo="image/png"):
    return client.post(
        f"/api/tickets/{ticket_id}/adjuntos",
        files={"archivo": (nombre, io.BytesIO(contenido), tipo)},
        headers=cabeceras,
    )


def test_se_puede_adjuntar_una_foto(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    r = subir(client, ticket["id"], cabeceras)

    assert r.status_code == 201
    assert r.json()["nombre_original"] == "foto.png"
    assert r.json()["tipo_mime"] == "image/png"
    assert r.json()["tamano_bytes"] == len(PNG)


def test_la_foto_se_puede_descargar(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()
    adjunto = subir(client, ticket["id"], cabeceras).json()

    r = client.get(f"/api/tickets/{ticket['id']}/adjuntos/{adjunto['id']}", headers=cabeceras)

    assert r.status_code == 200
    assert r.content == PNG


def test_no_se_aceptan_ejecutables(client, tmp_path, monkeypatch):
    """Un portal interno no es lugar para intercambiar binarios arbitrarios."""
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    r = subir(client, ticket["id"], cabeceras, nombre="virus.exe",
              contenido=b"MZ\x90\x00", tipo="application/x-msdownload")

    assert r.status_code == 422


def test_se_rechaza_un_archivo_enorme(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    monkeypatch.setattr(settings, "ADJUNTOS_MAX_MB", 1)
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    r = subir(client, ticket["id"], cabeceras, contenido=b"x" * (2 * 1024 * 1024),
              tipo="image/png")

    assert r.status_code == 413


def test_hay_un_tope_de_adjuntos_por_ticket(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    monkeypatch.setattr(settings, "ADJUNTOS_MAX_POR_TICKET", 2)
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    assert subir(client, ticket["id"], cabeceras).status_code == 201
    assert subir(client, ticket["id"], cabeceras).status_code == 201
    assert subir(client, ticket["id"], cabeceras).status_code == 422


def test_no_se_ven_los_adjuntos_de_un_ticket_ajeno(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    # El admin levanta un ticket suyo.
    ticket = crear(client, cab(client, "admin@test.com")).json()

    r = client.get(f"/api/tickets/{ticket['id']}/adjuntos", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


def test_el_nombre_del_archivo_no_toca_el_disco(client, tmp_path, monkeypatch):
    """Un nombre con rutas relativas no debe escapar de la carpeta."""
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()

    r = subir(client, ticket["id"], cabeceras, nombre="../../../etc/passwd.png")

    assert r.status_code == 201
    # Se conserva para mostrarlo, pero en disco el nombre es generado.
    archivos = list(tmp_path.iterdir())
    assert len(archivos) == 1
    assert "passwd" not in archivos[0].name
    assert ".." not in archivos[0].name


def test_borrar_un_adjunto_lo_quita_del_disco(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    cabeceras = cab(client)
    ticket = crear(client, cabeceras).json()
    adjunto = subir(client, ticket["id"], cabeceras).json()
    assert len(list(tmp_path.iterdir())) == 1

    r = client.delete(f"/api/tickets/{ticket['id']}/adjuntos/{adjunto['id']}", headers=cabeceras)

    assert r.status_code == 204
    assert list(tmp_path.iterdir()) == []


# ----------------------------------------------------------------------
# Historial por equipo
# ----------------------------------------------------------------------
def test_el_historial_de_un_equipo_agrupa_sus_tickets(client, db_session):
    from app.models import Equipo

    equipo = Equipo(sitio_id=1, tipo="activo", categoria="impresora",
                    marca="Zebra", modelo="ZT411", numero_serie="ZBR-001")
    db_session.add(equipo)
    db_session.commit()
    db_session.refresh(equipo)

    cabeceras = cab(client)
    for _ in range(3):
        crear(client, cabeceras, equipo_id=equipo.id, categoria="impresora")

    datos = client.get(f"/api/equipos/{equipo.id}/historial", headers=cabeceras).json()

    assert datos["total_tickets"] == 3
    assert datos["abiertos"] == 3
    assert len(datos["tickets"]) == 3


def test_el_historial_de_un_equipo_inexistente(client):
    assert client.get("/api/equipos/9999/historial", headers=cab(client)).status_code == 404
