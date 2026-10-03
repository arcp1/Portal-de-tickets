"""Telemetría ESP32 (sin broker: lo que decide vive en IoTService), etiquetas QR,
cierre de sesión y la cola de tareas sin Redis."""

import io
import json
from datetime import datetime, timedelta

import pytest
from PIL import Image

from app.core.config import settings
from app.models import Alerta, DispositivoIoT, Equipo, LecturaIoT
from app.services.iot_service import IoTService, leer_carga

TEMA = "portal/QRO/sensores/esp32-linea1/telemetria"


def _cab(client, email="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _carga(**valores):
    return json.dumps(valores).encode()


# ---------------------------------------------------------------------------
# Lo que llega por MQTT
# ---------------------------------------------------------------------------

def test_una_lectura_registra_el_sensor_y_se_guarda(db_session):
    r = IoTService.procesar(db_session, TEMA, _carga(temperatura=24.56, humedad="41,2", aire=412, rssi=-61))
    assert r["resultado"] == "guardado" and r["nuevo"] is True
    d = db_session.query(DispositivoIoT).one()
    assert d.clave == "esp32-linea1" and d.sitio_id == 1 and d.activo
    lectura = db_session.query(LecturaIoT).one()
    assert (lectura.temperatura, lectura.humedad, lectura.calidad_aire) == (24.56, 41.2, 412.0)
    assert lectura.extra == {"rssi": -61.0}


@pytest.mark.parametrize("tema, carga, motivo", [
    ("portal/QRO/sensores/esp32/otra-cosa", _carga(temperatura=20), "tema"),
    ("portal/QRO/sensores/esp 32/telemetria", _carga(temperatura=20), "tema"),
    ("portal/XXX/sensores/esp32/telemetria", _carga(temperatura=20), "planta desconocida"),
    (TEMA, b"no es json", "no es JSON"),
    (TEMA, b"[1, 2]", "no es un objeto JSON"),
    (TEMA, _carga(temperatura=999, humedad=140), "sin temperatura"),
    (TEMA, _carga(temperatura="NaN"), "sin temperatura"),
    (TEMA, _carga(texto="x" * 3000), "demasiado grande"),
])
def test_lo_que_no_sirve_se_descarta_con_motivo(db_session, tema, carga, motivo):
    r = IoTService.procesar(db_session, tema, carga)
    assert r["resultado"] == "descartado"
    assert motivo in r["motivo"]
    assert db_session.query(LecturaIoT).count() == 0


def test_un_valor_imposible_se_tira_y_los_demas_se_guardan():
    valores, _ = leer_carga(_carga(temperatura=22, humedad=140))
    assert valores == {"temperatura": 22.0, "humedad": None, "calidad_aire": None}


def test_ni_demasiado_seguido_ni_de_un_sensor_desactivado(db_session):
    ahora = datetime.utcnow()
    assert IoTService.procesar(db_session, TEMA, _carga(t=20), ahora)["resultado"] == "guardado"
    r = IoTService.procesar(db_session, TEMA, _carga(t=21), ahora + timedelta(seconds=1))
    assert r["motivo"] == "demasiado seguido"
    d = db_session.query(DispositivoIoT).one()
    d.activo = False
    db_session.commit()
    r = IoTService.procesar(db_session, TEMA, _carga(t=21), ahora + timedelta(minutes=1))
    assert r["motivo"] == "equipo desactivado"


def test_el_umbral_abre_una_alerta_por_episodio_y_se_cierra_solo(db_session):
    ahora = datetime.utcnow()
    paso = timedelta(seconds=settings.IOT_INTERVALO_MINIMO_S + 1)
    caliente = settings.IOT_TEMPERATURA_MAX + 5
    for i in range(3):  # tres lecturas altas: una sola alerta
        IoTService.procesar(db_session, TEMA, _carga(temperatura=caliente), ahora + paso * i)
    abiertas = db_session.query(Alerta).filter(Alerta.atendida_en.is_(None)).all()
    assert [(a.tipo, a.datos["magnitud"]) for a in abiertas] == [("iot_umbral", "temperatura")]

    # Justo bajo el umbral no basta (histéresis); bastante por debajo, sí.
    IoTService.procesar(db_session, TEMA, _carga(temperatura=settings.IOT_TEMPERATURA_MAX - 0.1), ahora + paso * 3)
    assert db_session.query(Alerta).filter(Alerta.atendida_en.is_(None)).count() == 1
    IoTService.procesar(db_session, TEMA, _carga(temperatura=20), ahora + paso * 4)
    assert db_session.query(Alerta).filter(Alerta.atendida_en.is_(None)).count() == 0

    # Vuelve a subir: un episodio nuevo, una alerta nueva.
    IoTService.procesar(db_session, TEMA, _carga(temperatura=caliente), ahora + paso * 5)
    assert db_session.query(Alerta).count() == 2


def test_un_sensor_callado_avisa_y_al_volver_se_cierra(db_session):
    ahora = datetime.utcnow()
    IoTService.procesar(db_session, TEMA, _carga(t=20), ahora)
    tarde = ahora + timedelta(minutes=settings.IOT_SIN_SENAL_MINUTOS + 1)
    assert IoTService.vigilar_senal(db_session, tarde) == 1
    assert IoTService.vigilar_senal(db_session, tarde) == 0  # no se repite
    IoTService.procesar(db_session, TEMA, _carga(t=20), tarde)
    assert db_session.query(Alerta).filter(Alerta.atendida_en.is_(None)).count() == 0


def test_la_purga_borra_solo_lo_viejo(db_session):
    ahora = datetime.utcnow()
    IoTService.procesar(db_session, TEMA, _carga(t=20), ahora - timedelta(days=settings.IOT_RETENCION_DIAS + 1))
    IoTService.procesar(db_session, TEMA, _carga(t=21), ahora)
    assert IoTService.purgar(db_session, ahora=ahora) == 1
    assert db_session.query(LecturaIoT).count() == 1


# ---------------------------------------------------------------------------
# El API de Monitoreo ESP32
# ---------------------------------------------------------------------------

def test_monitoreo_lista_la_ultima_lectura_y_la_grafica(client, db_session):
    ahora = datetime.utcnow()
    for i in range(6):
        IoTService.procesar(db_session, TEMA, _carga(temperatura=20 + i, humedad=40),
                            ahora - timedelta(minutes=50 - i * 10))
    cab = _cab(client)
    lista = client.get("/api/admin/iot/dispositivos", headers=cab).json()
    assert len(lista) == 1
    d = lista[0]
    assert d["ultima"]["temperatura"] == 25.0
    assert d["sitio"]["clave"] == "QRO" and d["en_linea"] is True
    assert d["umbrales"]["temperatura"] == settings.IOT_TEMPERATURA_MAX

    serie = client.get(f"/api/admin/iot/dispositivos/{d['id']}/lecturas?horas=1&puntos=12", headers=cab).json()
    assert serie["lecturas"] == 6
    assert serie["resumen"]["temperatura"] == {"min": 20.0, "max": 25.0, "promedio": 22.5}

    assert client.get("/api/admin/iot/dispositivos", headers=_cab(client, "user@test.com")).status_code == 403


def test_ti_le_pone_nombre_y_umbrales_propios(client, db_session):
    IoTService.procesar(db_session, TEMA, _carga(t=20))
    did = db_session.query(DispositivoIoT).one().id
    cab = _cab(client)
    r = client.patch(f"/api/admin/iot/dispositivos/{did}", headers=cab,
                     json={"nombre": "Cuarto de servidores", "ubicacion": "Planta alta",
                           "umbrales": {"temperatura": 27}})
    assert r.status_code == 200, r.text
    assert r.json()["umbrales"]["temperatura"] == 27
    assert r.json()["umbrales"]["humedad"] == settings.IOT_HUMEDAD_MAX
    assert client.patch(f"/api/admin/iot/dispositivos/{did}", headers=cab,
                        json={"umbrales": {"temperatura": 500}}).status_code == 422
    assert client.patch(f"/api/admin/iot/dispositivos/{did}", headers=cab,
                        json={"umbrales": {"presion": 3}}).status_code == 422
    r = client.patch(f"/api/admin/iot/dispositivos/{did}", headers=cab,
                     json={"umbrales": {"temperatura": None}})
    assert r.json()["umbrales_propios"] is None
    assert client.delete(f"/api/admin/iot/dispositivos/{did}", headers=cab).status_code == 200
    assert db_session.query(LecturaIoT).count() == 0


# ---------------------------------------------------------------------------
# Etiqueta QR
# ---------------------------------------------------------------------------

def _equipo(db, categoria="Impresora de etiquetas"):
    e = Equipo(sitio_id=1, tipo="activo", categoria=categoria, marca="Zebra", modelo="ZT410",
               numero_serie="ZBR-0042", ubicacion="Andén 2", estado="disponible")
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def test_la_etiqueta_es_un_png_imprimible_con_el_enlace_correcto(client, db_session):
    e = _equipo(db_session)
    r = client.get(f"/api/equipos/{e.id}/etiqueta.png", headers=_cab(client))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    imagen = Image.open(io.BytesIO(r.content))
    assert imagen.size == (1200, 600)
    assert round(imagen.info["dpi"][0]) == 300
    enlace = r.headers["x-enlace-qr"]
    assert enlace == f"{settings.PORTAL_URL.rstrip('/')}/new-ticket?equipo={e.id}&categoria=impresora"


@pytest.mark.parametrize("categoria, esperada", [
    ("Laptop", "equipo"), ("Switch de piso", "red"), ("Multifuncional", "impresora"), ("Monitor", "equipo"),
])
def test_la_categoria_del_qr_sale_del_inventario(db_session, categoria, esperada):
    from app.services.etiqueta_service import categoria_de_ticket
    e = _equipo(db_session, categoria)
    e.marca, e.modelo = "Dell", "X"
    assert categoria_de_ticket(e) == esperada


def test_la_etiqueta_es_de_ti_y_no_de_otra_planta_inexistente(client, db_session):
    e = _equipo(db_session)
    assert client.get(f"/api/equipos/{e.id}/etiqueta.png", headers=_cab(client, "user@test.com")).status_code == 403
    assert client.get("/api/equipos/999999/etiqueta.png", headers=_cab(client)).status_code == 404


def test_la_etiqueta_aguanta_textos_largos_y_acentos(client, db_session):
    e = _equipo(db_session)
    e.marca, e.modelo = "Fabricante Ñandú de Equipos Electrónicos Industriales", "Modelo " + "X" * 80
    e.numero_serie = "S" * 60
    e.ubicacion = "Almacén de refacciones, pasillo 14, anaquel C, entrepaño 3, junto al montacargas"
    db_session.commit()
    r = client.get(f"/api/equipos/{e.id}/etiqueta.png", headers=_cab(client))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Sesión y cola sin Redis
# ---------------------------------------------------------------------------

def test_cerrar_sesion_sin_redis_responde_y_no_revoca(client):
    cab = _cab(client, "user@test.com")
    r = client.post("/api/auth/logout", headers=cab)
    assert r.status_code == 200 and r.json() == {"ok": True, "revocada": False}


def test_sin_redis_las_tareas_se_hacen_en_la_peticion():
    from app.core import tareas
    assert tareas.encolar("indexar_ticket", 1) is False


def test_las_pruebas_no_alcanzan_la_base_ni_la_redis_reales():
    """Si esto falla, la suite está escribiendo en producción."""
    assert settings.REDIS_URL == ""
    assert "127.0.0.1:9" in settings.DATABASE_URL
    assert settings.MIGRAR_AL_ARRANCAR == "sql"
