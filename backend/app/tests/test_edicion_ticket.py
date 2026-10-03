"""Lo que se puede escribir al editar un ticket, y quién puede escribirlo.

`PATCH /api/tickets/{id}` tocaba varias columnas que el modelo guarda como
texto libre pero que en realidad son enumeraciones: `estado`, `prioridad` y
`canal_resolucion`. Al crear el ticket sí se comprobaban; al editarlo entraba
lo que llegara, y el rol solo se miraba para cerrar y para documentar la
solución. Estas pruebas fijan las dos cosas que faltaban: que el valor exista
y que el canal lo ponga TI.
"""

import pytest

SOLUCION = "Se limpió el cabezal con alcohol isopropílico y volvió a imprimir bien."


def token(client, email):
    respuesta = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def como_usuario(client):
    return token(client, "user@test.com")


def como_admin(client):
    return token(client, "admin@test.com")


def crear_ticket(client, cabeceras):
    respuesta = client.post("/api/tickets", json={
        "sitio_id": 1,
        "categoria": "impresora",
        "descripcion_original": "La etiquetadora de embarques no saca etiquetas",
        "prioridad": "media",
    }, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


# ----------------------------------------------------------------------
# Valores que no existen
# ----------------------------------------------------------------------

@pytest.mark.parametrize("campo,valor", [
    ("estado", "banana"),
    ("prioridad", "urgentisima"),
    ("canal_resolucion", "pura-invencion"),
])
def test_un_valor_inventado_se_rechaza(client, campo, valor):
    """Un estado que no existe deja al ticket fuera de todas las pestañas del
    tablero, que filtran justo por estos nombres: el ticket desaparece de la
    vista sin haberse borrado."""
    cabeceras = como_admin(client)
    ticket_id = crear_ticket(client, cabeceras)

    respuesta = client.patch(f"/api/tickets/{ticket_id}", json={campo: valor}, headers=cabeceras)
    assert respuesta.status_code == 422, respuesta.text


def test_asignar_a_alguien_que_no_existe_no_revienta(client):
    """Antes el id viajaba tal cual a la clave foránea y la violación salía
    como un 500: un error del servidor por un dato del cliente."""
    cabeceras = como_admin(client)
    ticket_id = crear_ticket(client, cabeceras)

    respuesta = client.patch(f"/api/tickets/{ticket_id}", json={"asignado_a": 99999}, headers=cabeceras)
    assert respuesta.status_code == 422, respuesta.text


# ----------------------------------------------------------------------
# Quién puede tocar el canal
# ----------------------------------------------------------------------

def test_el_usuario_no_puede_declarar_el_canal_al_editar(client):
    """La contraparte de `test_no_se_puede_falsear_el_canal`, que ya cubría la
    creación. El canal es de donde sale la tasa de deflexión, así que quien
    reporta no lo escribe ni al crear ni al editar."""
    cabeceras = como_usuario(client)
    ticket_id = crear_ticket(client, cabeceras)

    for canal in ("kb", "checklist", "tecnico"):
        respuesta = client.patch(f"/api/tickets/{ticket_id}",
                                 json={"canal_resolucion": canal}, headers=cabeceras)
        assert respuesta.status_code == 403, canal


def test_ti_si_puede_registrar_el_canal(client):
    cabeceras = como_admin(client)
    ticket_id = crear_ticket(client, cabeceras)

    respuesta = client.patch(f"/api/tickets/{ticket_id}",
                             json={"canal_resolucion": "proveedor"}, headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["canal_resolucion"] == "proveedor"


# ----------------------------------------------------------------------
# Quitarle el ticket a quien lo tenía
# ----------------------------------------------------------------------

def test_se_puede_dejar_un_ticket_sin_asignar(client):
    """`null` significa "déjalo en nadie", no "no lo mandes". Sin esta
    distinción la asignación era de una sola dirección: la pantalla ofrecía
    «Sin asignar», el endpoint respondía 200 y el ticket seguía asignado."""
    cabeceras = como_admin(client)
    ticket_id = crear_ticket(client, cabeceras)

    asignado = client.patch(f"/api/tickets/{ticket_id}", json={"asignado_a": 1}, headers=cabeceras)
    assert asignado.status_code == 200
    assert asignado.json()["asignado_a"] == 1

    liberado = client.patch(f"/api/tickets/{ticket_id}", json={"asignado_a": None}, headers=cabeceras)
    assert liberado.status_code == 200, liberado.text
    assert liberado.json()["asignado_a"] is None


def test_no_mandar_el_campo_no_toca_la_asignacion(client):
    """La otra mitad de lo mismo: omitirlo tiene que seguir significando
    "no lo cambies"."""
    cabeceras = como_admin(client)
    ticket_id = crear_ticket(client, cabeceras)

    client.patch(f"/api/tickets/{ticket_id}", json={"asignado_a": 1}, headers=cabeceras)
    respuesta = client.patch(f"/api/tickets/{ticket_id}", json={"prioridad": "alta"}, headers=cabeceras)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["asignado_a"] == 1


def test_solo_se_asigna_a_alguien_de_ti(client, db_session):
    """El selector ofrecía la plantilla entera, quien reportó incluido: el
    ticket quedaba "asignado" a alguien que no ve la cola ni puede atenderlo."""
    from app.models import Usuario
    cabeceras = como_admin(client)
    ticket_id = crear_ticket(client, cabeceras)
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()

    respuesta = client.patch(f"/api/tickets/{ticket_id}", json={"asignado_a": usuario.id},
                             headers=cabeceras)
    assert respuesta.status_code == 422, respuesta.text
    assert "TI" in respuesta.json()["detail"]


# ----------------------------------------------------------------------
# Cerrado, es de solo lectura para quien lo reportó
# ----------------------------------------------------------------------

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
       b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00"
       b"\x00\x00IEND\xaeB`\x82")


def _subir(client, ticket_id, cabeceras):
    return client.post(f"/api/tickets/{ticket_id}/adjuntos", headers=cabeceras,
                       files={"archivo": ("foto.png", PNG, "image/png")})


def _resolver(client, ticket_id):
    r = client.patch(f"/api/tickets/{ticket_id}", headers=como_admin(client), json={
        "estado": "resuelto", "solucion": "Se limpió el cabezal y se recalibró el sensor."})
    assert r.status_code == 200, r.text


def test_resuelto_quien_reporto_ya_no_comenta_ni_toca_archivos(client):
    """Se podía borrar la foto que explicaba un ticket resuelto, y un comentario
    nuevo avisaba a TI de algo que ya no está en ninguna cola."""
    usuario = como_usuario(client)
    ticket_id = crear_ticket(client, usuario)
    adjunto = _subir(client, ticket_id, usuario)
    assert adjunto.status_code == 201, adjunto.text
    _resolver(client, ticket_id)

    comentario = client.post(f"/api/tickets/{ticket_id}/comments", headers=usuario,
                             json={"comentario": "Sigue fallando"})
    assert comentario.status_code == 409
    assert "ticket nuevo" in comentario.json()["detail"]
    assert _subir(client, ticket_id, usuario).status_code == 409
    borrar = client.delete(f"/api/tickets/{ticket_id}/adjuntos/{adjunto.json()['id']}", headers=usuario)
    assert borrar.status_code == 409

    visto = client.get(f"/api/tickets/{ticket_id}", headers=usuario).json()
    assert len(visto["adjuntos"]) == 1 and visto["comentarios"] == []


def test_resuelto_ti_sigue_pudiendo_todo(client):
    """TI puede documentar después del cierre y reabrir cambiando el estado."""
    ticket_id = crear_ticket(client, como_usuario(client))
    _resolver(client, ticket_id)
    admin = como_admin(client)

    assert client.post(f"/api/tickets/{ticket_id}/comments", headers=admin,
                       json={"comentario": "Nota posterior", "es_interno": True}).status_code == 201
    assert _subir(client, ticket_id, admin).status_code == 201


def test_mientras_esta_abierto_quien_reporto_si_comenta_y_adjunta(client):
    usuario = como_usuario(client)
    ticket_id = crear_ticket(client, usuario)
    assert client.post(f"/api/tickets/{ticket_id}/comments", headers=usuario,
                       json={"comentario": "Le agrego un dato"}).status_code == 201
    assert _subir(client, ticket_id, usuario).status_code == 201
