"""Las notas internas son de TI y solo de TI.

La casilla al pie del comentario dice, con todas sus letras, «Nota interna
(solo visibles para TI)». El backend cuidaba dos tercios de esa promesa: un
usuario no puede crear una nota interna —`es_interno` se fuerza a False si no
es admin— y las notas internas no disparan el aviso por correo a quien
reportó.

Faltaba el tercio que importa. La lista de comentarios salía de la relación
del ORM tal cual, sin mirar quién preguntaba, así que el dueño del ticket
recibía las notas internas junto con las suyas y la pantalla se las pintaba.
Ahí es donde un técnico escribe lo que cuesta la pieza, lo que sospecha antes
de confirmarlo, o lo que no quiere decirle todavía a la persona.
"""

NOTA = "El proveedor cobra 4800 por el cabezal; no decírselo todavía."
PUBLICO = "Ya pedimos la refacción, le avisamos en cuanto llegue."


def cab(client, identificador):
    r = client.post("/api/auth/login", json={"email": identificador, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def ticket_del_usuario(client):
    """Un ticket levantado por el usuario normal, que es quien no debe ver."""
    r = client.post("/api/tickets", json={
        "sitio_id": 1,
        "categoria": "impresora",
        "descripcion_original": "La etiquetadora saca las etiquetas con una raya",
        "prioridad": "media",
    }, headers=cab(client, "user@test.com"))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def con_notas(client, ticket_id):
    admin = cab(client, "admin@test.com")
    client.post(f"/api/tickets/{ticket_id}/comments",
                json={"comentario": PUBLICO, "es_interno": False}, headers=admin)
    client.post(f"/api/tickets/{ticket_id}/comments",
                json={"comentario": NOTA, "es_interno": True}, headers=admin)


def textos(respuesta):
    return [c["comentario"] for c in respuesta.json()["comentarios"]]


# ----------------------------------------------------------------------

def test_el_dueno_no_ve_la_nota_interna_en_el_detalle(client):
    ticket_id = ticket_del_usuario(client)
    con_notas(client, ticket_id)

    visto = textos(client.get(f"/api/tickets/{ticket_id}", headers=cab(client, "user@test.com")))

    assert PUBLICO in visto
    assert NOTA not in visto


def test_el_dueno_no_ve_la_nota_interna_en_el_listado(client):
    """El tablero trae los comentarios de cada ticket: la fuga estaba en los
    dos sitios, no solo en la ficha."""
    ticket_id = ticket_del_usuario(client)
    con_notas(client, ticket_id)

    listado = client.get("/api/tickets", headers=cab(client, "user@test.com")).json()["items"]
    todos = [c["comentario"] for t in listado for c in t["comentarios"]]

    assert PUBLICO in todos
    assert NOTA not in todos


def test_el_dueno_no_la_ve_despues_de_que_ti_mueve_su_ticket(client):
    """Antes el dueño editaba su ticket y la respuesta del `PATCH` le traía el
    ticket entero, así que ahí también había que filtrar. Desde 2026-09-30
    solo TI edita: lo que queda por comprobar es que la edición de TI no
    destape la nota para el dueño, y que a TI la respuesta sí se la traiga."""
    ticket_id = ticket_del_usuario(client)
    con_notas(client, ticket_id)

    editado = client.patch(f"/api/tickets/{ticket_id}", json={"estado": "en_proceso"},
                           headers=cab(client, "admin@test.com"))
    assert editado.status_code == 200
    assert NOTA in textos(editado)

    visto = client.get(f"/api/tickets/{ticket_id}", headers=cab(client, "user@test.com"))
    assert visto.json()["estado"] == "en_proceso"
    assert NOTA not in textos(visto)


def test_ti_si_las_ve(client):
    """El filtro no puede llevarse por delante la razón de ser de la nota."""
    ticket_id = ticket_del_usuario(client)
    con_notas(client, ticket_id)

    visto = textos(client.get(f"/api/tickets/{ticket_id}", headers=cab(client, "admin@test.com")))

    assert PUBLICO in visto
    assert NOTA in visto


def test_un_usuario_no_puede_escribir_una_nota_interna(client):
    """Ya estaba cubierto por el endpoint; se fija aquí junto al resto para
    que la promesa de la casilla quede descrita en un solo sitio."""
    ticket_id = ticket_del_usuario(client)

    r = client.post(f"/api/tickets/{ticket_id}/comments",
                    json={"comentario": "Intento de nota interna", "es_interno": True},
                    headers=cab(client, "user@test.com"))

    assert r.status_code == 201
    assert r.json()["es_interno"] is False
