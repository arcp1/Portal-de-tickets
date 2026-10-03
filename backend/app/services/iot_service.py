"""Telemetría de los ESP32: de un mensaje MQTT a una lectura, y de ahí a una alerta.

**El camino.** Cada ESP32 publica en

    portal/<clave de planta>/sensores/<clave del equipo>/telemetria

un JSON como ``{"temperatura": 24.6, "humedad": 41, "calidad_aire": 412}``. El
receptor (``app/iot/ingestor.py``) está suscrito a todo ese árbol y le pasa
cada mensaje a ``procesar``, que es lo único que decide qué se guarda. Vive
aquí, sin nada de MQTT, para poder probarlo entero sin broker.

**Lo que se descarta, y por qué.** Todo lo que llega por MQTT viene de una
red de planta, firmado con una contraseña compartida por todos los equipos:

  * Un tema que no tiene la forma de arriba, una planta que no existe, una
    clave de equipo con caracteres raros o un cuerpo de más de 2 KB.
  * Un equipo que TI desactivó.
  * Lecturas fuera de lo físicamente posible para el sensor (una humedad de
    140 % es un sensor suelto, no una alarma): ese valor se tira, los demás
    del mismo mensaje se guardan.
  * Mensajes más seguidos que ``IOT_INTERVALO_MINIMO_S``: un bucle sin pausa
    en el ESP32 llenaría la tabla en horas.

**Las alertas.** Por encima del umbral se abre una alerta por equipo y
magnitud, y sigue siendo una aunque lleguen mil lecturas altas. Se cierra sola
cuando el valor baja un 3 % por debajo del umbral: sin ese margen, un valor
que ronda el límite abriría y cerraría alertas cada cinco segundos.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import Alerta, DispositivoIoT, LecturaIoT, Sitio
from app.services.alertas_service import IOT_SIN_SENAL, IOT_UMBRAL, AlertasService

TEMA = re.compile(r"^portal/([A-Za-z0-9]{2,10})/sensores/([A-Za-z0-9_-]{1,64})/telemetria$")
CARGA_MAXIMA = 2048
HISTERESIS = 0.97

#: Las tres magnitudes, sus nombres aceptados en el JSON y lo que un sensor
#: puede medir de verdad (DHT22: -40 a 80 °C; MQ-135/SGP30/SCD40 en ppm).
MAGNITUDES: Dict[str, Tuple[Tuple[str, ...], float, float]] = {
    "temperatura": (("temperatura", "temp", "temperature", "t"), -40.0, 125.0),
    "humedad": (("humedad", "hum", "humidity", "h"), 0.0, 100.0),
    "calidad_aire": (("calidad_aire", "aire", "aqi", "co2", "air_quality", "ppm"), 0.0, 10000.0),
}
#: Otras cifras que vale la pena guardar si vienen (señal, voltaje...). Pocas.
EXTRA_MAXIMO = 8


def umbrales_de(dispositivo: DispositivoIoT) -> Dict[str, float]:
    propios = dispositivo.umbrales or {}
    return {
        "temperatura": float(propios.get("temperatura") or settings.IOT_TEMPERATURA_MAX),
        "humedad": float(propios.get("humedad") or settings.IOT_HUMEDAD_MAX),
        "calidad_aire": float(propios.get("calidad_aire") or settings.IOT_CALIDAD_AIRE_MAX),
    }


def _numero(valor) -> Optional[float]:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        numero = float(valor)
    elif isinstance(valor, str):
        try:
            numero = float(valor.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    # NaN e infinito no son lecturas: un sensor desconectado los devuelve.
    if numero != numero or numero in (float("inf"), float("-inf")):
        return None
    return numero


def leer_carga(carga: bytes) -> Tuple[Dict[str, Optional[float]], Dict[str, float]]:
    """Las tres magnitudes (o None) y lo extra. ValueError si no es un JSON útil."""
    if len(carga) > CARGA_MAXIMA:
        raise ValueError("mensaje demasiado grande")
    try:
        datos = json.loads(carga.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("no es JSON")
    if not isinstance(datos, dict):
        raise ValueError("no es un objeto JSON")
    claves = {str(k).strip().lower(): v for k, v in datos.items()}

    valores: Dict[str, Optional[float]] = {}
    usadas = set()
    for magnitud, (nombres, minimo, maximo) in MAGNITUDES.items():
        valores[magnitud] = None
        for nombre in nombres:
            if nombre in claves:
                usadas.add(nombre)
                numero = _numero(claves[nombre])
                if numero is not None and minimo <= numero <= maximo:
                    valores[magnitud] = round(numero, 2)
                break

    extra = {}
    for clave, valor in claves.items():
        if clave in usadas or len(extra) >= EXTRA_MAXIMO or len(clave) > 32:
            continue
        numero = _numero(valor)
        if numero is not None:
            extra[clave] = round(numero, 3)

    if all(v is None for v in valores.values()):
        raise ValueError("sin temperatura, humedad ni calidad del aire válidas")
    return valores, extra


class IoTService:

    @staticmethod
    def procesar(db: Session, tema: str, carga: bytes,
                 ahora: Optional[datetime] = None) -> dict:
        """Un mensaje MQTT. Devuelve qué pasó con él (para el registro y las pruebas).

        Nunca levanta por culpa del mensaje: lo malo se descarta y se dice por qué.
        """
        ahora = ahora or datetime.utcnow()
        coincide = TEMA.match(tema or "")
        if not coincide:
            return {"resultado": "descartado", "motivo": "tema"}
        clave_planta, clave_equipo = coincide.group(1).upper(), coincide.group(2)

        try:
            valores, extra = leer_carga(carga)
        except ValueError as exc:
            return {"resultado": "descartado", "motivo": str(exc)}

        dispositivo = db.query(DispositivoIoT).filter(DispositivoIoT.clave == clave_equipo).first()
        nuevo = False
        if dispositivo is None:
            planta = db.query(Sitio).filter(func.upper(Sitio.clave) == clave_planta,
                                            Sitio.activo.is_(True)).first()
            if planta is None:
                return {"resultado": "descartado", "motivo": "planta desconocida"}
            # Se registra solo. TI le pone nombre y ubicación después, o lo
            # desactiva si no es de la casa.
            dispositivo = DispositivoIoT(clave=clave_equipo, nombre=clave_equipo,
                                         sitio_id=planta.id, activo=True, creado_en=ahora)
            db.add(dispositivo)
            db.flush()
            nuevo = True
            logger.info("Sensor nuevo registrado",
                        extra={"clave": clave_equipo, "sitio_id": planta.id})
        elif not dispositivo.activo:
            return {"resultado": "descartado", "motivo": "equipo desactivado"}
        elif (dispositivo.ultimo_contacto
              and (ahora - dispositivo.ultimo_contacto).total_seconds() < settings.IOT_INTERVALO_MINIMO_S):
            return {"resultado": "descartado", "motivo": "demasiado seguido"}

        lectura = LecturaIoT(dispositivo_id=dispositivo.id, registrado_en=ahora,
                             extra=extra or None, **valores)
        db.add(lectura)
        dispositivo.ultimo_contacto = ahora
        db.commit()

        cambios = IoTService._evaluar(db, dispositivo, valores)
        return {"resultado": "guardado", "dispositivo_id": dispositivo.id, "nuevo": nuevo,
                "sitio_id": dispositivo.sitio_id, "alertas": cambios}

    @staticmethod
    def _evaluar(db: Session, dispositivo: DispositivoIoT, valores: Dict[str, Optional[float]]) -> int:
        """Abre o cierra alertas de umbral. Devuelve cuántas cambiaron."""
        cambios = 0
        # Volvió a reportar: si estaba "sin señal", ya no.
        sin_senal = AlertasService.abierta(db, IOT_SIN_SENAL, f"dispositivo:{dispositivo.id}")
        if sin_senal:
            AlertasService.cerrar(db, sin_senal, nota="Volvió a reportar.")
            db.commit()
            cambios += 1

        nombre = dispositivo.nombre or dispositivo.clave
        for magnitud, umbral in umbrales_de(dispositivo).items():
            valor = valores.get(magnitud)
            if valor is None:
                continue
            clave = f"dispositivo:{dispositivo.id}:{magnitud}"
            abierta = AlertasService.abierta(db, IOT_UMBRAL, clave)
            if valor > umbral and not abierta:
                if AlertasService.abrir(
                        db, IOT_UMBRAL, clave, f"{nombre}: {magnitud} {valor} (máx. {umbral:g})",
                        datos={"dispositivo": nombre, "magnitud": magnitud, "valor": valor,
                               "umbral": umbral},
                        sitio_id=dispositivo.sitio_id, dispositivo_id=dispositivo.id,
                        avisar=False):
                    cambios += 1
            elif abierta and valor <= umbral * HISTERESIS:
                AlertasService.cerrar(db, abierta, nota=f"Se normalizó: {valor}.")
                db.commit()
                cambios += 1
        return cambios

    # ------------------------------------------------------------------
    # Lo que corre el worker
    # ------------------------------------------------------------------
    @staticmethod
    def vigilar_senal(db: Session, ahora: Optional[datetime] = None) -> int:
        """Alerta por cada equipo activo que lleva demasiado sin reportar."""
        ahora = ahora or datetime.utcnow()
        limite = ahora - timedelta(minutes=settings.IOT_SIN_SENAL_MINUTOS)
        callados = (db.query(DispositivoIoT)
                    .filter(DispositivoIoT.activo.is_(True),
                            DispositivoIoT.ultimo_contacto.isnot(None),
                            DispositivoIoT.ultimo_contacto < limite).all())
        abiertas = 0
        for d in callados:
            minutos = int((ahora - d.ultimo_contacto).total_seconds() // 60)
            nombre = d.nombre or d.clave
            if AlertasService.abrir(
                    db, IOT_SIN_SENAL, f"dispositivo:{d.id}",
                    f"{nombre}: sin señal desde hace {minutos} min",
                    datos={"dispositivo": nombre, "minutos": minutos},
                    sitio_id=d.sitio_id, dispositivo_id=d.id, avisar=False):
                abiertas += 1
        return abiertas

    @staticmethod
    def purgar(db: Session, dias: Optional[int] = None, ahora: Optional[datetime] = None) -> int:
        dias = dias or settings.IOT_RETENCION_DIAS
        corte = (ahora or datetime.utcnow()) - timedelta(days=dias)
        borradas = (db.query(LecturaIoT).filter(LecturaIoT.registrado_en < corte)
                    .delete(synchronize_session=False))
        db.commit()
        return borradas

    # ------------------------------------------------------------------
    # Para la pantalla
    # ------------------------------------------------------------------
    @staticmethod
    def ultimas(db: Session, ids: List[int]) -> Dict[int, LecturaIoT]:
        """La lectura más reciente de cada equipo, en una consulta."""
        if not ids:
            return {}
        reciente = (db.query(LecturaIoT.dispositivo_id,
                             func.max(LecturaIoT.registrado_en).label("en"))
                    .filter(LecturaIoT.dispositivo_id.in_(ids))
                    .group_by(LecturaIoT.dispositivo_id).subquery())
        filas = (db.query(LecturaIoT)
                 .join(reciente, (LecturaIoT.dispositivo_id == reciente.c.dispositivo_id)
                       & (LecturaIoT.registrado_en == reciente.c.en)).all())
        return {f.dispositivo_id: f for f in filas}

    @staticmethod
    def serie(db: Session, dispositivo_id: int, horas: int, puntos: int,
              ahora: Optional[datetime] = None) -> dict:
        """Promedios por tramo para la gráfica: `puntos` tramos en `horas`.

        Se agrupa en la base. Siete días de un equipo cada 5 s son 120 000
        filas; la gráfica pinta 120 puntos y no necesita las otras.
        """
        ahora = ahora or datetime.utcnow()
        desde = ahora - timedelta(hours=horas)
        paso = max(1, int(horas * 3600 / puntos))
        if db.bind.dialect.name == "postgresql":
            # floor y no un CAST a entero, que en Postgres redondea.
            tramo = cast(func.floor(func.extract("epoch", LecturaIoT.registrado_en) / paso),
                         Integer)
        else:
            # SQLite (las pruebas): entero entre entero ya trunca.
            tramo = cast(func.strftime("%s", LecturaIoT.registrado_en), Integer) / paso
        tramo = tramo.label("tramo")
        filas = (db.query(tramo,
                          func.avg(LecturaIoT.temperatura), func.avg(LecturaIoT.humedad),
                          func.avg(LecturaIoT.calidad_aire), func.count(LecturaIoT.id))
                 .filter(LecturaIoT.dispositivo_id == dispositivo_id,
                         LecturaIoT.registrado_en >= desde)
                 .group_by(tramo).order_by(tramo).all())

        def _r(v):
            return round(float(v), 2) if v is not None else None

        serie = [{"t": datetime.utcfromtimestamp(int(t) * paso).isoformat() + "Z",
                  "temperatura": _r(te), "humedad": _r(hu), "calidad_aire": _r(ai), "n": n}
                 for t, te, hu, ai, n in filas]
        resumen = {}
        for magnitud in MAGNITUDES:
            valores = [p[magnitud] for p in serie if p[magnitud] is not None]
            resumen[magnitud] = ({"min": min(valores), "max": max(valores),
                                  "promedio": round(sum(valores) / len(valores), 2)}
                                 if valores else None)
        return {"desde": desde.isoformat() + "Z", "hasta": ahora.isoformat() + "Z",
                "paso_segundos": paso, "puntos": serie, "resumen": resumen,
                "lecturas": sum(p["n"] for p in serie)}

    @staticmethod
    def alertas_abiertas(db: Session, ids: List[int]) -> Dict[int, int]:
        if not ids:
            return {}
        return dict(db.query(Alerta.dispositivo_id, func.count(Alerta.id))
                    .filter(Alerta.dispositivo_id.in_(ids), Alerta.atendida_en.is_(None))
                    .group_by(Alerta.dispositivo_id).all())
