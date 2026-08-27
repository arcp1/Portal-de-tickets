"""Horario del equipo de TI y cálculo de SLA en horas hábiles.

En la planta no hay personal de TI después de las 17:00 ni en fin de semana.
Dos consecuencias de diseño:

1. **El portal no miente sobre los tiempos.** Un ticket abierto el viernes a las
   16:50 con SLA de 8 horas no vence el sábado a la 1:00; vence el lunes. Contar
   horas de reloj en vez de horas hábiles produce SLAs que nadie puede cumplir y
   métricas que solo sirven para verse mal.

2. **Fuera de horario el asistente se esfuerza más.** No hay a quién escalar,
   así que vale la pena mostrar más sugerencias antes de rendirse, y decirle al
   usuario con claridad cuándo lo van a atender de verdad.
"""

from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings

SLA_POR_PRIORIDAD = {
    "critica": "SLA_HORAS_CRITICA",
    "alta": "SLA_HORAS_ALTA",
    "media": "SLA_HORAS_MEDIA",
    "baja": "SLA_HORAS_BAJA",
}


def _dias_laborales() -> set:
    try:
        return {int(d.strip()) for d in settings.DIAS_LABORALES.split(",") if d.strip() != ""}
    except ValueError:
        # Configuración mal escrita: se asume lunes a viernes en vez de romper.
        return {0, 1, 2, 3, 4}


def a_hora_local(momento: datetime) -> datetime:
    """UTC -> hora de la planta.

    Todo se guarda en UTC; el horario laboral solo tiene sentido en local.
    """
    return momento + timedelta(hours=settings.HUSO_HORARIO_OFFSET)


def a_utc(local: datetime) -> datetime:
    return local - timedelta(hours=settings.HUSO_HORARIO_OFFSET)


class HorarioService:

    @staticmethod
    def es_horario_laboral(momento: Optional[datetime] = None) -> bool:
        """¿Hay alguien de TI en este momento?"""
        local = a_hora_local(momento or datetime.utcnow())
        if local.weekday() not in _dias_laborales():
            return False
        return settings.HORARIO_INICIO <= local.hour < settings.HORARIO_FIN

    @staticmethod
    def proximo_inicio_laboral(momento: Optional[datetime] = None) -> datetime:
        """Cuándo vuelve a haber personal. Devuelve UTC."""
        local = a_hora_local(momento or datetime.utcnow())
        laborales = _dias_laborales()

        # Si hoy es laboral y aún no abren, es hoy a la hora de apertura.
        if local.weekday() in laborales and local.hour < settings.HORARIO_INICIO:
            candidato = local.replace(hour=settings.HORARIO_INICIO, minute=0, second=0, microsecond=0)
            return a_utc(candidato)

        # Si no, el siguiente día laboral a la hora de apertura.
        candidato = local
        for _ in range(8):  # una semana basta; el bucle nunca es infinito
            candidato = (candidato + timedelta(days=1)).replace(
                hour=settings.HORARIO_INICIO, minute=0, second=0, microsecond=0
            )
            if candidato.weekday() in laborales:
                return a_utc(candidato)

        # Sin días laborales configurados: se devuelve el momento tal cual.
        return momento or datetime.utcnow()

    @staticmethod
    def sumar_horas_habiles(desde: datetime, horas: float) -> datetime:
        """Avanza `horas` contando solo tiempo dentro del horario laboral.

        Recibe y devuelve UTC. Avanza en pasos de 15 minutos: es suficiente
        precisión para un SLA y evita la aritmética de bordes de jornada.
        """
        laborales = _dias_laborales()
        if not laborales or settings.HORARIO_FIN <= settings.HORARIO_INICIO:
            # Configuración sin sentido: se cae a horas de reloj.
            return desde + timedelta(hours=horas)

        restantes = timedelta(hours=horas)
        paso = timedelta(minutes=15)
        actual = desde
        # Techo de seguridad: 400 días hábiles en pasos de 15 min.
        for _ in range(400 * 24 * 4):
            if restantes <= timedelta(0):
                return actual
            local = a_hora_local(actual)
            dentro = (
                local.weekday() in laborales
                and settings.HORARIO_INICIO <= local.hour < settings.HORARIO_FIN
            )
            if dentro:
                restantes -= paso
            actual += paso
        return actual

    @staticmethod
    def calcular_vencimiento(prioridad: str, creado_en: Optional[datetime] = None) -> datetime:
        """Cuándo vence el SLA de un ticket, en UTC."""
        creado_en = creado_en or datetime.utcnow()
        atributo = SLA_POR_PRIORIDAD.get((prioridad or "media").lower(), "SLA_HORAS_MEDIA")
        horas = getattr(settings, atributo)

        # Si entra fuera de horario, el reloj empieza a correr cuando abren.
        inicio = creado_en
        if not HorarioService.es_horario_laboral(creado_en):
            inicio = HorarioService.proximo_inicio_laboral(creado_en)

        return HorarioService.sumar_horas_habiles(inicio, horas)

    @staticmethod
    def contexto(momento: Optional[datetime] = None) -> dict:
        """Lo que el frontend necesita para decirle la verdad al usuario."""
        momento = momento or datetime.utcnow()
        laboral = HorarioService.es_horario_laboral(momento)
        proximo = None if laboral else HorarioService.proximo_inicio_laboral(momento)
        return {
            "es_horario_laboral": laboral,
            "proximo_inicio": proximo.isoformat() if proximo else None,
            "horario_inicio": settings.HORARIO_INICIO,
            "horario_fin": settings.HORARIO_FIN,
            # Fuera de horario se muestran más sugerencias: no hay a quién escalar.
            "max_sugerencias": (
                settings.KB_MAX_SUGERENCIAS if laboral
                else settings.KB_MAX_SUGERENCIAS_FUERA_HORARIO
            ),
        }
