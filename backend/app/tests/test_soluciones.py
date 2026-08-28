"""Soluciones generales: de muchos tickets, un procedimiento.

Dos cosas se prueban aquí, y la segunda importa más que la primera:

  1. Que agrupe bien los tickets del mismo problema.
  2. Que **nada llegue a contestarle a nadie sin que una persona lo firme**.
     Un borrador sin revisar no aparece en ninguna búsqueda.
"""

import pytest

from app.core.config import settings
from app.models import BaseConocimiento, SolucionGeneral
from app.services.soluciones_service import SolucionesService


def token(client, identificador="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": password})
    return r.json()["access_token"]


def cab(client, identificador="admin@test.com"):
    return {"Authorization": f"Bearer {token(client, identificador=identificador)}"}


# Contenido realista de una entrada de la base de conocimiento. Medir el
# anclaje contra un extracto de cuatro palabras da numeros que no se parecen a
# los de produccion.
SOLUCION_REAL = (
    "impresora\n"
    "La impresora del almacen saca una raya negra vertical en todas las hojas.\n"
    "Se limpio el rodillo de transferencia con un pano seco y sin solvente. La "
    "raya desaparecio de inmediato. Si vuelve en menos de un mes, el rodillo ya "
    "esta gastado y hay que pedir el repuesto."
)


def entrada(db_session, titulo, contenido, vector, descartado=None, sitio_id=1):
    fila = BaseConocimiento(
        sitio_id=sitio_id, titulo=titulo, contenido=contenido,
        categoria="impresora", embedding=vector, descartado=descartado,
    )
    db_session.add(fila)
    db_session.commit()
    return fila


def vector(semilla: float):
    """Vector con una dirección dominante, para controlar el parecido."""
    v = [0.01] * 768
    v[int(semilla * 100) % 768] = 1.0
    return v


# ----------------------------------------------------------------------
# Agrupar
# ----------------------------------------------------------------------
def test_tres_tickets_del_mismo_problema_hacen_un_grupo(db_session):
    igual = vector(0.1)
    for i in range(3):
        entrada(db_session, f"Raya negra {i}", SOLUCION_REAL, igual)

    grupos = SolucionesService.agrupar(db_session, 1)

    assert len(grupos) == 1
    assert grupos[0]["ocurrencias"] == 3


def test_un_caso_suelto_no_es_un_patron(db_session):
    entrada(db_session, "Algo que pasó una vez", "Se resolvió así", vector(0.2))

    assert SolucionesService.agrupar(db_session, 1) == []


def test_problemas_distintos_no_se_mezclan(db_session):
    """Juntar cosas distintas produce procedimientos que no sirven para ninguna."""
    for i in range(3):
        entrada(db_session, f"Impresora {i}", "rodillo", vector(0.1))
    for i in range(3):
        entrada(db_session, f"Red {i}", "switch", vector(0.9))

    grupos = SolucionesService.agrupar(db_session, 1)

    assert len(grupos) == 2
    assert all(g["ocurrencias"] == 3 for g in grupos)


def test_el_minimo_es_configurable(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SOLUCION_GENERAL_MIN_TICKETS", 2)
    for i in range(2):
        entrada(db_session, f"Raya {i}", "rodillo", vector(0.1))

    assert len(SolucionesService.agrupar(db_session, 1)) == 1


# ----------------------------------------------------------------------
# Redactar
# ----------------------------------------------------------------------
def test_el_borrador_junta_los_descartes_de_todos(db_session, monkeypatch):
    """Lo que se probó en cualquiera de los tickets sirve para todos."""
    igual = vector(0.1)
    entrada(db_session, "Raya 1", SOLUCION_REAL, igual,
            descartado="Se cambió el tóner y no era")
    entrada(db_session, "Raya 2", SOLUCION_REAL, igual,
            descartado="Se cambió el cable y no era")
    entrada(db_session, "Raya 3", SOLUCION_REAL, igual)

    monkeypatch.setattr("app.services.soluciones_service.ollama.responder_texto",
                        lambda *a, **k: ("SÍNTOMA: raya negra vertical en todas las hojas.\n"
                                    "CAUSA MÁS COMÚN: rodillo de transferencia sucio.\n"
                                    "QUÉ HACER: 1. Limpiar el rodillo con paño seco."))

    grupo = SolucionesService.agrupar(db_session, 1)[0]
    solucion = SolucionesService.redactar_borrador(db_session, grupo, 1)

    assert "tóner" in solucion.descartado
    assert "cable" in solucion.descartado


def test_el_borrador_nace_sin_publicar_y_sin_embedding(db_session, monkeypatch):
    """**Lo más importante del archivo.** Un procedimiento sin revisar no debe
    contestarle a nadie, y sin embedding no aparece en ninguna búsqueda."""
    igual = vector(0.1)
    for i in range(3):
        entrada(db_session, f"Raya {i}", SOLUCION_REAL, igual)
    monkeypatch.setattr("app.services.soluciones_service.ollama.responder_texto",
                        lambda *a, **k: ("SÍNTOMA: raya negra vertical en todas las hojas.\n"
                                    "CAUSA MÁS COMÚN: rodillo de transferencia sucio.\n"
                                    "QUÉ HACER: 1. Limpiar el rodillo con paño seco."))

    grupo = SolucionesService.agrupar(db_session, 1)[0]
    solucion = SolucionesService.redactar_borrador(db_session, grupo, 1)

    assert solucion.estado == "borrador"
    assert solucion.embedding is None
    assert solucion.revisada_por is None


def test_si_ningun_modelo_puede_no_se_inventa_nada(db_session, monkeypatch):
    igual = vector(0.1)
    for i in range(3):
        entrada(db_session, f"Raya {i}", SOLUCION_REAL, igual)
    monkeypatch.setattr("app.services.soluciones_service.ollama.responder_texto",
                        lambda *a, **k: None)

    grupo = SolucionesService.agrupar(db_session, 1)[0]

    assert SolucionesService.redactar_borrador(db_session, grupo, 1) is None


def test_una_redaccion_ridiculamente_corta_se_rechaza(db_session, monkeypatch):
    igual = vector(0.1)
    for i in range(3):
        entrada(db_session, f"Raya {i}", SOLUCION_REAL, igual)
    monkeypatch.setattr("app.services.soluciones_service.ollama.responder_texto",
                        lambda *a, **k: "Pues sí.")

    grupo = SolucionesService.agrupar(db_session, 1)[0]

    assert SolucionesService.redactar_borrador(db_session, grupo, 1) is None


def test_gemini_es_el_primero_aqui(db_session, monkeypatch):
    """Es la única parte del portal donde Gemini va antes: sintetizar sobre diez
    tickets es justo lo que un modelo chico no hace bien."""
    igual = vector(0.1)
    for i in range(3):
        entrada(db_session, f"Raya {i}", SOLUCION_REAL, igual)

    monkeypatch.setattr("app.services.soluciones_service.gemini.api_key", "llave")
    monkeypatch.setattr("app.services.soluciones_service.gemini.redactar",
                        lambda *a, **k: {"respuesta": (
                            "SÍNTOMA: raya negra vertical en todas las hojas.\n"
                            "CAUSA MÁS COMÚN: rodillo de transferencia sucio.\n"
                            "QUÉ HACER: 1. Limpiar el rodillo con un paño seco.")})
    llamadas = {"ollama": 0}
    monkeypatch.setattr("app.services.soluciones_service.ollama.responder_texto",
                        lambda *a, **k: llamadas.update(ollama=llamadas["ollama"] + 1))

    grupo = SolucionesService.agrupar(db_session, 1)[0]
    solucion = SolucionesService.redactar_borrador(db_session, grupo, 1)

    assert solucion.redactada_por == "gemini"
    assert llamadas["ollama"] == 0


# ----------------------------------------------------------------------
# Publicar
# ----------------------------------------------------------------------
def test_publicar_la_firma_una_persona_y_la_indexa(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.soluciones_service.ollama.generar_embedding",
                        lambda *a, **k: [0.1] * 768)
    solucion = SolucionGeneral(sitio_id=1, titulo="Raya negra", contenido="Limpiar rodillo",
                               estado="borrador")
    db_session.add(solucion)
    db_session.commit()

    r = client.post(f"/api/admin/soluciones/{solucion.id}/publicar", headers=cab(client))

    assert r.status_code == 200
    assert r.json()["estado"] == "publicada"
    assert r.json()["revisada_por"] is not None


def test_un_borrador_no_aparece_en_las_busquedas(db_session, monkeypatch):
    from app.services.recuperacion_service import RecuperacionService

    db_session.add(SolucionGeneral(sitio_id=1, titulo="Borrador", contenido="x",
                                   estado="borrador", embedding=[0.1] * 768))
    db_session.commit()
    monkeypatch.setattr("app.services.recuperacion_service.ollama.generar_embedding",
                        lambda *a, **k: [0.1] * 768)

    pasajes = RecuperacionService.buscar(db_session, "borrador", 1)

    assert all(p.fuente != "solucion_general" for p in pasajes)


def test_archivar_la_saca_de_las_respuestas(client, db_session):
    solucion = SolucionGeneral(sitio_id=1, titulo="Vieja", contenido="algo",
                               estado="publicada", embedding=[0.1] * 768)
    db_session.add(solucion)
    db_session.commit()

    r = client.post(f"/api/admin/soluciones/{solucion.id}/archivar", headers=cab(client))

    assert r.json()["estado"] == "archivada"
    db_session.refresh(solucion)
    assert solucion.embedding is None


def test_editar_el_texto_marca_que_la_tocó_una_persona(client, db_session):
    solucion = SolucionGeneral(sitio_id=1, titulo="Raya", contenido="original",
                               estado="borrador", redactada_por="gemini")
    db_session.add(solucion)
    db_session.commit()

    r = client.patch(f"/api/admin/soluciones/{solucion.id}",
                     json={"contenido": "corregido por el técnico"}, headers=cab(client))

    assert r.json()["redactada_por"] == "persona"


def test_solo_ti_ve_las_soluciones(client):
    r = client.get("/api/admin/soluciones", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


def test_un_borrador_que_se_salio_de_los_tickets_se_descarta(db_session, monkeypatch):
    """Pasó de verdad: el modelo local escribió "revisar el cable de corriente"
    y "revisar el papel" para una raya negra. Ningún ticket lo menciona; son lo
    que "suena" a impresora.

    Un borrador se lee una vez y se publica: aquí el filtro importa más que en
    el asistente, donde la respuesta lleva sus fuentes al lado.
    """
    igual = vector(0.1)
    for i in range(3):
        entrada(db_session, f"Raya {i}",
                "Se limpió el rodillo de transferencia con un paño seco", igual)

    monkeypatch.setattr(
        "app.services.soluciones_service.ollama.responder_texto",
        lambda *a, **k: ("SÍNTOMA: la impresora falla.\n"
                         "QUÉ HACER: 1. Verificar el cable de alimentación. "
                         "2. Revisar la bandeja del papel. "
                         "3. Comprobar los controladores del sistema operativo."))

    grupo = SolucionesService.agrupar(db_session, 1)[0]

    assert SolucionesService.redactar_borrador(db_session, grupo, 1) is None
