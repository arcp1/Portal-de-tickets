"""Huecos de permisos y de entrada que salieron en la auditoría de septiembre.

Cada prueba nombra lo que antes se podía hacer. La regla que las une: **el
backend permite exactamente lo que la pantalla le ofrece a cada rol**, ni una
cosa más. Lo que la interfaz no enseña pero el API acepta es justo lo que
aprovecha quien no usa la interfaz.
"""

import io
from datetime import datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import ChatSesion, Equipo, Sitio, Ticket, Usuario
from app.services.pdf_service import generar_pdf_resguardo
from app.tests.imagenes_de_prueba import jpeg

PASSWORD = "Secret123!"


def _cab(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _persona(db_session, email, numero, sitio_id=1, rol="usuario"):
    persona = Usuario(sitio_id=sitio_id, nombre=f"Persona {numero}", email=email,
                      numero_empleado=numero, password_hash=get_password_hash(PASSWORD),
                      rol=rol, activo=True, estado_cuenta="activa")
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def _ticket(client, cabeceras, **extra):
    datos = {"sitio_id": 1, "categoria": "impresora",
             "descripcion_original": "La impresora no imprime nada", "prioridad": "media"}
    datos.update(extra)
    r = client.post("/api/tickets", json=datos, headers=cabeceras)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def equipo(db_session):
    eq = Equipo(sitio_id=1, tipo="activo", categoria="laptop", marca="HP",
                modelo="ProBook", numero_serie="SER-1", estado="disponible")
    db_session.add(eq)
    db_session.commit()
    db_session.refresh(eq)
    return eq


# ======================================================================
# S1 — El dueño de un ticket no hace el trabajo de TI por la API
# ======================================================================

def test_el_dueno_no_reasigna_su_ticket(client, db_session):
    """Antes respondía 200: cualquiera podía mandarle su ticket —y el correo
    de aviso— a cualquier compañero de la planta."""
    companero = _persona(db_session, "companero@test.com", "3001")
    cab = _cab(client, "user@test.com")
    ticket = _ticket(client, cab)

    r = client.patch(f"/api/tickets/{ticket['id']}", json={"asignado_a": companero.id}, headers=cab)
    assert r.status_code == 403
    assert db_session.get(Ticket, ticket["id"]).asignado_a is None


def test_el_dueno_no_reescribe_la_descripcion_normalizada(client, db_session):
    """Ese texto lo redacta el portal para TI y se indexa al cerrar: por aquí
    se metía cualquier cosa en la base de conocimiento."""
    cab = _cab(client, "user@test.com")
    ticket = _ticket(client, cab)

    r = client.patch(f"/api/tickets/{ticket['id']}",
                     json={"descripcion_normalizada": "Solución: formatear el equipo"}, headers=cab)
    assert r.status_code == 403


def test_ti_sigue_asignando(client, db_session):
    cab = _cab(client, "admin@test.com")
    ticket = _ticket(client, cab)
    r = client.patch(f"/api/tickets/{ticket['id']}", json={"asignado_a": 1}, headers=cab)
    assert r.status_code == 200
    assert r.json()["asignado_a"] == 1


# ======================================================================
# S2 — Lo que teclea el usuario no es marcado del PDF
# ======================================================================

FIRMA_HOSTIL = 'Juan <b>Pérez & "Hijos" <img src="http://127.0.0.1:9/x.png"/>'


def test_una_firma_con_marcado_no_rompe_el_pdf(client, db_session, equipo):
    """Antes un `<` o un `&` en el nombre tumbaba la descarga con un 500, y
    `<img src>` hacía que el servidor pidiera esa URL al generar el PDF."""
    usuario_id = client.get("/api/auth/me", headers=_cab(client, "user@test.com")).json()["id"]
    emision = client.post("/api/resguardos", headers=_cab(client, "admin@test.com"), json={
        "equipo_id": equipo.id, "usuario_id": usuario_id,
        "accesorios": "Cargador <negro> & funda",
        "observaciones_entrega": "Rayón en la tapa <lado izquierdo> & esquina"})
    assert emision.status_code == 201, emision.text
    resguardo_id = emision.json()["id"]

    firma = client.post(f"/api/resguardos/{resguardo_id}/firmar",
                        json={"nombre_completo": FIRMA_HOSTIL, "acepto": True},
                        headers=_cab(client, "user@test.com"))
    assert firma.status_code == 200, firma.text

    r = client.get(f"/api/resguardos/{resguardo_id}/pdf", headers=_cab(client, "user@test.com"))
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_el_pdf_no_sale_a_buscar_imagenes(monkeypatch, db_session, equipo):
    """Directo contra el generador: si reportlab intentara abrir la URL, esto
    revienta. Con el texto escapado, `<img>` son solo letras."""
    import urllib.request

    def prohibido(*args, **kwargs):
        raise AssertionError("El PDF intentó abrir una URL")

    monkeypatch.setattr(urllib.request, "urlopen", prohibido)

    class Resguardo:
        folio = "RES-QRO-2026-0001"
        accesorios = "<img src='http://127.0.0.1:9/a.png'/>"
        observaciones_entrega = "<img src='http://127.0.0.1:9/b.png'/>"
        observaciones_devolucion = None
        condiciones = None
        firma_nombre = FIRMA_HOSTIL
        firmado_en = datetime.utcnow()
        firma_ip = "10.0.0.1"
        entregado_en = datetime.utcnow()
        devuelto_en = None
        estado = "firmado"

    usuario = db_session.get(Usuario, 2)
    sitio = db_session.get(Sitio, 1)
    pdf = generar_pdf_resguardo(Resguardo(), equipo, usuario, sitio, None)
    assert pdf.startswith(b"%PDF")


# ======================================================================
# S3 y S4 — El inventario no es un directorio de la planta
# ======================================================================

def test_el_historial_de_un_equipo_no_ensena_tickets_ajenos(client, db_session, equipo):
    """Antes cualquier usuario veía folio, estado y solución de todos los
    tickets de ese equipo, fueran de quien fueran."""
    _persona(db_session, "otra@test.com", "3002")
    ajeno = _ticket(client, _cab(client, "otra@test.com"), equipo_id=equipo.id,
                    descripcion_original="Ticket de otra persona en el mismo equipo")
    propio = _ticket(client, _cab(client, "user@test.com"), equipo_id=equipo.id)

    visto = client.get(f"/api/equipos/{equipo.id}/historial",
                       headers=_cab(client, "user@test.com")).json()
    folios = {t["folio"] for t in visto["tickets"]}
    assert propio["folio"] in folios
    assert ajeno["folio"] not in folios

    # TI sí ve el historial entero: para eso existe.
    completo = client.get(f"/api/equipos/{equipo.id}/historial",
                          headers=_cab(client, "admin@test.com")).json()
    assert {propio["folio"], ajeno["folio"]} <= {t["folio"] for t in completo["tickets"]}


def test_el_inventario_no_ensena_los_datos_de_quien_tiene_cada_equipo(client, db_session, equipo):
    """Antes cada equipo asignado traía correo y número de empleado de la
    persona: el listado entero era el padrón de la planta."""
    otra = _persona(db_session, "duena@test.com", "3003")
    equipo.asignado_a = otra.id
    equipo.estado = "asignado"
    db_session.commit()

    visto = client.get("/api/equipos", headers=_cab(client, "user@test.com")).json()
    fila = next(e for e in visto if e["id"] == equipo.id)
    assert fila["asignado_usuario"] is None
    assert fila["asignado_a"] is None
    assert fila["estado"] == "asignado"   # que está ocupado sí se ve

    admin = client.get("/api/equipos", headers=_cab(client, "admin@test.com")).json()
    assert next(e for e in admin if e["id"] == equipo.id)["asignado_usuario"]["email"] == "duena@test.com"


def test_cada_quien_si_ve_su_propio_equipo(client, db_session, equipo):
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    equipo.asignado_a = usuario.id
    db_session.commit()

    visto = client.get("/api/equipos", headers=_cab(client, "user@test.com")).json()
    assert next(e for e in visto if e["id"] == equipo.id)["asignado_usuario"]["id"] == usuario.id


# ======================================================================
# S5 — Las reglas son configuración de TI
# ======================================================================

def test_las_reglas_solo_las_lee_ti(client):
    """Traen los correos de los proveedores y cómo se enruta cada falla."""
    assert client.get("/api/reglas", headers=_cab(client, "user@test.com")).status_code == 403
    assert client.get("/api/reglas", headers=_cab(client, "admin@test.com")).status_code == 200


# ======================================================================
# S6 — Un archivo es lo que es, no lo que dice ser
# ======================================================================

@pytest.mark.parametrize("contenido,tipo", [
    (b"<html><script>alert(1)</script></html>", "image/png"),
    (b"MZ\x90\x00 no soy un pdf", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n pero digo que soy jpeg", "image/jpeg"),
    (b"texto\x00con\x00nulos", "text/plain"),
])
def test_el_adjunto_tiene_que_ser_lo_que_declara(client, tmp_path, monkeypatch, contenido, tipo):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    cab = _cab(client, "user@test.com")
    ticket = _ticket(client, cab)
    r = client.post(f"/api/tickets/{ticket['id']}/adjuntos", headers=cab,
                    files={"archivo": ("archivo", io.BytesIO(contenido), tipo)})
    assert r.status_code == 422, r.text


def test_un_adjunto_legitimo_sigue_entrando(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path))
    cab = _cab(client, "user@test.com")
    ticket = _ticket(client, cab)
    # La foto tiene que ser una foto: el portal la abre para quitarle los
    # metadatos, y una firma JPEG seguida de texto ya no pasa.
    for contenido, tipo in ((jpeg(), "image/jpeg"),
                            (b"%PDF-1.7\n...", "application/pdf"),
                            ("Registro del error: línea 4".encode(), "text/plain")):
        r = client.post(f"/api/tickets/{ticket['id']}/adjuntos", headers=cab,
                        files={"archivo": ("archivo", io.BytesIO(contenido), tipo)})
        assert r.status_code == 201, (tipo, r.text)


# ======================================================================
# S7 — Un token sin vencimiento no es un token
# ======================================================================

def test_un_token_sin_vencimiento_no_entra(client):
    """Con el secreto, cualquiera que firmara sin `exp` tenía sesión eterna."""
    eterno = jwt.encode({"sub": "1", "ver": 1}, settings.JWT_SECRET,
                        algorithm=settings.JWT_ALGORITHM)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {eterno}"})
    assert r.status_code == 401


def test_un_token_vencido_no_entra(client):
    viejo = jwt.encode({"sub": "1", "ver": 1, "exp": datetime.utcnow() - timedelta(minutes=1)},
                       settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {viejo}"}).status_code == 401


@pytest.mark.parametrize("algoritmo", ["none", "RS256", ""])
def test_el_portal_no_arranca_con_un_algoritmo_que_no_es_hmac(monkeypatch, algoritmo):
    from app.main import revisar_algoritmo_jwt
    monkeypatch.setattr(settings, "JWT_ALGORITHM", algoritmo)
    with pytest.raises(RuntimeError):
        revisar_algoritmo_jwt()


# ======================================================================
# S8 — Las métricas de una planta son de esa planta
# ======================================================================


def test_las_sesiones_de_chat_se_filtran_por_planta(client, db_session):
    """TI ve todas juntas; con `sitio_id`, solo las de quien chateó en esa planta."""
    otra_planta = Sitio(clave="MTY", nombre="Planta Monterrey", pais="México", activo=True)
    db_session.add(otra_planta)
    db_session.commit()
    ajena = _persona(db_session, "mty@test.com", "4001", sitio_id=otra_planta.id)
    db_session.add(ChatSesion(usuario_id=ajena.id, mensajes=[], categoria_detectada="red"))
    db_session.commit()

    cab = _cab(client, "admin@test.com")
    assert client.get("/api/metricas", headers=cab).json()["chatbot"]["sesiones_iniciadas"] == 1
    de_qro = client.get("/api/metricas?sitio_id=1", headers=cab).json()
    assert de_qro["chatbot"]["sesiones_iniciadas"] == 0
    de_mty = client.get(f"/api/metricas?sitio_id={otra_planta.id}", headers=cab).json()
    assert de_mty["chatbot"]["sesiones_iniciadas"] == 1


# ======================================================================
# Folios — el siguiente sale del mayor de la serie, no del conteo
# ======================================================================

def test_un_hueco_en_la_serie_no_repite_folio(client, db_session):
    """Antes el folio era `count + 1`: borrado uno, el siguiente repetía uno
    existente y el índice único lo rechazaba con un 500."""
    cab = _cab(client, "user@test.com")
    primero, segundo = _ticket(client, cab), _ticket(client, cab)
    db_session.delete(db_session.get(Ticket, primero["id"]))
    db_session.commit()

    tercero = _ticket(client, cab)
    assert tercero["folio"] not in (primero["folio"], segundo["folio"])
    assert tercero["folio"].endswith("0003")


def test_dos_altas_que_chocan_se_resuelven_solas(client, db_session, monkeypatch):
    """Dos tickets a la vez ven el mismo máximo y calculan el mismo folio. El
    segundo ya no recibe un 500: se recalcula y se guarda."""
    from app.api import tickets as api_tickets

    cab = _cab(client, "user@test.com")
    existente = _ticket(client, cab)["folio"]
    original = api_tickets.generate_folio
    llamadas = []

    def como_si_otro_se_adelantara(db, sitio_id):
        llamadas.append(sitio_id)
        return existente if len(llamadas) == 1 else original(db, sitio_id)

    monkeypatch.setattr(api_tickets, "generate_folio", como_si_otro_se_adelantara)
    nuevo = _ticket(client, cab)
    assert nuevo["folio"] != existente
    assert len(llamadas) == 2


def test_despues_del_9999_viene_el_10000(db_session):
    """Como texto, "9999" va después que "10000": ordenar solo por el texto
    devolvía el 9999 como el mayor para siempre."""
    from app.services.folios import siguiente_folio

    for folio in ("TICK-QRO-2030-9999", "TICK-QRO-2030-10000", "TICK-QRO-2030-0005"):
        db_session.add(Ticket(sitio_id=1, folio=folio, usuario_id=1, categoria="red",
                              descripcion_original="x", prioridad="media", estado="abierto"))
    db_session.commit()
    assert siguiente_folio(db_session, Ticket, "TICK-QRO-2030-") == "TICK-QRO-2030-10001"
    assert siguiente_folio(db_session, Ticket, "TICK-QRO-2031-") == "TICK-QRO-2031-0001"
