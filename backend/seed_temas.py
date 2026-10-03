"""Contenido de arranque: checklists y base de conocimiento de planta.

Los pasos están escritos para que un operador de piso los pueda seguir sin
vocabulario técnico, y en el orden en que un técnico revisaría de verdad: lo
físico y gratis antes que lo complicado.

Criterio de diseño: la primera pregunta de cada categoría es siempre la causa
más frecuente y más tonta. Un monitor que "no sirve" casi siempre está
desconectado, y preguntar eso primero resuelve el ticket antes de crearlo.

Uso:
    python seed_temas.py
"""

import os
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.logging import logger
from app.models import BaseConocimiento, Checklist, Sitio
from app.services.ollama_client import ollama

# (categoria, pregunta, accion_si_no, resuelve)
#
# `resuelve=True` significa que responder "sí" a esa pregunta cierra el caso:
# el usuario ya encontró la causa y la puede corregir solo.
PASOS = [
    # ---------------------------------------------------------------
    # EQUIPO — lo más reportado y lo más frecuentemente trivial
    # ---------------------------------------------------------------
    ("equipo", "¿El monitor tiene luz encendida en su botón de encendido?",
     "Si no tiene luz: revise que el cable de corriente esté firme en el monitor y en la toma. "
     "Pruebe otra toma de corriente.", True),
    ("equipo", "¿El cable de video (HDMI/DisplayPort/VGA) está bien puesto en los dos extremos?",
     "Desconéctelo y vuelva a conectarlo firmemente en la computadora y en el monitor. "
     "Es la causa número uno de 'el monitor no sirve'.", True),
    ("equipo", "Si el monitor dice 'sin señal': ¿la computadora está encendida?",
     "Revise que la torre o laptop tenga luz. Si está apagada, enciéndala y espere un minuto.", True),
    ("equipo", "¿La computadora está conectada a la corriente y el docking bien asentado?",
     "En laptops, retire y vuelva a colocar el equipo en la base. Verifique que el LED del docking encienda.", True),
    ("equipo", "¿Intentó apagar el equipo por completo (10 segundos) y volver a encenderlo?",
     "Mantenga presionado el botón de encendido 10 segundos, espere, y encienda de nuevo. "
     "No es lo mismo que reiniciar.", True),
    ("equipo", "¿El teclado o mouse tienen el cable conectado, o pilas con carga si son inalámbricos?",
     "Pruebe el dispositivo en otro puerto USB. Si es inalámbrico, cambie las pilas.", True),

    # ---------------------------------------------------------------
    # IMPRESORA / ETIQUETADORA
    # ---------------------------------------------------------------
    ("impresora", "¿La impresora está encendida y con luz verde estable?",
     "Si parpadea en rojo o ámbar, anote qué luz es: normalmente indica papel, tóner o atasco.", False),
    ("impresora", "¿Tiene papel o etiquetas suficientes, y el rollo está bien colocado?",
     "Abra la tapa, verifique que el rollo gire libre y que las etiquetas salgan por la ranura correcta.", True),
    ("impresora", "¿El tóner o el ribbon están colocados y no se han agotado?",
     "En etiquetadoras térmicas revise el ribbon; si está transparente o rasgado, hay que cambiarlo.", True),
    ("impresora", "¿Hay papel o etiqueta atascada dentro?",
     "Apague, abra la tapa y retire el material con cuidado jalando en el sentido del avance. Nunca al revés.", True),
    ("impresora", "¿Apagó la impresora 10 segundos y la volvió a encender?",
     "Muchos atascos de cola de impresión se limpian con este reinicio.", True),
    ("impresora", "¿La impresora está en la lista y aparece 'En línea' en la computadora?",
     "Si aparece 'Sin conexión' o 'Pausada', puede reactivarla desde Dispositivos e impresoras.", True),
    ("impresora", "¿El cable de red o USB de la impresora está firme?",
     "En impresoras de red verifique que el led del puerto esté encendido.", True),

    # ---------------------------------------------------------------
    # RED
    # ---------------------------------------------------------------
    ("red", "¿El cable de red está bien puesto en la pared y en el equipo?",
     "Debe hacer clic al insertarlo. Verifique que la lucecita del puerto encienda.", True),
    ("red", "¿Otras personas de su área también están sin red?",
     "Si es toda el área, probablemente sea el switch de piso: repórtelo indicando el área completa.", False),
    ("red", "Si usa Wi-Fi: ¿está conectado a la red de planta y no a otra?",
     "Revise el ícono de Wi-Fi: la red de la planta es «CGR_QUERETARO_OFFICE».", True),
    ("red", "¿Intentó desconectar el cable, esperar 10 segundos y volver a conectarlo?",
     "Esto obliga al equipo a pedir una dirección de red nueva.", True),
    ("red", "¿El problema es que no abre una página o que no abre ninguna?",
     "Si abre otras páginas, el problema es del sistema en cuestión y no de la red.", False),

    # ---------------------------------------------------------------
    # ACCESOS
    # ---------------------------------------------------------------
    ("accesos", "¿El teclado tiene activada la tecla de mayúsculas (Caps Lock)?",
     "Es la causa más común de contraseña rechazada. Verifique la luz del teclado.", True),
    ("accesos", "¿Está escribiendo su usuario completo, con el dominio si aplica?",
     "Confirme el formato con el que normalmente entra.", True),
    ("accesos", "¿El sistema le dice 'cuenta bloqueada' o 'contraseña incorrecta'?",
     "Son cosas distintas: bloqueada requiere desbloqueo de TI; incorrecta puede ser un error de escritura.", False),
    ("accesos", "¿Su contraseña venció recientemente o le pidieron cambiarla?",
     "Si venció, el sistema debería ofrecerle cambiarla al intentar entrar.", False),

    # ---------------------------------------------------------------
    # SOFTWARE
    # ---------------------------------------------------------------
    ("software", "¿El programa muestra algún mensaje de error con texto o número?",
     "Anótelo tal cual aparece o tome una foto: es lo que más acelera el diagnóstico.", False),
    ("software", "¿Intentó cerrar el programa por completo y volver a abrirlo?",
     "Ciérrelo desde la X y confirme que ya no aparezca en la barra de tareas.", True),
    ("software", "¿Le pasa a usted solamente o también a sus compañeros?",
     "Si le pasa a todos, es del sistema central y no de su equipo.", False),
    ("software", "¿Reinició la computadora desde que empezó el problema?",
     "Un reinicio completo resuelve la mayoría de los bloqueos de aplicación.", True),
    ("software", "¿El problema empezó después de una actualización o de un cambio reciente?",
     "Si sabe qué cambió, menciónelo en la descripción del ticket.", False),

    # ---------------------------------------------------------------
    # OTRO — no diagnostica, orienta a describir bien
    # ---------------------------------------------------------------
    ("otro", "¿Puede describir qué equipo o sistema está involucrado y en qué área está?",
     "Entre más específico sea (área, número de equipo, qué estaba haciendo), más rápido se atiende.", False),
    ("otro", "¿El problema le impide trabajar en este momento?",
     "Si detiene producción, indíquelo: eso cambia la prioridad del ticket.", False),
]

# Conocimiento de arranque. Sin esto la base empieza vacía y la búsqueda por
# similitud no tiene nada que sugerir durante las primeras semanas.
CONOCIMIENTO = [
    ("equipo", "Monitor sin imagen o 'sin señal'",
     "Causa más frecuente: cable de video flojo o desconectado. "
     "Pasos: 1) Verificar que el monitor tenga luz de encendido. "
     "2) Desconectar y reconectar el cable de video en ambos extremos. "
     "3) Probar otro puerto de video en la computadora. "
     "4) Si hay otro monitor cerca, intercambiar cables para descartar cable dañado. "
     "En la mayoría de los reportes de 'monitor descompuesto' el equipo estaba bien."),

    ("equipo", "Laptop no enciende estando en el docking",
     "El docking no siempre entrega corriente si no está bien asentado. "
     "Pasos: 1) Retirar la laptop del docking. 2) Conectar el cargador directo a la laptop. "
     "3) Si enciende, el problema es el docking o su fuente. "
     "4) Verificar que el LED del docking esté encendido y que su cable de corriente esté firme."),

    ("impresora", "Etiquetadora Zebra no imprime o saca etiquetas en blanco",
     "Etiquetas en blanco casi siempre significan ribbon agotado o mal colocado. "
     "Pasos: 1) Abrir la tapa y verificar el ribbon: si se ve transparente, se agotó. "
     "2) Confirmar que el rollo de etiquetas avanza libre. "
     "3) Calibrar la impresora con el botón de avance. "
     "4) Si imprime pero corrido, recalibrar el sensor de etiqueta."),

    ("impresora", "La impresora aparece 'Sin conexión' en la computadora",
     "Pasos: 1) Verificar que la impresora esté encendida y con red conectada. "
     "2) En Dispositivos e impresoras, quitar la marca de 'Usar impresora sin conexión'. "
     "3) Reiniciar la cola de impresión. "
     "4) Si persiste, apagar la impresora 10 segundos y encenderla."),

    ("red", "Sin red en un área completa",
     "Cuando varias personas de la misma área pierden red al mismo tiempo, "
     "el punto de falla suele ser el switch de piso, no los equipos. "
     "Pasos: 1) Confirmar cuántas personas están afectadas y de qué área. "
     "2) Revisar el switch del rack correspondiente: LEDs de puertos y de corriente. "
     "3) Verificar el enlace de subida al MDF. "
     "Registrar el área completa en el ticket acelera mucho la atención."),

    ("red", "Un equipo sin red mientras los demás sí tienen",
     "Si solo un equipo está afectado, el problema es local. "
     "Pasos: 1) Revisar que el cable haga clic y que el LED del puerto encienda. "
     "2) Probar el mismo cable en otro equipo. "
     "3) Probar otro cable en el mismo equipo. "
     "4) Renovar la dirección de red del equipo. "
     "Esto separa cable dañado, puerto muerto y problema de configuración."),

    ("accesos", "Cuenta bloqueada por intentos fallidos",
     "El bloqueo ocurre tras varios intentos con contraseña incorrecta. "
     "Causa frecuente: la tecla de mayúsculas activada, o un dispositivo con la "
     "contraseña vieja guardada (teléfono con el correo configurado) intentando "
     "entrar en segundo plano. "
     "Pasos: 1) Desbloquear la cuenta. 2) Revisar si algún dispositivo del usuario "
     "tiene credenciales viejas guardadas, o se volverá a bloquear solo."),

    ("software", "El sistema ERP va lento o no responde",
     "Antes de escalar, distinguir si es local o general. "
     "Pasos: 1) Preguntar si a los compañeros del área les pasa igual. "
     "2) Si es general, es del servidor y hay un solo ticket para todos. "
     "3) Si es local, cerrar la aplicación por completo y reabrirla. "
     "4) Reiniciar el equipo. "
     "5) Verificar que el equipo no esté con el disco lleno."),
]


def sembrar():
    db: Session = SessionLocal()
    try:
        # La misma planta que crea seed.py, con la misma variable.
        clave = (os.getenv("SEED_SITIO_CLAVE") or "QRO").strip().upper()
        sitio = db.query(Sitio).filter(Sitio.clave == clave).first()
        if not sitio:
            print(f"No existe el sitio {clave}. Corre primero seed.py")
            return

        # --- Checklists ---
        nuevos = 0
        for categoria, pregunta, accion, resuelve in PASOS:
            existe = db.query(Checklist).filter(
                Checklist.categoria == categoria,
                Checklist.pregunta_texto == pregunta,
            ).first()
            if existe:
                continue
            orden = db.query(Checklist).filter(Checklist.categoria == categoria).count() + 1
            db.add(Checklist(
                categoria=categoria,
                orden=orden,
                pregunta_key=f"seed.{categoria}.{orden}",
                pregunta_texto=pregunta,
                accion_si_no=accion,
                resuelve=resuelve,
                activo=True,
                creado_en=datetime.utcnow(),
            ))
            nuevos += 1
        db.commit()
        print(f"Pasos de checklist agregados: {nuevos}")

        # --- Base de conocimiento ---
        hay_ollama = ollama.disponible()
        if not hay_ollama:
            print("Ollama no responde: las entradas se guardan sin vector.")
            print("Corre reindexar_kb.py cuando esté disponible.")

        agregadas = 0
        for categoria, titulo, contenido in CONOCIMIENTO:
            if db.query(BaseConocimiento).filter(BaseConocimiento.titulo == titulo).first():
                continue
            texto = f"{categoria}\n{titulo}\n{contenido}"
            db.add(BaseConocimiento(
                sitio_id=sitio.id,
                titulo=titulo,
                contenido=contenido,
                categoria=categoria,
                embedding=ollama.generar_embedding(texto, tarea="documento") if hay_ollama else None,
                creado_en=datetime.utcnow(),
            ))
            agregadas += 1
        db.commit()
        print(f"Entradas de conocimiento agregadas: {agregadas}")

    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error sembrando temas: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sembrar()
