"""El tablero de tickets, por páginas.

Lo que importa no es que existan `pagina` y `por_pagina`, sino que las páginas
juntas sean exactamente el listado —ni repetidos ni perdidos—, que el total
cuente lo filtrado y que la búsqueda mire en todos los tickets y no solo en la
página visible.
"""

import pytest

from app.core.security import get_password_hash
from app.models import Usuario


def _cab(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _crear(client, cabeceras, descripcion="La impresora no imprime", **extra):
    datos = {"sitio_id": 1, "categoria": "impresora", "descripcion_original": descripcion,
             "prioridad": "media"}
    datos.update(extra)
    r = client.post("/api/tickets", json=datos, headers=cabeceras)
    assert r.status_code == 201, r.text
    return r.json()


def _pagina(client, cabeceras, **parametros):
    r = client.get("/api/tickets", params=parametros, headers=cabeceras)
    assert r.status_code == 200, r.text
    return r.json()


def test_la_respuesta_trae_los_datos_de_la_pagina(client):
    cab = _cab(client, "user@test.com")
    creados = [_crear(client, cab) for _ in range(3)]

    pagina = _pagina(client, cab)
    assert pagina["total"] == 3
    assert pagina["pagina"] == 1
    assert pagina["por_pagina"] == 20
    assert pagina["paginas"] == 1
    # Lo más nuevo primero.
    assert [t["id"] for t in pagina["items"]] == [t["id"] for t in reversed(creados)]


def test_las_paginas_juntas_son_el_listado_sin_repetir_ni_perder(client):
    cab = _cab(client, "user@test.com")
    ids = {_crear(client, cab)["id"] for _ in range(5)}

    vistos = []
    for numero in (1, 2, 3):
        pagina = _pagina(client, cab, pagina=numero, por_pagina=2)
        assert pagina["total"] == 5
        assert pagina["paginas"] == 3
        vistos += [t["id"] for t in pagina["items"]]

    assert len(vistos) == 5
    assert set(vistos) == ids


def test_una_pagina_de_mas_viene_vacia_y_con_el_total(client):
    cab = _cab(client, "user@test.com")
    _crear(client, cab)
    pagina = _pagina(client, cab, pagina=9)
    assert pagina["items"] == []
    assert pagina["total"] == 1


def test_el_filtro_de_estado_y_la_paginacion_van_juntos(client):
    """El total y las páginas son los del filtro, no los de todo el tablero."""
    admin = _cab(client, "admin@test.com")
    tickets = [_crear(client, admin) for _ in range(5)]
    for t in tickets[:3]:
        assert client.patch(f"/api/tickets/{t['id']}", json={"estado": "en_proceso"},
                            headers=admin).status_code == 200

    pagina = _pagina(client, admin, estado="en_proceso", por_pagina=2)
    assert pagina["total"] == 3
    assert pagina["paginas"] == 2
    assert all(t["estado"] == "en_proceso" for t in pagina["items"])

    segunda = _pagina(client, admin, estado="en_proceso", por_pagina=2, pagina=2)
    assert len(segunda["items"]) == 1
    assert _pagina(client, admin, estado="abierto")["total"] == 2


def test_la_busqueda_mira_todos_los_tickets_no_solo_la_pagina(client):
    """Antes el tablero filtraba en el navegador lo que ya había llegado: con
    páginas, eso habría buscado solo en la visible."""
    cab = _cab(client, "user@test.com")
    buscado = _crear(client, cab, descripcion="El escáner del Andén 4 no lee")
    for _ in range(4):
        _crear(client, cab)

    # El buscado es el más viejo: con 2 por página, cae en la última.
    por_texto = _pagina(client, cab, buscar="andén 4", por_pagina=2)
    assert por_texto["total"] == 1
    assert por_texto["items"][0]["id"] == buscado["id"]

    por_folio = _pagina(client, cab, buscar=buscado["folio"].lower()[-4:], por_pagina=2)
    assert buscado["id"] in [t["id"] for t in por_folio["items"]]


def test_los_comodines_se_buscan_como_letras(client):
    """Un `%` suelto no puede devolver todo el tablero."""
    cab = _cab(client, "user@test.com")
    _crear(client, cab, descripcion="Sin red en almacén")
    con_porcentaje = _crear(client, cab, descripcion="La batería se queda en 5% y se apaga")

    assert _pagina(client, cab, buscar="%")["total"] == 1
    assert _pagina(client, cab, buscar="%")["items"][0]["id"] == con_porcentaje["id"]
    assert _pagina(client, cab, buscar="_")["total"] == 0


def test_quien_reporta_solo_cuenta_los_suyos(client, db_session):
    otra = Usuario(sitio_id=1, nombre="Otra Persona", email="otra@test.com",
                   numero_empleado="7001", password_hash=get_password_hash("Secret123!"),
                   rol="usuario", activo=True, estado_cuenta="activa")
    db_session.add(otra)
    db_session.commit()
    _crear(client, _cab(client, "otra@test.com"))
    _crear(client, _cab(client, "otra@test.com"))
    _crear(client, _cab(client, "user@test.com"))

    assert _pagina(client, _cab(client, "user@test.com"))["total"] == 1
    assert _pagina(client, _cab(client, "admin@test.com"))["total"] == 3


@pytest.mark.parametrize("parametros", [
    {"por_pagina": 101},
    {"por_pagina": 0},
    {"pagina": 0},
    {"buscar": "x" * 101},
])
def test_los_limites_de_la_pagina(client, parametros):
    """Sin tope, `por_pagina=100000` devolvía la tabla entera."""
    r = client.get("/api/tickets", params=parametros, headers=_cab(client, "user@test.com"))
    assert r.status_code == 422
    assert r.json()["codigo"] == "validacion"
