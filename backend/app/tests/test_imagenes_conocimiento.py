"""Imágenes en los pasos, en la base de conocimiento y en la solución de un ticket.

Lo que cuidan estas pruebas es lo que haría daño si fallara en silencio:

  * que **la ve quien ya ve el texto**, ni más —una captura de la solución de
    un ticket ajeno es información ajena— ni menos —un paso con la foto rota
    no explica nada—;
  * que **solo TI escribe**: es contenido que se le enseña a la gente como
    respuesta;
  * que **lo que entra es una imagen de verdad**, con la misma comprobación de
    firma que los adjuntos;
  * y que **al borrar no quedan restos**: ni filas sin dueño ni archivos sin
    fila.
"""

import io
from datetime import datetime
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import BaseConocimiento, Checklist, ImagenConocimiento, Ticket, Usuario
from app.tests.imagenes_de_prueba import misma_imagen

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def cab(client, email="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def subir(client, tipo, ident, cabeceras, contenido=PNG, mime="image/png",
          nombre="captura.png", pie=""):
    return client.post(
        f"/api/imagenes/{tipo}/{ident}",
        files={"archivo": (nombre, io.BytesIO(contenido), mime)},
        data={"pie": pie},
        headers=cabeceras,
    )


def carpeta() -> Path:
    return Path(settings.ADJUNTOS_RUTA) / "conocimiento"


@pytest.fixture
def paso(db_session):
    p = Checklist(categoria="impresora", orden=1, pregunta_key="custom.impresora.1",
                  pregunta_texto="¿Tiene la luz verde encendida?", activo=True)
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def entrada(db_session):
    e = BaseConocimiento(titulo="Atasco en la Zebra",
                         contenido="Abrir la tapa, retirar la etiqueta y recalibrar.",
                         categoria="impresora")
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def ticket(db_session):
    """Un ticket de la persona de prueba (user@test.com)."""
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").first()
    t = Ticket(sitio_id=usuario.sitio_id, folio="TICK-QRO-2026-0901", usuario_id=usuario.id,
               categoria="impresora", descripcion_original="No imprime", prioridad="media",
               estado="resuelto", solucion="Se cambió el cabezal y se recalibró.",
               creado_en=datetime.utcnow())
    db_session.add(t)
    db_session.commit()
    return t


@pytest.fixture
def otra_persona(db_session):
    u = Usuario(sitio_id=1, nombre="Otra Persona", email="otra@test.com",
                numero_empleado="1003", password_hash=get_password_hash("Secret123!"),
                rol="usuario", activo=True, estado_cuenta="activa")
    db_session.add(u)
    db_session.commit()
    return u


# ----------------------------------------------------------------------
# Pasos
# ----------------------------------------------------------------------
def test_ti_ilustra_un_paso_y_lo_ve_quien_levanta_un_ticket(client, paso):
    r = subir(client, "paso", paso.id, cab(client), pie="La luz está junto al botón")
    assert r.status_code == 201
    [imagen] = r.json()
    assert imagen["pie"] == "La luz está junto al botón"

    # El checklist que se le enseña al levantar un ticket ya la trae.
    persona = cab(client, "user@test.com")
    [visto] = client.get("/api/checklists?categoria=impresora", headers=persona).json()
    assert [i["id"] for i in visto["imagenes"]] == [imagen["id"]]

    archivo = client.get(f"/api/imagenes/{imagen['id']}", headers=persona)
    assert archivo.status_code == 200
    assert misma_imagen(archivo.content, PNG)
    assert archivo.headers["content-type"] == "image/png"


def test_el_listado_de_ti_tambien_las_trae(client, paso):
    subir(client, "paso", paso.id, cab(client))
    [visto] = client.get("/api/admin/pasos", headers=cab(client)).json()
    assert len(visto["imagenes"]) == 1


def test_un_paso_dado_de_baja_no_ensena_su_imagen(client, db_session, paso):
    [imagen] = subir(client, "paso", paso.id, cab(client)).json()
    paso.activo = False
    db_session.commit()

    # A quien levanta tickets ya no se le enseña el paso: tampoco su foto.
    assert client.get(f"/api/imagenes/{imagen['id']}",
                      headers=cab(client, "user@test.com")).status_code == 404
    # TI sigue viéndola para poder revisarlo antes de reactivarlo.
    assert client.get(f"/api/imagenes/{imagen['id']}", headers=cab(client)).status_code == 200


def test_solo_ti_sube_imagenes(client, paso):
    r = subir(client, "paso", paso.id, cab(client, "user@test.com"))
    assert r.status_code == 403


def test_solo_ti_borra_imagenes(client, paso):
    [imagen] = subir(client, "paso", paso.id, cab(client)).json()
    r = client.delete(f"/api/imagenes/{imagen['id']}", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


# ----------------------------------------------------------------------
# Base de conocimiento
# ----------------------------------------------------------------------
def test_la_base_de_conocimiento_lleva_sus_imagenes(client, entrada):
    [imagen] = subir(client, "kb", entrada.id, cab(client)).json()

    [vista] = client.get("/api/admin/kb", headers=cab(client)).json()
    assert [i["id"] for i in vista["imagenes"]] == [imagen["id"]]

    # Se comparte entre plantas, como el texto: cualquiera que entra la ve.
    persona = cab(client, "user@test.com")
    assert client.get(f"/api/imagenes/kb/{entrada.id}", headers=persona).json()[0]["id"] == imagen["id"]
    assert client.get(f"/api/imagenes/{imagen['id']}", headers=persona).status_code == 200


def test_borrar_una_entrada_se_lleva_sus_imagenes(client, db_session, entrada):
    [imagen] = subir(client, "kb", entrada.id, cab(client)).json()
    guardada = db_session.get(ImagenConocimiento, imagen["id"]).nombre_guardado
    assert (carpeta() / guardada).exists()

    assert client.delete(f"/api/admin/kb/{entrada.id}", headers=cab(client)).status_code == 204

    db_session.expire_all()
    assert db_session.query(ImagenConocimiento).count() == 0
    assert not (carpeta() / guardada).exists()


# ----------------------------------------------------------------------
# Solución de un ticket
# ----------------------------------------------------------------------
def test_quien_reporto_ve_como_le_resolvieron_su_ticket(client, ticket):
    [imagen] = subir(client, "ticket", ticket.id, cab(client),
                     pie="Así quedó la configuración").json()

    persona = cab(client, "user@test.com")
    visto = client.get(f"/api/tickets/{ticket.id}", headers=persona).json()
    assert [i["id"] for i in visto["imagenes_solucion"]] == [imagen["id"]]
    assert visto["imagenes_solucion"][0]["pie"] == "Así quedó la configuración"
    assert misma_imagen(client.get(f"/api/imagenes/{imagen['id']}", headers=persona).content, PNG)


def test_la_solucion_de_un_ticket_ajeno_no_se_ve(client, ticket, otra_persona):
    [imagen] = subir(client, "ticket", ticket.id, cab(client)).json()

    ajena = cab(client, "otra@test.com")
    # 404 y no 403: un 403 confirmaría que el ticket existe.
    assert client.get(f"/api/imagenes/{imagen['id']}", headers=ajena).status_code == 404
    assert client.get(f"/api/imagenes/ticket/{ticket.id}", headers=ajena).status_code == 404


def test_quien_reporto_no_puede_tocar_la_solucion(client, ticket):
    """La solución la escribe TI; quien reportó la lee."""
    persona = cab(client, "user@test.com")
    assert subir(client, "ticket", ticket.id, persona).status_code == 403
    [imagen] = subir(client, "ticket", ticket.id, cab(client)).json()
    assert client.delete(f"/api/imagenes/{imagen['id']}", headers=persona).status_code == 403


def test_el_tablero_no_crece_en_consultas_por_las_imagenes(client, ticket):
    """El listado carga las imágenes de todos los tickets de una vez."""
    subir(client, "ticket", ticket.id, cab(client))
    pagina = client.get("/api/tickets", headers=cab(client)).json()
    assert pagina["items"][0]["imagenes_solucion"]


# ----------------------------------------------------------------------
# Lo que entra
# ----------------------------------------------------------------------
def test_un_html_disfrazado_de_png_no_entra(client, paso):
    r = subir(client, "paso", paso.id, cab(client),
              contenido=b"<html><script>alert(1)</script></html>")
    assert r.status_code == 422
    assert not carpeta().exists() or not any(carpeta().iterdir())


def test_un_pdf_no_cabe(client, paso):
    """Aquí la imagen se enseña en línea; un PDF no se ve debajo de un paso."""
    r = subir(client, "paso", paso.id, cab(client), contenido=b"%PDF-1.4 hola",
              mime="application/pdf", nombre="manual.pdf")
    assert r.status_code == 422


def test_heic_no_cabe(client, paso):
    """Fuera de Safari ningún navegador lo pinta: sería una imagen rota."""
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"
    r = subir(client, "paso", paso.id, cab(client), contenido=heic,
              mime="image/heic", nombre="foto.heic")
    assert r.status_code == 422


def test_hay_tope_de_imagenes_por_elemento(client, paso, monkeypatch):
    monkeypatch.setattr(settings, "IMAGENES_MAX_POR_ELEMENTO", 2)
    assert subir(client, "paso", paso.id, cab(client)).status_code == 201
    assert subir(client, "paso", paso.id, cab(client)).status_code == 201
    assert subir(client, "paso", paso.id, cab(client)).status_code == 422


def test_hay_tope_de_tamano(client, paso, monkeypatch):
    monkeypatch.setattr(settings, "IMAGENES_MAX_MB", 0)
    assert subir(client, "paso", paso.id, cab(client)).status_code == 413


def test_un_dueno_inventado_no_existe(client):
    assert client.get("/api/imagenes/usuario/1", headers=cab(client)).status_code == 422
    assert client.get("/api/imagenes/paso/999999", headers=cab(client)).status_code == 404


# ----------------------------------------------------------------------
# Corregir y borrar
# ----------------------------------------------------------------------
def test_el_pie_se_corrige(client, paso):
    [imagen] = subir(client, "paso", paso.id, cab(client), pie="Mal escrito").json()
    r = client.patch(f"/api/imagenes/{imagen['id']}", json={"pie": "El botón rojo"},
                     headers=cab(client))
    assert r.status_code == 200
    assert r.json()[0]["pie"] == "El botón rojo"


def test_se_suben_en_orden(client, paso):
    subir(client, "paso", paso.id, cab(client), pie="primera")
    r = subir(client, "paso", paso.id, cab(client), pie="segunda")
    assert [i["pie"] for i in r.json()] == ["primera", "segunda"]


def test_borrar_una_imagen_retira_el_archivo(client, db_session, paso):
    [imagen] = subir(client, "paso", paso.id, cab(client)).json()
    guardada = db_session.get(ImagenConocimiento, imagen["id"]).nombre_guardado

    r = client.delete(f"/api/imagenes/{imagen['id']}", headers=cab(client))

    assert r.status_code == 200
    assert r.json() == []
    assert not (carpeta() / guardada).exists()


def test_los_archivos_caen_en_la_carpeta_de_la_prueba(client, paso, tmp_path):
    """La suite corre en el contenedor de producción: nada al volumen real."""
    subir(client, "paso", paso.id, cab(client))
    assert str(carpeta()).startswith(str(tmp_path))
    assert any(carpeta().iterdir())


# ----------------------------------------------------------------------
# Del ticket a la base de conocimiento: las capturas van enlazadas
# ----------------------------------------------------------------------
@pytest.fixture
def indexar(db_session, monkeypatch):
    """La indexación de verdad (`KBService.indexar_ticket`), con el vector
    sustituido: sin Ollama no se crea la entrada."""
    from app.services.kb_service import KBService
    monkeypatch.setattr("app.services.ollama_client.ollama.generar_embedding",
                        lambda *a, **k: [0.1] * 768)

    def _indexar(ticket):
        assert KBService.indexar_ticket(db_session, ticket)
        return db_session.query(BaseConocimiento).filter_by(ticket_origen_id=ticket.id).one()
    return _indexar


def test_al_pasar_a_la_kb_la_entrada_trae_las_capturas_del_ticket(
        client, ticket, otra_persona, indexar):
    [imagen] = subir(client, "ticket", ticket.id, cab(client), pie="La casilla").json()
    ajena = cab(client, "otra@test.com")
    # Mientras es solo un ticket, la captura es de quien lo reportó y de TI.
    assert client.get(f"/api/imagenes/{imagen['id']}", headers=ajena).status_code == 404

    entrada = indexar(ticket)

    [vista] = client.get("/api/admin/kb", headers=cab(client)).json()
    assert vista["id"] == entrada.id
    assert [i["id"] for i in vista["imagenes_ticket"]] == [imagen["id"]]
    assert vista["imagenes"] == []
    # Ya es conocimiento de todos: la ve quien lee la entrada.
    assert [i["id"] for i in client.get(f"/api/imagenes/kb/{entrada.id}", headers=ajena).json()] \
        == [imagen["id"]]
    assert misma_imagen(client.get(f"/api/imagenes/{imagen['id']}", headers=ajena).content, PNG)


def test_una_captura_subida_despues_de_indexar_tambien_llega(client, ticket, indexar):
    """El cierre guarda la solución y sube las capturas justo después, y el
    índice corre en el worker: cualquiera de los dos puede llegar primero."""
    entrada = indexar(ticket)
    [imagen] = subir(client, "ticket", ticket.id, cab(client)).json()

    vista = client.get(f"/api/imagenes/kb/{entrada.id}", headers=cab(client, "user@test.com")).json()
    assert [i["id"] for i in vista] == [imagen["id"]]


def test_corregir_la_captura_en_el_ticket_la_corrige_en_la_kb(client, ticket, indexar):
    [imagen] = subir(client, "ticket", ticket.id, cab(client)).json()
    entrada = indexar(ticket)

    client.delete(f"/api/imagenes/{imagen['id']}", headers=cab(client))

    assert client.get(f"/api/imagenes/kb/{entrada.id}", headers=cab(client)).json() == []


def test_borrar_la_entrada_no_borra_las_capturas_del_ticket(
        client, db_session, ticket, otra_persona, indexar):
    [imagen] = subir(client, "ticket", ticket.id, cab(client)).json()
    entrada = indexar(ticket)
    guardada = db_session.get(ImagenConocimiento, imagen["id"]).nombre_guardado

    assert client.delete(f"/api/admin/kb/{entrada.id}", headers=cab(client)).status_code == 204

    # Siguen en el ticket, para quien lo reportó...
    assert client.get(f"/api/imagenes/{imagen['id']}",
                      headers=cab(client, "user@test.com")).status_code == 200
    assert (carpeta() / guardada).exists()
    # ...y dejan de ser públicas: ya no hay entrada que las enlace.
    assert client.get(f"/api/imagenes/{imagen['id']}",
                      headers=cab(client, "otra@test.com")).status_code == 404


def test_desde_la_entrada_no_se_tocan_las_capturas_del_ticket(client, ticket, indexar):
    """Se ven con la entrada, pero son del ticket: borrarlas es cosa de TI en
    el ticket, no de quien lee la base."""
    [imagen] = subir(client, "ticket", ticket.id, cab(client)).json()
    indexar(ticket)
    r = client.delete(f"/api/imagenes/{imagen['id']}", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


# ----------------------------------------------------------------------
# Soluciones generales
# ----------------------------------------------------------------------
@pytest.fixture
def procedimiento(db_session):
    from app.models import SolucionGeneral
    s = SolucionGeneral(titulo="La Zebra imprime en blanco",
                        contenido="1. Recalibrar el sensor.\n2. Revisar el ribbon.",
                        estado="borrador", tickets_origen=0)
    db_session.add(s)
    db_session.commit()
    return s


def test_un_procedimiento_lleva_sus_imagenes(client, procedimiento):
    r = subir(client, "solucion", procedimiento.id, cab(client), pie="El sensor")
    assert r.status_code == 201

    [visto] = client.get("/api/admin/soluciones", headers=cab(client)).json()
    assert [i["pie"] for i in visto["imagenes"]] == ["El sensor"]


def test_un_borrador_no_ensena_sus_imagenes(client, db_session, procedimiento):
    """Mientras no lo firma una persona, no le contesta a nadie: tampoco
    con fotos."""
    [imagen] = subir(client, "solucion", procedimiento.id, cab(client)).json()
    persona = cab(client, "user@test.com")
    assert client.get(f"/api/imagenes/{imagen['id']}", headers=persona).status_code == 404

    procedimiento.estado = "publicada"
    db_session.commit()
    assert client.get(f"/api/imagenes/{imagen['id']}", headers=persona).status_code == 200


def test_solo_ti_ilustra_un_procedimiento(client, procedimiento):
    assert subir(client, "solucion", procedimiento.id,
                 cab(client, "user@test.com")).status_code == 403
