#!/usr/bin/env python3
"""Ver las pantallas del portal sin sesión, sin base de datos y sin producción.

    python3 scripts/vista-previa.py            # estado "a medias"
    python3 scripts/vista-previa.py vacio      # portal recién instalado
    python3 scripts/vista-previa.py roto       # todo lo que puede fallar, fallando

Después: abrir http://localhost:8099/conocimiento
               http://localhost:8099/conocimiento/catalogo

**Para qué existe.** Las pantallas de este portal cambian de forma según los
datos —el mapa de conocimiento pinta un nodo hueco distinto de uno vacío, la
tubería marca atascos, los avisos aparecen y desaparecen—, y producir esos
estados en la base de datos real es lento y a veces imposible sin ensuciarla.
Aquí se sirve el `dist` ya construido con respuestas de API inventadas, así que
se puede mirar cada estado en segundos.

Sirvió para algo concreto: durante tres rondas de trabajo no se pudo comprobar
cómo quedaba la pantalla de Conciencia porque la sesión del navegador había
caducado, y **no se piden credenciales a nadie para ver una pantalla**. Con
esto se ve.

**Qué NO es.** No prueba el backend ni la autenticación: las respuestas son
constantes escritas aquí abajo. Sirve para juzgar el aspecto y el
comportamiento de la interfaz, no para validar datos.

**Cuidado con la caducidad.** Estos ejemplos imitan la forma que devuelve
`ConcienciaService` hoy. Si esa forma cambia y nadie toca este archivo, la vista
previa mentirá — enseñará una pantalla que ya no existe. Ante la duda, contraste
con la respuesta real:

    curl -s -H "Authorization: Bearer <token>" \\
      http://localhost/api/admin/conciencia/aprendizaje | python3 -m json.tool
"""

import http.server
import json
import os
import shutil
import signal
import socketserver
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

PUERTO = 8099
IMAGEN = "portal-de-tickets-frontend:latest"

# `sitio_nombre` a propósito distinto de cualquier planta real: la barra lo
# pinta tal cual, así que si en pantalla sale "Querétaro" es que alguien volvió
# a escribir el nombre en una traducción.
USUARIO = {"id": 1, "nombre": "Vista previa", "email": "vista@cgr.mx",
           "rol": "admin", "sitio_id": 1, "sitio_nombre": "Planta de vista previa",
           "idioma_preferido": "es", "puede_usar_prioridad_alta": True,
           "numero_empleado": "0001", "estado_cuenta": "activa"}


def _tickets_de_muestra():
    """Una página del tablero con la forma de `TicketPagina` (api/tickets.py).

    El total dice 47 para que se vean los controles de paginación; la página
    trae solo tres porque el guion no pagina de verdad: siempre devuelve esta.
    """
    persona = {"id": 7, "sitio_id": 1, "sitio_nombre": USUARIO["sitio_nombre"],
               "nombre": "Operador de muestra", "rol": "usuario", "activo": True,
               "idioma_preferido": "es"}
    casos = [
        (101, "abierto", "alta", "impresora", "La Zebra del andén 2 saca una raya negra"),
        (100, "en_proceso", "media", "red", "Se cae el wifi del almacén cada rato"),
        (99, "espera_proveedor", "critica", "equipo", "La terminal de calidad no enciende"),
        (98, "cancelado", "media", "software", "El ERP no abre (ya funcionó, lo cancelo)"),
    ]
    items = [{
        "id": i, "sitio_id": 1, "folio": f"TICK-QRO-2026-{i:04d}", "usuario_id": 7,
        "usuario": persona, "categoria": cat, "descripcion_original": texto,
        "prioridad": prio, "estado": estado, "asignado_a": None,
        "asignado_usuario": None, "canal_resolucion": "tecnico",
        "indexado_kb": False, "creado_en": "2026-09-29T15:00:00Z",
        "vence_en": "2026-09-30T23:00:00Z", "fuera_horario": False,
        "comentarios": [], "adjuntos": [],
        "cancelado_en": "2026-09-29T16:00:00Z" if estado == "cancelado" else None,
    } for i, estado, prio, cat, texto in casos]
    for ticket in items:
        if ticket["estado"] == "cancelado":
            ticket["vence_en"] = None
    return {"items": items, "total": 47, "pagina": 1, "por_pagina": 20, "paginas": 3}


def _personas_de_muestra():
    """El panel de Personas, con la forma de `UsuarioAdminResponse`
    (api/cuentas.py). Una de las dos tiene revocada la prioridad alta, para
    ver la marca y el interruptor en los dos estados."""
    base = {"rol": "usuario", "activo": True, "estado_cuenta": "activa",
            "debe_cambiar_password": False, "ultimo_acceso": "2026-09-29T15:00:00Z",
            "creado_en": "2026-09-01T15:00:00Z", "codigo_expira": None,
            "numero_epp": "421", "datos_verificacion": ["numero_epp", "fecha_nacimiento"],
            "equipos_a_cargo": 0, "resguardos_pendientes": 0, "tickets_abiertos": 1,
            "sitio_id": 1, "plantas": [{"id": 1, "clave": "QRO", "nombre": "Planta de vista previa"}]}
    return [
        dict(base, id=21, nombre="Rosa Elena Campos", numero_empleado="30001",
             email=None, area="Producción", puede_usar_prioridad_alta=True),
        dict(base, id=22, nombre="Mario Ruiz Téllez", numero_empleado="30002",
             email=None, area="Almacén", puede_usar_prioridad_alta=False),
    ]


def _categoria(nombre, kb=0, soluciones=0, documentos=0, tickets=0,
               consultas=0, fallidas=0, estado="vacio"):
    return {"categoria": nombre, "conocimiento": kb + soluciones + documentos,
            "kb": kb, "soluciones": soluciones, "documentos": documentos,
            "tickets_resueltos": tickets, "consultas": consultas,
            "consultas_fallidas": fallidas, "estado": estado}


def _totales(cats):
    suma = lambda c: sum(x[c] for x in cats)
    return {"conocimiento": suma("conocimiento"), "kb": suma("kb"),
            "soluciones": suma("soluciones"), "documentos": suma("documentos"),
            "consultas": suma("consultas"), "consultas_fallidas": suma("consultas_fallidas"),
            "categorias_vacias": sum(1 for c in cats if c["conocimiento"] == 0)}


# --- Los tres estados que de verdad hay que poder mirar ------------------
#
# "vacio" es el primer día y el más fácil de pintar mal: una gráfica que omite
# lo que no tiene datos esconde justo el dato. "roto" junta todos los avisos a
# la vez, que es como se comprueba que la lista se lee y se prioriza bien.

_VACIO = [_categoria(n) for n in
          ("accesos", "equipo", "impresora", "otro", "red", "software")]

_MEDIAS = [
    _categoria("accesos", kb=3, soluciones=1, tickets=6, consultas=9, fallidas=1, estado="cubierto"),
    _categoria("equipo", tickets=2, consultas=11, fallidas=9, estado="hueco"),
    _categoria("impresora", kb=5, soluciones=1, documentos=1, tickets=14, consultas=16, fallidas=2, estado="cubierto"),
    _categoria("otro"),
    _categoria("red", kb=2, tickets=5, consultas=8, fallidas=5, estado="flojo"),
    _categoria("software", tickets=1, consultas=3, fallidas=3, estado="hueco"),
]

# --- Soluciones generales -------------------------------------------------
#
# La forma es la de `SolucionResponse` (app/api/soluciones.py). La pantalla se
# comporta distinto segun el `estado` de cada una: una publicada ofrece
# archivar, un borrador ofrece publicar, y un `descartado` con texto pinta el
# recuadro de "ya se probo y no era" —que es la parte que mas cuesta ver a
# mano, porque hace falta que la maquina lo haya escrito—.
_SOLUCIONES_MEDIAS = [
    {"id": 1, "titulo": "Raya negra vertical en las etiquetas de embarques",
     "categoria": "impresora", "estado": "publicada", "tickets_origen": 7,
     "redactada_por": "ollama", "revisada_por": 1,
     "veces_sugerida": 12, "veces_util": 9,
     "creado_en": "2026-09-02T10:00:00", "publicado_en": "2026-09-03T08:30:00",
     "contenido": ("1. Apague la impresora y abra la tapa del cabezal.\n"
                   "2. Limpie el cabezal con alcohol isopropilico y deje secar "
                   "dos minutos.\n"
                   "3. Si la raya sigue, el cabezal esta rayado: pida reemplazo "
                   "al proveedor."),
     "descartado": "Cambiar el ribbon. Se hizo tres veces y la raya volvio."},
    {"id": 2, "titulo": "El wifi del almacen se cae cada rato",
     "categoria": "red", "estado": "publicada", "tickets_origen": 5,
     "redactada_por": "gemini", "revisada_por": 1,
     "veces_sugerida": 8, "veces_util": 2,
     "creado_en": "2026-09-05T11:20:00", "publicado_en": "2026-09-06T09:00:00",
     "contenido": ("1. Mire en que pasillo se cae: el AP-4 cubre hasta el "
                   "rack 12 y no mas alla.\n"
                   "2. Si es mas alla del rack 12, no es una averia: falta "
                   "cobertura y hay que pedir un AP.\n"
                   "3. Si es en todo el almacen, reinicie el AP-4 desde el "
                   "panel y avise a redes."),
     "descartado": None},
    {"id": 3, "titulo": "El handheld del anden 3 no manda lecturas",
     "categoria": "equipo", "estado": "borrador", "tickets_origen": 3,
     "redactada_por": "ollama", "revisada_por": None,
     "veces_sugerida": 0, "veces_util": 0,
     "creado_en": "2026-09-15T16:40:00", "publicado_en": None,
     "contenido": ("1. Verifique que el handheld este emparejado con la base.\n"
                   "2. Revise la sesion del operador en el sistema."),
     "descartado": None},
    {"id": 4, "titulo": "El tablero de produccion no carga desde la actualizacion",
     "categoria": "software", "estado": "borrador", "tickets_origen": 4,
     "redactada_por": "ollama", "revisada_por": None,
     "veces_sugerida": 0, "veces_util": 0,
     "creado_en": "2026-09-16T12:05:00", "publicado_en": None,
     "contenido": "1. Limpie la cache del navegador.\n2. Vuelva a entrar.",
     "descartado": None},
]


# --- Métricas, estado del sistema y expediente -----------------------------
#
# Tres pantallas que hasta ahora se veían solo por su rama de error, porque el
# guion no conocía sus rutas y les contestaba `[]`. Las tres se caían con eso
# —«Algo se rompió en esta pantalla»— hasta que se les puso guarda de forma.
# Los campos de abajo son exactamente los que cada pantalla lee; si alguna deja
# de pintarse, es que el backend cambió y aquí no se enteró nadie.
_METRICAS = {
    "tickets": {
        "periodo_dias": 30, "tickets_total": 47, "tickets_abiertos": 9,
        "tickets_ultima_semana": 12, "tiempo_resolucion_promedio_min": 186,
        "tickets_periodo": 31, "tickets_cancelados": 4, "tickets_cancelados_periodo": 2,
        # **Porcentajes de 0 a 100, no fracciones.** `_porcentaje` del backend
        # ya multiplica por 100; escribirlos aquí como 0.23 hacía que la
        # pantalla enseñara «0.23 %» —casi cero— donde en realidad va 23 %.
        "tasa_deflexion": 23.4, "tasa_normalizacion": 81.0,
        "por_canal": {"tecnico": 31, "ia": 9, "checklist": 5, "kb": 2, "visual": 3},
        # Lista, no diccionario: `por_canal` es un diccionario y
        # `por_categoria` una lista de {categoria, total}. Confundirlos aquí
        # tumbó la pantalla en la propia vista previa, que es para lo que sirve.
        "por_categoria": [{"categoria": "impresora", "total": 14},
                          {"categoria": "red", "total": 11},
                          {"categoria": "equipo", "total": 9},
                          {"categoria": "software", "total": 7},
                          {"categoria": "accesos", "total": 6}],
    },
    "base_conocimiento": {
        "entradas_kb": 10, "tasa_utilidad": 70.8,
        "sugerencias_mostradas_semana": 24,
        "incidencias_resueltas_por_kb": 6,
        # El umbral sí es de 0 a 1: no sale de `_porcentaje`, es el ajuste
        # `KB_UMBRAL_SIMILITUD` tal cual. Conviven las dos escalas en la misma
        # pantalla, y por eso hay que mirar de dónde sale cada número.
        "umbral_actual": 0.75, "tickets_pendientes_indexar": 3,
    },
    "chatbot": {
        "sesiones_iniciadas": 38, "porcentaje_termino_en_ticket": 34.2,
        "precision_clasificacion": 86.2, "clasificaciones_comparables": 29,
        "umbral_confianza": 0.7,      # ajuste, de 0 a 1
    },
    # Las latencias son las medidas de verdad en esta planta, no inventadas:
    # ver la sección del gobernador de energía en DESPLIEGUE.md.
    "ollama": {"disponible": True,
               "latencias_ms": {"normalizacion": 850, "clasificacion": 680,
                                "asistencia": 7090, "embedding": 1020}},
    # Los ESP32 (desde 2026-10-05): uno de los cuatro sin reportar.
    "sensores": {"dispositivos": 4, "en_linea": 3, "alertas_periodo": 7,
                 "alertas_por_tipo": {"iot_umbral": 5, "iot_sin_senal": 2},
                 "alertas_pendientes": 2, "sin_senal_minutos": 15, "periodo_dias": 30},
}

# El directorio de documentos (2026-10-05): dos raíces con visibilidades
# distintas, una subcarpeta y archivos de varios tipos, nombres largos
# incluidos —son los que rompen una fila en el celular—.
_PLANTA_QRO = {"id": 1, "clave": "QRO", "nombre": "Planta de vista previa"}
_CARPETAS_RAIZ = [
    {"id": 1, "padre_id": None, "nombre": "Manuales de equipos", "descripcion": None, "profundidad": 1,
     "visibilidad": "todos", "creado_en": "2026-10-01T15:00:00Z", "actualizado_en": "2026-10-01T15:00:00Z",
     "subcarpetas": 1, "archivos": 3, "plantas": []},
    {"id": 2, "padre_id": None, "nombre": "Contratos con proveedores", "descripcion": None, "profundidad": 1,
     "visibilidad": "ti", "creado_en": "2026-10-02T15:00:00Z", "actualizado_en": "2026-10-02T15:00:00Z",
     "subcarpetas": 0, "archivos": 0, "plantas": []},
    {"id": 3, "padre_id": None, "nombre": "Formatos de la planta", "descripcion": None, "profundidad": 1,
     "visibilidad": "plantas", "creado_en": "2026-10-02T15:00:00Z", "actualizado_en": "2026-10-02T15:00:00Z",
     "subcarpetas": 0, "archivos": 0, "plantas": [_PLANTA_QRO]},
]
def _archivo_muestra(i, nombre, ext, tamano, version=1, en_linea=False, descripcion=None):
    return {"id": i, "carpeta_id": 1, "nombre": nombre, "extension": ext, "tipo_mime": "application/octet-stream",
            "tamano_bytes": tamano, "sha256": "0" * 64, "version": version, "descripcion": descripcion,
            "subido_por": {"id": 1, "nombre": "Vista previa"}, "creado_en": "2026-10-01T15:00:00Z",
            "actualizado_en": "2026-10-04T18:20:00Z", "en_linea": en_linea}
_DIRECTORIO_CARPETA = {
    "carpeta": dict(_CARPETAS_RAIZ[0], visibilidad_efectiva="todos", raiz_id=1),
    "migas": [{"id": 1, "nombre": "Manuales de equipos"}],
    "carpetas": [{"id": 4, "padre_id": 1, "nombre": "Impresoras Zebra de etiquetas", "descripcion": None,
                  "profundidad": 2, "visibilidad": None, "creado_en": "2026-10-01T15:00:00Z",
                  "actualizado_en": "2026-10-01T15:00:00Z", "subcarpetas": 0, "archivos": 2}],
    "archivos": [
        _archivo_muestra(11, "Manual de servicio HP LaserJet Enterprise M607 - procedimiento de cambio de fusor.pdf",
                         "pdf", 4_812_330, version=3, en_linea=True,
                         descripcion="La versión 3 corrige el torque de los tornillos del fusor."),
        _archivo_muestra(12, "Inventario de switches.xlsx", "xlsx", 48_210),
        _archivo_muestra(13, "foto-rack-principal.jpg", "jpg", 1_204_000, en_linea=True),
    ],
    "puede_editar": True,
}

_ALERTAS = [
    {"id": 9, "tipo": "iot_umbral", "titulo": "x", "detalle": None,
     "datos": {"dispositivo": "Cuarto de servidores", "magnitud": "temperatura", "valor": 31.4, "umbral": 28},
     "sitio": _PLANTA_QRO, "ticket_id": None, "dispositivo_id": 2, "creado_en": "2026-10-05T17:40:00Z",
     "atendida_en": None, "atendida_por": None, "atendida_por_nombre": None},
    {"id": 8, "tipo": "sla_vencido", "titulo": "x", "detalle": None,
     "datos": {"folio": "TICK-QRO-2026-0012", "vence_en": "2026-10-05T15:00:00Z"},
     "sitio": _PLANTA_QRO, "ticket_id": 101, "dispositivo_id": None, "creado_en": "2026-10-05T15:01:00Z",
     "atendida_en": None, "atendida_por": None, "atendida_por_nombre": None},
    {"id": 7, "tipo": "iot_sin_senal", "titulo": "x", "detalle": None,
     "datos": {"dispositivo": "Nave 2 — línea de empaque", "minutos": 42},
     "sitio": _PLANTA_QRO, "ticket_id": None, "dispositivo_id": 3, "creado_en": "2026-10-04T09:00:00Z",
     "atendida_en": "2026-10-04T09:30:00Z", "atendida_por": 1, "atendida_por_nombre": "Vista previa"},
]

_BITACORA = [
    {"id": 30, "accion": "archivo.reemplazado", "entidad": "archivo", "entidad_id": 11,
     "detalle": {"nombre": "Manual HP M607.pdf", "version": {"antes": 2, "despues": 3}},
     "ip": "100.64.0.12", "creado_en": "2026-10-05T16:10:00Z",
     "usuario": {"id": 1, "nombre": "Vista previa", "email": "vista@cgr.mx"}},
    {"id": 29, "accion": "ticket.estado", "entidad": "ticket", "entidad_id": 101,
     "detalle": {"estado": {"antes": "abierto", "despues": "en_proceso"}},
     "ip": "100.64.0.12", "creado_en": "2026-10-05T15:30:00Z",
     "usuario": {"id": 1, "nombre": "Vista previa", "email": "vista@cgr.mx"}},
    {"id": 28, "accion": "usuario.creado", "entidad": "usuario", "entidad_id": 4,
     "detalle": {"numero_empleado": "1234", "plantas": ["QRO"]},
     "ip": None, "creado_en": "2026-10-04T12:00:00Z",
     "usuario": {"id": 1, "nombre": "Vista previa", "email": "vista@cgr.mx"}},
]

_HORARIO = {"es_horario_laboral": True, "fuera_de_horario": False,
            "vuelven_hoy": None, "vuelven_manana": None, "proximo": None}

_ESTADO_SISTEMA = {
    "operativo": True,
    "horario": _HORARIO,
    "actividad_24h": {"tickets_creados": 6, "usuarios_activos": 14},
    "servicios": [
        {"nombre": "Base de datos", "clave": "db", "estado": "arriba",
         "critico": True, "detalle": "PostgreSQL con pgvector"},
        {"nombre": "Modelo local", "clave": "ollama", "estado": "arriba",
         "critico": False, "detalle": "qwen2.5:3b",
         "latencias_ms": {"normalizacion": 850, "clasificacion": 680,
                          "asistencia": 7090},
         # La cola, con la forma que devuelve `cola_ia.metricas()`. Con dos
         # rechazos puestos a propósito: es el caso que la pantalla tiene que
         # saber destacar, y el que no se puede reproducir a mano sin poner a
         # cuatro personas a preguntar a la vez.
         "cola": {
             "generacion": {"aforo": 1, "sala": 3, "en_curso": 1, "esperando": 2,
                            "admitidos": 41, "rechazados_sala": 2,
                            "rechazados_espera": 0, "espera_promedio_ms": 8400,
                            "espera_maxima_ms": 24000, "duracion_mediana_s": 7.1,
                            "espera_estimada_s": 14.2},
             "embeddings": {"aforo": 2, "sala": 8, "en_curso": 0, "esperando": 0,
                            "admitidos": 118, "rechazados_sala": 0,
                            "rechazados_espera": 0, "espera_promedio_ms": 120,
                            "espera_maxima_ms": 900, "duracion_mediana_s": 0.3,
                            "espera_estimada_s": 0.0},
         },
         "degradacion": "El asistente entrega extractos en vez de redactar."},
        {"nombre": "Gemini", "clave": "gemini", "estado": "sin_llave",
         "critico": False, "detalle": "gemini-2.0-flash",
         "latencias_ms": {"gemini": None},
         "degradacion": "Sin respaldo cuando el modelo local no alcanza."},
        {"nombre": "Certificado TLS", "clave": "certificado", "estado": "arriba",
         "critico": False, "detalle": "Vence en 312 días"},
    ],
}

_EXPEDIENTE = {
    "usuario": {"id": 1, "nombre": "Vista previa", "email": "vista@cgr.mx",
                "numero_empleado": "0001", "area": "Sistemas"},
    "equipos_a_cargo": [
        {"id": 3, "tipo": "laptop", "marca": "Dell", "modelo": "Latitude 5440",
         "numero_serie": "QRO-LT-0031", "estado": "asignado"},
    ],
    "resguardos": [
        {"id": 11, "folio": "RG-2026-0011", "estado": "pendiente_firma",
         "equipo": {"tipo": "laptop", "marca": "Dell", "modelo": "Latitude 5440",
                    "numero_serie": "QRO-LT-0031"},
         "entregado_en": "2026-09-10T09:00:00", "firmado_en": None,
         "devuelto_en": None},
        {"id": 7, "folio": "RG-2026-0007", "estado": "firmado",
         "equipo": {"tipo": "monitor", "marca": "HP", "modelo": "P24h",
                    "numero_serie": "QRO-MN-0087"},
         "entregado_en": "2026-06-02T11:20:00",
         "firmado_en": "2026-06-02T11:35:00", "devuelto_en": None},
    ],
    "documentos": [
        {"id": 4, "tipo": "carta_responsiva", "titulo": "Carta responsiva 2026",
         "creado_en": "2026-01-15T08:00:00", "vigente_hasta": "2026-12-31",
         "vencido": False},
        {"id": 2, "tipo": "politica_uso", "titulo": "Política de uso de equipo",
         "creado_en": "2025-02-01T08:00:00", "vigente_hasta": "2026-02-01",
         "vencido": True},
    ],
}


# --- Catálogo visual: las fotos, dibujadas aquí mismo ----------------------
#
# **Las imágenes se generan en código y no se guardan como archivos.** Un PNG
# de verdad en `scripts/` sería un binario en el repositorio que nadie sabría
# por qué está ahí, y la vista previa existe justamente para no depender de
# nada externo. Estas tres son suficientes para juzgar lo único que hay que
# juzgar aquí: si las tarjetas caben, si la foto se lee a ese tamaño y si los
# pasos se siguen en orden.


def _png(ancho, alto, pinta):
    """Un PNG de verdad, sin más dependencias que la biblioteca estándar.

    `pinta(x, y)` devuelve la terna RGB de cada píxel. Filtro 0 en cada fila,
    que es el mínimo que exige el formato.
    """
    filas = b"".join(
        b"\x00" + b"".join(bytes(pinta(x, y)) for x in range(ancho))
        for y in range(alto)
    )

    def trozo(tipo, datos):
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xffffffff))

    return (b"\x89PNG\r\n\x1a\n"
            + trozo(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(filas))
            + trozo(b"IEND", b""))


def _hoja_borrosa(x, y):
    """Texto desvanecido sobre fondo con bandas: la copia con poco tóner."""
    if 30 < y < 200 and 40 < x < 460 and (y // 14) % 3 != 2:
        gris = 150 + ((x * 7 + y * 3) % 40)
        return (gris, gris, gris)
    fondo = 245 - (18 if (y // 9) % 2 == 0 else 0)
    return (fondo, fondo, fondo - 4)


def _hoja_con_raya(x, y):
    """La misma hoja, legible, con una línea oscura vertical."""
    if 180 < x < 196:
        return (35, 35, 40)
    if 30 < y < 200 and 40 < x < 460 and (y // 14) % 3 != 2:
        return (60, 60, 66)
    return (247, 247, 244)


def _captura_senalada(x, y):
    """Una ventana de ajustes con el control que hay que tocar, en rojo."""
    if 20 < y < 60:
        return (37, 99, 235)
    if 120 < y < 160 and 40 < x < 300:
        return (220, 38, 38)
    if (y // 30) % 2 == 0 and 60 < x < 420:
        return (232, 234, 238)
    return (250, 250, 252)


# (ficha_id, imagen_id) -> bytes
IMAGENES_VISUALES = {
    (1, 11): _png(500, 230, _hoja_borrosa),
    (1, 12): _png(460, 240, _captura_senalada),
    (1, 13): _png(460, 240, _captura_senalada),
    (2, 21): _png(500, 230, _hoja_con_raya),
}

# --- Imágenes del conocimiento: pasos, base de conocimiento y soluciones ---
#
# Tres formas a propósito, porque son las tres que rompen un diseño de
# formas distintas: una captura de pantalla ancha (1280 px, mucho más que un
# teléfono), una foto vertical de teléfono y una pequeña. Si la galería o el
# visor se salen de la tarjeta en `/movil`, se ve con la primera.
def _captura_ancha(x, y):
    """Una ventana de configuración apaisada, con la casilla en rojo."""
    if y < 60:
        return (37, 99, 235)
    if 300 < y < 360 and 120 < x < 700:
        return (220, 38, 38)
    if (y // 40) % 2 == 0 and 80 < x < 1200:
        return (226, 230, 236)
    return (248, 249, 251)


def _foto_vertical(x, y):
    """La parte de atrás de un equipo, con el botón de reinicio marcado."""
    if 600 < y < 680 and 200 < x < 340:
        return (220, 38, 38)
    gris = 70 + ((x // 30 + y // 30) % 2) * 25
    return (gris, gris, gris + 8)


IMAGENES_CONOCIMIENTO = {
    501: _png(1280, 720, _captura_ancha),
    502: _png(540, 960, _foto_vertical),
    503: _png(460, 240, _captura_senalada),
}


def _breve(ident, pie=None):
    """La forma de `ImagenBreve` (app/schemas/imagenes.py)."""
    return {"id": ident, "orden": 1, "pie": pie, "nombre_original": f"captura-{ident}.png",
            "tipo_mime": "image/png", "tamano_bytes": len(IMAGENES_CONOCIMIENTO[ident]),
            "creado_en": "2026-10-02T15:00:00Z"}


_PASOS = [
    {"id": 31, "categoria": "impresora", "orden": 1, "pregunta_key": "custom.impresora.1",
     "pregunta_texto": "¿Tiene encendida la luz verde de la parte trasera?",
     "accion_si_no": "Si está apagada, mantenga pulsado el botón de reinicio cinco segundos.",
     "resuelve": True, "activo": True, "veces_resolvio": 3,
     "imagenes": [_breve(502, "El botón de reinicio, junto al conector de corriente")]},
    {"id": 32, "categoria": "impresora", "orden": 2, "pregunta_key": "custom.impresora.2",
     "pregunta_texto": "¿El controlador tiene desactivado el ahorro de tóner?",
     "accion_si_no": "Abra Preferencias de impresión y destilde «Ahorro de tóner».",
     "resuelve": True, "activo": True, "veces_resolvio": 0,
     "imagenes": [_breve(501, "Preferencias de impresión: la casilla está a la izquierda"),
                  _breve(503)]},
]

_KB = [
    {"id": 41, "titulo": "La Zebra imprime etiquetas en blanco",
     "contenido": "Recalibrar el sensor: con la impresora encendida, mantener pulsado PAUSE "
                  "y FEED hasta que parpadee dos veces.",
     "categoria": "impresora", "tags": None, "veces_sugerida": 4, "veces_util": 3,
     "ticket_origen_id": None, "tasa_utilidad": 75.0, "tiene_embedding": True,
     "imagenes": [_breve(501, "Panel frontal: PAUSE y FEED"), _breve(502)]},
]

# Un procedimiento de Soluciones generales con capturas, y la entrada de la
# base con las que hereda de su ticket de origen (enlazadas, de solo lectura).
_SOLUCIONES_MEDIAS[0]["imagenes"] = [_breve(501, "La tapa del cabezal, abierta"), _breve(503)]
_KB[0]["imagenes_ticket"] = [_breve(503, "Del ticket: así quedó el ajuste")]

_SOLUCION_TICKET = ("Se cambió el controlador por el de la marca y se desactivó el ahorro de "
                    "tóner en las preferencias de impresión. Se imprimió una prueba sin raya.")


_SOLUCION_BORROSA = ("1. Abra la bandeja 2 y saque el cartucho.\n"
                     "2. Agitelo en horizontal cinco veces.\n"
                     "3. Vuelva a meterlo hasta que haga clic.")

# Dos fichas y no una: la de arriba es el estado bueno —publicada, indexada,
# con pasos y con un diagnostico limpio— y la de abajo es el estado que hay que
# poder mirar, que es el que se pinta mal: borrador, sin indexar y con la
# alerta de "la reconocen y no les arregla".
_FICHAS_MEDIAS = [
    {"id": 1, "titulo": "La copia sale borrosa",
     "sintoma": "El texto sale desvanecido y con el fondo gris, como si faltara toner.",
     "solucion": _SOLUCION_BORROSA,
     "descartado": "Se cambio el cartucho completo y siguio igual: no era el toner.",
     "frases": "sale borroso, se ve despintado, queda tenue",
     "categoria": "impresora", "estado": "publicada", "indexada": True,
     "veces_mostrada": 24, "veces_confirmada": 19, "veces_descartada": 5,
     "veces_resuelta": 17,
     "creado_en": "2026-08-30T10:00:00", "actualizado_en": None,
     "autor_nombre": "TI", "imagenes": [
         {"id": 11, "rol": "sintoma", "orden": 1, "pie": "Asi se ve la hoja",
          "nombre_original": "borrosa.png", "tamano_bytes": 40321},
         {"id": 12, "rol": "solucion", "orden": 1,
          "pie": "Destilde «Ahorro de toner» y acepte",
          "nombre_original": "paso1.png", "tamano_bytes": 30100},
         {"id": 13, "rol": "solucion", "orden": 2, "pie": "Despues, Calidad -> Normal",
          "nombre_original": "paso2.png", "tamano_bytes": 28110}]},
    {"id": 2, "titulo": "Raya negra vertical en todas las hojas",
     "sintoma": "Una linea oscura de arriba abajo, siempre en el mismo sitio de la hoja.",
     "solucion": "Es el rodillo de transferencia. Levante la tapa trasera y limpielo con un pano seco.",
     "descartado": None, "frases": "sale una raya, linea oscura vertical",
     "categoria": "impresora", "estado": "borrador", "indexada": False,
     "veces_mostrada": 12, "veces_confirmada": 9, "veces_descartada": 3,
     "veces_resuelta": 2,
     "creado_en": "2026-09-14T12:00:00", "actualizado_en": None,
     "autor_nombre": "TI", "imagenes": [
         {"id": 21, "rol": "sintoma", "orden": 1, "pie": "La raya, a 4 cm del borde",
          "nombre_original": "raya.png", "tamano_bytes": 39990}]},
]

# Lo que el chat y el formulario reciben al reconocer. Sin la solucion: esa
# llega al confirmar, cuando la persona ya senalo cual es la suya.
_CANDIDATAS = [
    {"ficha_id": f["id"], "titulo": f["titulo"], "categoria": f["categoria"],
     "sintoma": f["sintoma"], "similitud": s,
     "imagen_id": f["imagenes"][0]["id"], "pie": f["imagenes"][0]["pie"],
     "imagenes": [{"imagen_id": f["imagenes"][0]["id"], "pie": f["imagenes"][0]["pie"]}]}
    for f, s in zip(_FICHAS_MEDIAS, (0.80, 0.71))
]

_CONFIRMADA = {
    "ficha_id": 1, "titulo": _FICHAS_MEDIAS[0]["titulo"], "categoria": "impresora",
    "solucion": _SOLUCION_BORROSA, "descartado": _FICHAS_MEDIAS[0]["descartado"],
    "pasos": [{"imagen_id": 12, "pie": "Destilde «Ahorro de toner» y acepte", "orden": 1},
              {"imagen_id": 13, "pie": "Despues, Calidad -> Normal", "orden": 2}],
}


ESTADOS = {
    "vacio": {
        "panorama": {"dias": 30, "categorias": _VACIO, "total": _totales(_VACIO)},
        "aprendizaje": {"dias": 30, "etapas": [
            {"clave": "resueltos", "valor": 0, "de": None},
            {"clave": "indexados", "valor": 0, "de": 0, "atasco": False},
            {"clave": "procedimientos", "valor": 0, "de": 0, "atasco": False},
            {"clave": "temas", "valor": 0, "de": 0}],
            "pendientes_indexar": 0, "pendiente_de_revision": 0,
            "temas_pendientes": 0, "sin_vector": 0,
            "realimentacion": {"votados": 0, "utiles": 0, "ratio": None},
            "consultas": {"total": 0, "fallidas": 0, "ratio_fallo": None},
            "avisos": []},
        "consultas": {"dias": 30, "por_origen": {}, "consultas": []},
        "soluciones": [],
        "candidatos": {"total": 0, "minimo_configurado": 0, "grupos": []},
        "fichas": [],
    },
    "medias": {
        "panorama": {"dias": 30, "categorias": _MEDIAS, "total": _totales(_MEDIAS)},
        "aprendizaje": {"dias": 30, "etapas": [
            {"clave": "resueltos", "valor": 28, "de": None},
            {"clave": "indexados", "valor": 10, "de": 28, "atasco": False},
            {"clave": "procedimientos", "valor": 2, "de": 10, "atasco": False},
            {"clave": "temas", "valor": 1, "de": 4}],
            "pendientes_indexar": 3, "pendiente_de_revision": 2,
            "temas_pendientes": 3, "sin_vector": 1,
            "realimentacion": {"votados": 24, "utiles": 17, "ratio": 0.708},
            "consultas": {"total": 47, "fallidas": 20, "ratio_fallo": 0.426},
            "avisos": [{"tipo": "categoria_dudosa", "kb_id": 2,
                        "titulo": "No deja entrar al portal y dice que contacte a TI",
                        "etiqueta": "impresora", "sugerida": "accesos",
                        "confianza": 0.85}]},
        "consultas": {"dias": 30,
            "por_origen": {"directo": 9, "ollama": 12, "gemini": 2,
                           "extractos": 6, "sin_fundamento": 14},
            "consultas": [
             {"id": 1, "pregunta": "el escaner de codigo de barras del anden 3 pita pero no manda nada al sistema y la pantalla del handheld se queda congelada",
              "categoria": "equipo", "pasajes": 0, "mejor_similitud": None,
              "mejor_fuente": None, "origen": "sin_fundamento",
              "duracion_ms": 312, "creado_en": "2026-09-17T09:12:00"},
             {"id": 2, "pregunta": "la impresora de embarques saca una raya negra vertical en las etiquetas",
              "categoria": "impresora", "pasajes": 1, "mejor_similitud": 0.81,
              "mejor_fuente": "ticket", "origen": "directo",
              "duracion_ms": 140, "creado_en": "2026-09-17T09:05:00"},
             {"id": 3, "pregunta": "no me carga el tablero de produccion desde la actualizacion del lunes",
              "categoria": "software", "pasajes": 2, "mejor_similitud": 0.66,
              "mejor_fuente": "documento", "origen": "extractos",
              "duracion_ms": 14820, "creado_en": "2026-09-17T08:51:00"},
             {"id": 4, "pregunta": "se cae el wifi en el almacen cada rato",
              "categoria": "red", "pasajes": 3, "mejor_similitud": 0.74,
              "mejor_fuente": "solucion_general", "origen": "ollama",
              "duracion_ms": 9260, "creado_en": "2026-09-17T08:40:00"}]},
        "soluciones": _SOLUCIONES_MEDIAS,
        "candidatos": {"total": 3, "minimo_configurado": 3, "grupos": [
            {"titulo": "La impresora de embarques saca una raya negra vertical",
             "categoria": "impresora", "ocurrencias": 7},
            {"titulo": "Se cae el wifi en el almacen cada rato",
             "categoria": "red", "ocurrencias": 5},
            {"titulo": "El handheld del anden 3 no manda lecturas al sistema",
             "categoria": "equipo", "ocurrencias": 3}]},
        "fichas": _FICHAS_MEDIAS,
    },
}

# "roto": el mismo panorama a medias, pero con la tubería cortada y todos los
# avisos disparados a la vez. Es el estado que más cuesta reproducir de verdad
# y el que más importa que se lea bien.
ESTADOS["roto"] = json.loads(json.dumps(ESTADOS["medias"]))
ESTADOS["roto"]["aprendizaje"].update({
    "etapas": [{"clave": "resueltos", "valor": 31, "de": None},
               {"clave": "indexados", "valor": 0, "de": 31, "atasco": True},
               {"clave": "procedimientos", "valor": 0, "de": 0, "atasco": False},
               {"clave": "temas", "valor": 0, "de": 5}],
    "pendientes_indexar": 31, "sin_vector": 8, "pendiente_de_revision": 4,
    "temas_pendientes": 5,
    "realimentacion": {"votados": 30, "utiles": 4, "ratio": 0.133},
})
# Nada publicado y cuatro borradores parados, con nueve problemas ya repetidos
# esperando procedimiento: el caso en que la pantalla tiene que empujar a
# revisar, no a redactar más.
ESTADOS["roto"]["soluciones"] = [
    dict(s, id=100 + i, estado="borrador")
    for i, s in enumerate(_SOLUCIONES_MEDIAS[:2] * 2)
]
ESTADOS["roto"]["candidatos"] = {
    "total": 9, "minimo_configurado": 3,
    "grupos": ESTADOS["medias"]["candidatos"]["grupos"] + [
        {"titulo": "No deja entrar al portal y pide contactar a TI",
         "categoria": "accesos", "ocurrencias": 6}],
}


# --- El asistente del formulario de tickets ------------------------------
#
# La escalera de `AsistenteService` tiene cinco salidas y cada una se pinta
# distinta. Las dos ultimas —`extractos` y `sin_fundamento`— son las mas
# comunes desde que la recuperacion exige mas a un pasaje solitario, y son
# justo las que menos se ven al probar a mano, porque hace falta preguntar algo
# que el portal NO sepa.
#
# Cada POST a /consultar devuelve la siguiente de la lista, asi que escribiendo
# varias veces en el formulario se recorren todas en orden.

_FUENTE = {
    "fuente": "ticket", "referencia_id": 12,
    "titulo": "Impresora Zebra saca la etiqueta con una raya negra",
    "texto": ("La raya negra a lo largo de la etiqueta es el cabezal sucio, no "
              "un cartucho gastado. Se apaga la impresora, se abre la tapa y se "
              "limpia el cabezal con una torunda con alcohol isopropilico."),
    "similitud": 0.81, "categoria": "impresora",
    "descartado": "Se cambio el ribbon dos veces y no era eso.",
}

# En "roto" el catalogo tambien falla, y falla de las dos maneras que hay que
# poder mirar: una ficha publicada que se quedo sin vector —solo se halla por
# sus frases literales— y otra que se ensena mucho y no reconoce casi nadie.
ESTADOS["roto"]["fichas"] = json.loads(json.dumps(_FICHAS_MEDIAS))
ESTADOS["roto"]["fichas"][0].update({"indexada": False, "veces_confirmada": 4,
                                     "veces_resuelta": 0})
ESTADOS["roto"]["fichas"][1].update({"estado": "publicada", "veces_mostrada": 30,
                                     "veces_confirmada": 2, "veces_resuelta": 1})

RESPUESTAS_ASISTENTE = [
    {"respuesta": _FUENTE["texto"], "origen": "directo", "fundamentada": True,
     "fuentes": [_FUENTE], "consumo": None, "siguiente_paso": "listo",
     "traza": "vista01"},
    {"respuesta": ("1. Apague la impresora y abra la tapa.\n"
                   "2. Limpie el cabezal con alcohol isopropilico y deje secar "
                   "dos minutos.\n3. Si la raya sigue, el cabezal esta rayado: "
                   "pida reemplazo al proveedor.\n\nYa se probo y no era: "
                   "cambiar el ribbon."),
     "origen": "ollama", "fundamentada": True, "fuentes": [_FUENTE],
     "consumo": None, "siguiente_paso": "listo", "traza": "vista02"},
    {"respuesta": None, "origen": "extractos", "fundamentada": True,
     "fuentes": [_FUENTE, dict(_FUENTE, referencia_id=19, similitud=0.66,
                               fuente="documento",
                               titulo="Mantenimiento preventivo de etiquetadoras",
                               descartado=None)],
     "consumo": None, "siguiente_paso": "listo", "traza": "vista03"},
    {"respuesta": None, "origen": "sin_fundamento", "fundamentada": False,
     "fuentes": [], "consumo": None, "siguiente_paso": "levantar_ticket",
     "traza": "vista04"},
]


def _extraer_dist(destino: str) -> None:
    """Saca el `dist` ya construido de la imagen del frontend."""
    cid = subprocess.run(["docker", "create", IMAGEN],
                         capture_output=True, text=True, check=True).stdout.strip()
    try:
        subprocess.run(["docker", "cp", f"{cid}:/usr/share/nginx/html/.", destino],
                       check=True, capture_output=True)
    finally:
        subprocess.run(["docker", "rm", cid], capture_output=True)


def main() -> int:
    # **Una línea, un vaciado.** Python usa búfer de bloque cuando la salida no
    # es una terminal, así que redirigiendo a un archivo —o corriendo esto en
    # segundo plano— el rótulo de arranque y, peor, el informe de rutas no
    # cubiertas del final se quedaban en el búfer y no llegaban nunca. Un
    # informe que no se lee no sirve de nada, y este existe justo para que no
    # se den por buenas partes de pantalla que el guion se invento.
    sys.stdout.reconfigure(line_buffering=True)

    # **Las dos formas de parar pasan por el mismo `finally`.**
    #
    # El informe de rutas no cubiertas se imprime al salir, y salir dependía de
    # que `serve_forever()` levantara `KeyboardInterrupt`. Comprobado: no lo
    # hace de forma fiable —ni con SIGTERM, ni con SIGINT cuando el proceso no
    # tiene terminal de control—, así que el guion se moría de golpe y el
    # informe no se escribía nunca. Y el «Ctrl+C para parar» del rótulo
    # prometía algo que no siempre cumplía.
    #
    # Levantarla a mano desde el manejador quita la duda: parar por donde sea
    # pasa por el mismo camino de salida.
    def _parar(*_):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)

    estado = (sys.argv[1] if len(sys.argv) > 1 else "medias").lower()
    if estado not in ESTADOS:
        print(f"Estado desconocido: {estado}. Use uno de: {', '.join(ESTADOS)}")
        return 2

    datos = ESTADOS[estado]
    raiz = tempfile.mkdtemp(prefix="vista-portal-")

    # **Se prefiere el `dist` del disco, y se dice cuál se está sirviendo.**
    #
    # Antes esto sacaba siempre el `dist` de la imagen, y ahí hay una trampa
    # silenciosa: quien acaba de tocar una pantalla y levanta la vista previa
    # está mirando la compilación **anterior**, sin que nada se lo diga, y
    # concluye que su cambio no hizo nada. Compilar el frontend no necesita
    # reconstruir la imagen ni tener npm en el host:
    #
    #     docker run --rm -v "$PWD/frontend":/app -w /app \
    #       -u "$(id -u):$(id -g)" node:20-alpine npx vite build
    #
    # Si no hay `dist` en el disco se sigue sacando de la imagen, que es el
    # caso de quien solo quiere mirar lo que está desplegado.
    local = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if (local / "index.html").exists():
        print(f"Sirviendo el dist del disco: {local}")
        shutil.copytree(local, raiz, dirs_exist_ok=True)
    else:
        try:
            print(f"No hay frontend/dist; extrayendo de {IMAGEN}...")
            _extraer_dist(raiz)
        except subprocess.CalledProcessError:
            shutil.rmtree(raiz, ignore_errors=True)
            print(f"No se pudo leer la imagen {IMAGEN}.\n"
                  f"Constrúyala primero:  docker compose build frontend")
            return 1

    rutas = {
        "/api/auth/me": USUARIO,
        "/api/tickets": _tickets_de_muestra(),
        "/api/admin/usuarios": _personas_de_muestra(),
        # El de la vista previa es su dueño: así se ve el botón de cancelar.
        "/api/tickets/101": dict(_tickets_de_muestra()["items"][0], usuario_id=USUARIO["id"]),
        "/api/admin/conciencia/panorama": datos["panorama"],
        "/api/admin/conciencia/aprendizaje": datos["aprendizaje"],
        "/api/admin/soluciones": datos["soluciones"],
        "/api/admin/soluciones/candidatos": datos["candidatos"],
        "/api/metricas": _METRICAS,
        "/api/admin/estado/sistema": _ESTADO_SISTEMA,
        "/api/expediente/mio": _EXPEDIENTE,
        "/api/estado/horario": _HORARIO,
        # El chat se dibuja solo si esto dice que Ollama esta vivo. Sin ello no
        # hay manera de mirar el reconocimiento visual, que vive dentro.
        "/api/chat/estado": {"disponible": True, "max_intercambios": 3},
        "/api/admin/visual": datos["fichas"],
        # Imágenes del conocimiento. Los pasos que ve quien levanta un ticket
        # son los mismos que administra TI, sin los dados de baja.
        "/api/admin/pasos": _PASOS,
        "/api/checklists": _PASOS,
        "/api/admin/kb": _KB,
        # Un ticket ya resuelto, con las capturas de la solución, del que la
        # vista previa es dueña: así se ve lo que lee quien lo reportó.
        "/api/tickets/102": dict(_tickets_de_muestra()["items"][0], id=102,
                                 folio="TICK-QRO-2026-0102", usuario_id=USUARIO["id"],
                                 estado="resuelto", solucion=_SOLUCION_TICKET,
                                 resuelto_en="2026-09-30T12:00:00Z", vence_en=None,
                                 imagenes_solucion=[
                                     _breve(501, "Preferencias de impresión, ya corregidas"),
                                     _breve(502, "El controlador nuevo instalado")]),
        # Una sola planta: el caso de hoy, en el que Personas tiene que decir
        # cómo se reparten varias.
        "/api/directorio/raiz": {"carpeta": None, "migas": [], "carpetas": _CARPETAS_RAIZ,
                                 "archivos": [], "puede_editar": True},
        "/api/directorio/carpetas/1": _DIRECTORIO_CARPETA,
        "/api/directorio/arbol": [{k: c[k] for k in ("id", "padre_id", "nombre", "profundidad", "visibilidad")}
                                  for c in _CARPETAS_RAIZ + _DIRECTORIO_CARPETA["carpetas"]],
        "/api/directorio/papelera": [
            {"tipo": "archivo", "id": 20, "nombre": "Manual viejo.pdf", "ubicacion": ["Manuales de equipos"],
             "eliminado_en": "2026-10-03T12:00:00Z", "eliminado_por": "Vista previa",
             "purga_en": "2026-11-02T12:00:00Z", "restaurable": True, "tamano_bytes": 120000, "extension": "pdf"}],
        "/api/admin/alertas": _ALERTAS,
        "/api/admin/alertas/resumen": {"pendientes": 2, "por_tipo": {"iot_umbral": 1, "sla_vencido": 1}},
        "/api/auditoria": _BITACORA,
        "/api/auditoria/opciones": {"acciones": ["archivo.reemplazado", "ticket.estado", "usuario.creado"],
                                    "entidades": ["archivo", "ticket", "usuario"],
                                    "personas": [{"id": 1, "nombre": "Vista previa"}]},
        "/api/sitios": [{"id": 1, "clave": "QRO", "nombre": "Planta de vista previa",
                         "pais": "México", "activo": True}],
    }
    # Rutas que se pidieron y este guion no conoce. Se anotan para decirlo al
    # final: ver mas abajo por que.
    sin_cubrir = {}

    class Manejador(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=raiz, **k)

        def log_message(self, *a):
            pass

        def _json(self, cuerpo):
            crudo = json.dumps(cuerpo).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(crudo)))
            self.end_headers()
            self.wfile.write(crudo)

        def do_POST(self):
            """Las llamadas del asistente. Rotan por las cuatro salidas."""
            largo = int(self.headers.get("Content-Length") or 0)
            crudo = self.rfile.read(largo) if largo else b""
            try:
                cuerpo = json.loads(crudo or b"{}")
            except ValueError:
                cuerpo = {}
            ruta = self.path.split("?")[0]
            if ruta == "/api/conciencia/consultar":
                i = turno["n"] % len(RESPUESTAS_ASISTENTE)
                turno["n"] += 1
                return self._json(RESPUESTAS_ASISTENTE[i])

            # --- Catalogo visual ---
            #
            # Se mira lo que se escribio para poder enseñar **los dos** caminos
            # sin tocar codigo: una frase con "borros" o "raya" activa las
            # fotos; cualquier otra sigue de largo, que es lo que hace el
            # portal de verdad con "no manda a imprimir".
            visual = bool(datos["fichas"]) and any(
                t in (cuerpo.get("texto") or cuerpo.get("mensaje") or "").lower()
                for t in ("borros", "raya", "linea", "línea", "manch")
            )
            if ruta == "/api/visual/reconocer":
                return self._json({"activado": visual,
                                   "motivo": "apariencia" if visual else "ausencia_de_funcion",
                                   "candidatas": _CANDIDATAS if visual else []})
            if ruta == "/api/admin/visual/probar":
                return self._json({"activado": visual,
                                   "motivo": "apariencia" if visual else "ausencia_de_funcion",
                                   "candidatas": _CANDIDATAS if visual else [],
                                   "umbral": 0.65})
            if ruta == "/api/visual/confirmar":
                return self._json(_CONFIRMADA)
            if ruta in ("/api/visual/descartar", "/api/visual/resultado"):
                return self._json({"anotadas": 1})
            if ruta == "/api/chat/mensaje":
                texto = cuerpo.get("mensaje") or ""
                if visual and not cuerpo.get("omitir_visual"):
                    return self._json({"sesion_id": 1, "accion": "reconocer_imagen",
                                       "fichas": _CANDIDATAS, "fuentes": [],
                                       "intercambios": 1, "descripcion_sugerida": texto,
                                       "categorias": []})
                return self._json({"sesion_id": 1, "accion": "pedir_categoria",
                                   "fichas": [], "fuentes": [], "intercambios": 1,
                                   "descripcion_sugerida": texto,
                                   "categorias": ["impresora", "red", "equipo",
                                                  "software", "accesos", "otro"]})
            return self._json({})

        def do_GET(self):
            ruta = self.path.split("?")[0]
            if ruta in rutas:
                return self._json(rutas[ruta])
            if ruta.startswith("/api/admin/conciencia/consultas"):
                return self._json(datos["consultas"])
            if ruta.startswith("/api/visual/fichas/"):
                return self._imagen_visual(ruta)
            if ruta.startswith("/api/imagenes/"):
                return self._imagen_conocimiento(ruta)
            if ruta.startswith("/api/"):
                # Cualquier otra llamada: lista vacía, para que la pantalla no
                # se quede cargando.
                #
                # **Pero se anota.** Una lista vacía inventada se ve igual que
                # un portal sin datos, así que sin este apunte no hay manera de
                # distinguir "esta pantalla está bien y no hay nada" de "esta
                # pantalla pide algo que el guion no sabe responder" — y lo
                # segundo se lee como lo primero, que es justo la clase de
                # mentira que esta herramienta existe para no contar.
                #
                # Además: devolver `[]` a un endpoint que en realidad contesta
                # un objeto es un cuerpo con la forma equivocada. Eso ya pasó
                # con `/admin/soluciones/candidatos`, y así se ve en el aviso.
                sin_cubrir[ruta] = sin_cubrir.get(ruta, 0) + 1
                return self._json([])
            if ruta == "/movil":
                return self._movil()
            # SPA: una ruta sin extensión es del enrutador, no un archivo.
            if "." not in os.path.basename(ruta):
                return self._index()
            return super().do_GET()

        def _imagen_conocimiento(self, ruta):
            """`/api/imagenes/{id}` es el archivo; `/api/imagenes/{tipo}/{id}`,
            la lista de un dueño (la pide el asistente para sus fuentes)."""
            partes = ruta.strip("/").split("/")
            if len(partes) == 4:
                return self._json([_breve(503)] if partes[2] == "kb" else [])
            try:
                imagen = IMAGENES_CONOCIMIENTO.get(int(partes[2]))
            except (IndexError, ValueError):
                imagen = None
            if imagen is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(imagen)))
            self.end_headers()
            self.wfile.write(imagen)

        def _imagen_visual(self, ruta):
            """La foto de una ficha, dibujada al vuelo.

            Va por la API autenticada como en el portal de verdad —el navegador
            no manda el token en un `<img src>`, asi que el frontend la
            descarga y la enseña desde un blob—. Aqui no hay token que valga,
            pero la ruta tiene que ser la misma o el componente no la pide.
            """
            partes = ruta.strip("/").split("/")
            try:
                clave = (int(partes[3]), int(partes[5]))
            except (IndexError, ValueError):
                clave = None
            imagen = IMAGENES_VISUALES.get(clave)
            if imagen is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(imagen)))
            self.end_headers()
            self.wfile.write(imagen)

        def _movil(self):
            """La misma pantalla dentro de un marco del ancho de un teléfono.

            **Por qué un marco y no encoger la ventana.** Redimensionar el
            navegador no siempre se puede —una ventana maximizada en Windows
            ignora la petición, y por control remoto no hay forma de
            arreglarlo—, y sin poder estrecharla no hay manera de ver si algo
            se amontona o se sale. Un `iframe` de 412 px sí tiene su propio
            ancho de ventana, así que las reglas `@media` se aplican de verdad:
            lo que se ve aquí es lo que ve un teléfono.

            412x915 es un Pixel corriente. Se ponen dos anchos porque los
            problemas no aparecen en el mismo: a 412 se amontona, a 360 se
            desborda.
            """
            from urllib.parse import parse_qs, urlparse
            consulta = parse_qs(urlparse(self.path).query)
            destino = (consulta.get("r") or ["/conciencia"])[0]
            if not destino.startswith("/"):
                destino = "/" + destino
            marcos = "".join(
                f'<figure><figcaption>{ancho}&times;915</figcaption>'
                f'<iframe src="{destino}" width="{ancho}" height="915"></iframe>'
                '</figure>'
                for ancho in (412, 360)
            )
            html = (
                "<!doctype html><meta charset='utf-8'>"
                f"<title>{destino} en el celular</title>"
                "<style>"
                "body{margin:0;padding:18px;background:#111;color:#ccc;"
                "font:13px system-ui,sans-serif;display:flex;gap:22px;"
                "align-items:flex-start;flex-wrap:wrap}"
                "figure{margin:0}"
                "figcaption{padding:0 0 7px;letter-spacing:.08em;"
                "text-transform:uppercase;font-size:11px;color:#888}"
                "iframe{border:1px solid #333;border-radius:12px;background:#000}"
                "</style>" + marcos
            )
            crudo = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(crudo)))
            self.end_headers()
            self.wfile.write(crudo)

        def _index(self):
            """El `index.html` con la sesión ya puesta.

            Se inyecta **antes** del `<script>` de la aplicación, no después:
            `AuthContext` lee `localStorage` en el primer render, y si para
            entonces no hay nada, el enrutador manda a /login y ya no vuelve.
            """
            with open(os.path.join(raiz, "index.html"), encoding="utf-8") as f:
                html = f.read()
            sesion = (
                "<script>"
                "localStorage.setItem('portal_tickets_token','vista-previa');"
                f"localStorage.setItem('portal_tickets_user',{json.dumps(json.dumps(USUARIO))});"
                "</script>"
            )
            html = html.replace("</head>", sesion + "</head>", 1)
            crudo = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(crudo)))
            self.end_headers()
            self.wfile.write(crudo)

    # Cuenta compartida para rotar las respuestas del asistente.
    turno = {"n": 0}

    socketserver.TCPServer.allow_reuse_address = True
    print(f"\n  Estado: {estado}")
    print(f"  Abra:   http://localhost:{PUERTO}/conocimiento")
    print(f"          http://localhost:{PUERTO}/new-ticket  "
          f"(el asistente rota por sus {len(RESPUESTAS_ASISTENTE)} salidas)")
    print(f"          http://localhost:{PUERTO}/conocimiento/procedimientos")
    print(f"          http://localhost:{PUERTO}/conocimiento/catalogo")
    print(f"          http://localhost:{PUERTO}/documentos/archivos/1   (directorio)")
    print(f"          http://localhost:{PUERTO}/sistema/metricas")
    print("\n  Las fotos: escriba «sale borroso» en el chat de abajo a la derecha,")
    print("  o en la descripción de /new-ticket.")
    print(f"\n  En el celular, sin encoger la ventana:")
    print(f"          http://localhost:{PUERTO}/movil?r=/conocimiento   (412 y 360 px)")
    print(f"          http://localhost:{PUERTO}/movil?r=/conocimiento/catalogo")
    print(f"          http://localhost:{PUERTO}/movil?r=/tickets/102   (solución con capturas)")
    print(f"          http://localhost:{PUERTO}/movil?r=/temas         (pasos y base de conocimiento)")
    print(f"          http://localhost:{PUERTO}/movil?r=/soluciones    (procedimientos con capturas)")
    print("\n  La sesión se inyecta sola; no hace falta iniciarla.")
    print("  Ctrl+C para parar.\n")
    try:
        with socketserver.TCPServer(("0.0.0.0", PUERTO), Manejador) as servidor:
            servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        shutil.rmtree(raiz, ignore_errors=True)
        if sin_cubrir:
            print("\n  Rutas que se pidieron y este guion NO conoce:")
            for ruta, veces in sorted(sin_cubrir.items()):
                print(f"    {ruta}  ({veces})")
            print("  A todas se les contestó `[]`. Lo que se vio en esas "
                  "partes de la pantalla\n  es invento del guion, no del "
                  "portal: no lo dé por bueno. Si esa\n  pantalla importa, "
                  "añada la ruta arriba con la forma real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
