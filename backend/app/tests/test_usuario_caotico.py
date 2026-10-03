"""El usuario distraído: lo que llega por error, no por mala intención.

Cada caso salió de una batería contra una copia del portal con Postgres
(2026-10-01): texto de puros espacios, emojis, campos vacíos, números
absurdos, fechas imposibles, ids que no existen, dobles clics. La regla es la
misma para todos: **un dato malo es un 4xx con un mensaje que se entienda,
nunca un 500, y nunca basura guardada como si fuera un dato.**

Lo que solo se ve con Postgres —el byte nulo, los enteros que no caben, los
dos clics simultáneos en «Crear ticket»— se prueba aquí a través de los
manejadores, que es la parte que no depende de la base.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError, IntegrityError

from app.main import app
from app.models import Equipo, ReglaNegocio, SolucionGeneral, Sitio, Usuario


def _cab(client, email="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ticket(client, cab, **extra):
    datos = {"sitio_id": 1, "categoria": "red", "descripcion_original": "Sin red en mi lugar"}
    datos.update(extra)
    return client.post("/api/tickets", json=datos, headers=cab)


def _es_4xx_legible(r, codigo):
    assert r.status_code == codigo, r.text
    cuerpo = r.json()
    assert isinstance(cuerpo["detail"], str) and cuerpo["detail"]


# ======================================================================
# Manejadores: lo que Postgres rechaza llega como 4xx
# ======================================================================

@pytest.fixture
def rutas_que_fallan():
    def dato_fuera_de_rango():
        raise DataError("SELECT", {}, Exception("integer out of range"))

    def choque():
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    def byte_nulo():
        raise ValueError("A string literal cannot contain NUL (0x00) characters.")

    def otro_value_error():
        raise ValueError("cualquier otra cosa")

    rutas = {"/api/_caos/rango": dato_fuera_de_rango, "/api/_caos/choque": choque,
             "/api/_caos/nulo": byte_nulo, "/api/_caos/otro": otro_value_error}
    for ruta, funcion in rutas.items():
        app.add_api_route(ruta, funcion)
    yield TestClient(app, raise_server_exceptions=False)
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in rutas]


def test_un_numero_que_no_cabe_en_la_base_es_422(rutas_que_fallan):
    _es_4xx_legible(rutas_que_fallan.get("/api/_caos/rango"), 422)


def test_una_restriccion_de_la_base_es_409(rutas_que_fallan):
    _es_4xx_legible(rutas_que_fallan.get("/api/_caos/choque"), 409)


def test_el_byte_nulo_pegado_de_otro_programa_es_422(rutas_que_fallan):
    r = rutas_que_fallan.get("/api/_caos/nulo")
    _es_4xx_legible(r, 422)
    assert "carácter no válido" in r.json()["detail"]


def test_otro_value_error_sigue_siendo_un_error_interno(rutas_que_fallan):
    """La red es para el byte nulo, no para tapar errores de verdad."""
    r = rutas_que_fallan.get("/api/_caos/otro")
    assert r.status_code == 500
    assert "cualquier otra cosa" not in r.text


# ======================================================================
# Tickets
# ======================================================================

@pytest.mark.parametrize("descripcion", ["", "     ", " " * 5000, "x" * 5001])
def test_descripcion_vacia_de_espacios_o_enorme(client, descripcion):
    r = _ticket(client, _cab(client, "user@test.com"), descripcion_original=descripcion)
    _es_4xx_legible(r, 422)
    assert "la descripción" in r.json()["detail"]


def test_la_descripcion_se_guarda_sin_los_espacios_de_los_extremos(client):
    r = _ticket(client, _cab(client, "user@test.com"),
                descripcion_original="   🔥 La impresora echa humo 💥   ")
    assert r.status_code == 201, r.text
    assert r.json()["descripcion_original"] == "🔥 La impresora echa humo 💥"


def test_categoria_inventada(client):
    _es_4xx_legible(_ticket(client, _cab(client, "user@test.com"), categoria="cafetera"), 422)


@pytest.mark.parametrize("equipo_id", [-1, 0, 99999, 2**31, 10**20])
def test_equipo_que_no_existe(client, equipo_id):
    r = _ticket(client, _cab(client, "user@test.com"), equipo_id=equipo_id)
    _es_4xx_legible(r, 422)


def test_equipo_de_otra_planta(client, db_session):
    otra = Sitio(clave="MTY", nombre="Planta Monterrey", pais="México", activo=True)
    db_session.add(otra)
    db_session.flush()
    ajeno = Equipo(sitio_id=otra.id, tipo="activo", categoria="laptop", marca="Dell", modelo="X")
    db_session.add(ajeno)
    db_session.commit()

    r = _ticket(client, _cab(client, "user@test.com"), equipo_id=ajeno.id)
    _es_4xx_legible(r, 422)


@pytest.mark.parametrize("comentario", ["", "    ", "\n\n\t", "x" * 5001])
def test_comentario_vacio_o_enorme(client, comentario):
    cab = _cab(client, "user@test.com")
    ticket = _ticket(client, cab).json()
    r = client.post(f"/api/tickets/{ticket['id']}/comments",
                    json={"comentario": comentario}, headers=cab)
    _es_4xx_legible(r, 422)


@pytest.mark.parametrize("ruta", ["/api/tickets/abc", "/api/tickets/1.5", "/api/tickets/-1"])
def test_id_de_ticket_que_no_es_un_numero_valido(client, ruta):
    r = client.get(ruta, headers=_cab(client))
    assert r.status_code in (404, 422), r.text
    assert isinstance(r.json()["detail"], str)


@pytest.mark.parametrize("pagina", [0, -1, 100_001, 10**20])
def test_pagina_absurda(client, pagina):
    r = client.get("/api/tickets", params={"pagina": pagina}, headers=_cab(client))
    _es_4xx_legible(r, 422)


def test_pagina_mas_alla_del_final_es_una_lista_vacia(client):
    r = client.get("/api/tickets", params={"pagina": 5000}, headers=_cab(client))
    assert r.status_code == 200
    assert r.json()["items"] == []


# ======================================================================
# Cuentas
# ======================================================================

def _alta(client, **extra):
    datos = {"nombre": "Persona Nueva", "numero_empleado": "5555"}
    datos.update(extra)
    return client.post("/api/admin/usuarios", json=datos, headers=_cab(client))


@pytest.mark.parametrize("extra", [
    {"rol": "superusuario"},
    {"idioma_preferido": "klingon"},
    {"nombre": "   "},
    {"area": "x" * 51},
    {"fecha_nacimiento": "2099-01-01"},
    {"fecha_nacimiento": "1700-01-01"},
    {"fecha_ingreso": "1900-01-01"},
    {"fecha_nacimiento": "31/02/2024"},
    {"numero_empleado": "🔥🔥"},
    {"numero_empleado": "12 34"},
    {"numero_empleado": "-123"},
])
def test_alta_con_datos_imposibles(client, extra):
    _es_4xx_legible(_alta(client, **extra), 422)


def test_alta_de_quien_empieza_la_semana_que_viene(client):
    """La fecha de ingreso puede ir un poco adelante: se da de alta antes del primer día."""
    from datetime import date, timedelta
    lunes = (date.today() + timedelta(days=7)).isoformat()
    assert _alta(client, fecha_ingreso=lunes).status_code == 201


@pytest.mark.parametrize("cambios", [
    {"nombre": ""}, {"nombre": "  "}, {"fecha_nacimiento": "2099-12-31"},
    {"fecha_nacimiento": "ayer"}, {"area": "x" * 51}, {"numero_empleado": "🔥"},
])
def test_edicion_con_datos_imposibles(client, db_session, cambios):
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.patch(f"/api/admin/usuarios/{usuario.id}", json=cambios, headers=_cab(client))
    _es_4xx_legible(r, 422)
    db_session.refresh(usuario)
    assert usuario.nombre == "User Test"


@pytest.mark.parametrize("accion", ["restablecer", "activacion-asistida"])
def test_el_admin_no_se_restablece_a_si_mismo(client, db_session, accion):
    """Lo dejaba fuera con un código en pantalla como única llave; con un
    solo admin en la planta, si cerraba el diálogo nadie podía darle otro."""
    admin = db_session.query(Usuario).filter_by(email="admin@test.com").one()
    r = client.post(f"/api/admin/usuarios/{admin.id}/{accion}", headers=_cab(client))
    _es_4xx_legible(r, 422)
    assert "Cambiar mi contraseña" in r.json()["detail"]

    db_session.refresh(admin)
    assert admin.estado_cuenta == "activa"
    assert client.get("/api/auth/me", headers=_cab(client)).status_code == 200


def test_el_admin_si_restablece_a_otra_persona(client, db_session):
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.post(f"/api/admin/usuarios/{usuario.id}/restablecer", headers=_cab(client))
    assert r.status_code == 200, r.text


# ======================================================================
# Inventario
# ======================================================================

def _equipo(client, **extra):
    datos = {"sitio_id": 1, "tipo": "activo", "categoria": "laptop", "marca": "Dell",
             "modelo": "Latitude"}
    datos.update(extra)
    return client.post("/api/equipos", json=datos, headers=_cab(client))


@pytest.mark.parametrize("extra", [
    {"marca": ""}, {"marca": "   "}, {"modelo": "x" * 51}, {"categoria": ""},
    {"numero_serie": "x" * 101}, {"tipo": "mágico"}, {"estado": "perdido"},
])
def test_equipo_con_campos_vacios_o_enormes(client, extra):
    _es_4xx_legible(_equipo(client, **extra), 422)


@pytest.mark.parametrize("campo", ["marca", "modelo", "categoria", "tipo", "estado"])
def test_editar_equipo_no_vacia_una_columna_obligatoria(client, campo):
    equipo = _equipo(client).json()
    r = client.patch(f"/api/equipos/{equipo['id']}", json={campo: None}, headers=_cab(client))
    _es_4xx_legible(r, 422)


# ======================================================================
# Reglas de negocio
# ======================================================================

def _regla(client, **extra):
    datos = {"sitio_id": 1, "categoria": "red", "condicion": "cable", "accion": "escalar"}
    datos.update(extra)
    return client.post("/api/reglas", json=datos, headers=_cab(client))


@pytest.mark.parametrize("extra", [
    {"condicion": ""}, {"condicion": "    "}, {"condicion": "x" * 101},
    {"accion": "borrar_todo"}, {"accion": "proveedor"}, {"accion": "proveedor", "destinatario": "  "},
    {"accion": "proveedor", "destinatario": "esto no es un correo"},
    {"accion": "proveedor", "destinatario": "soporte@"},
])
def test_regla_que_no_se_puede_guardar(client, extra):
    _es_4xx_legible(_regla(client, **extra), 422)


def test_proveedor_sin_destinatario_lo_dice_sin_nombres_tecnicos(client):
    detalle = _regla(client, accion="proveedor").json()["detail"]
    assert "destinatario" in detalle
    assert "solicitud" not in detalle


def test_una_regla_en_blanco_ya_guardada_no_casa_con_todo(client, db_session):
    """La cadena vacía está contenida en cualquier descripción: una regla así,
    con «auto», cerraba cada ticket de su categoría sin que nadie lo viera."""
    db_session.add(ReglaNegocio(sitio_id=1, categoria="red", condicion="   ",
                                accion="auto", activa=True))
    db_session.commit()

    r = _ticket(client, _cab(client, "user@test.com"))
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "abierto"


def test_el_comodin_sigue_abarcando_todo(client, db_session):
    db_session.add(ReglaNegocio(sitio_id=1, categoria="red", condicion="*",
                                accion="escalar", activa=True))
    db_session.commit()
    assert _ticket(client, _cab(client, "user@test.com")).json()["prioridad"] == "critica"


# ======================================================================
# Contenido de TI: editar no deja vacío lo que el alta exigió
# ======================================================================

def test_editar_kb_no_deja_el_titulo_ni_el_contenido_en_blanco(client):
    cab = _cab(client)
    entrada = client.post("/api/admin/kb", headers=cab, json={
        "titulo": "Reiniciar el router", "categoria": "red",
        "contenido": "Desconectar veinte segundos y volver a conectar.",
    })
    assert entrada.status_code == 201, entrada.text
    eid = entrada.json()["id"]
    for cambios in ({"titulo": ""}, {"titulo": "    "}, {"contenido": "   "}):
        _es_4xx_legible(client.patch(f"/api/admin/kb/{eid}", json=cambios, headers=cab), 422)


def test_editar_documentacion_no_la_deja_en_blanco(client):
    cab = _cab(client)
    doc = client.post("/api/documentacion", headers=cab, json={
        "categoria": "red", "titulo": "VLAN de impresoras",
        "contenido": "Las impresoras viven en la VLAN 30.",
    })
    assert doc.status_code == 201, doc.text
    for cambios in ({"titulo": " "}, {"contenido": ""}):
        r = client.patch(f"/api/documentacion/{doc.json()['id']}", json=cambios, headers=cab)
        _es_4xx_legible(r, 422)


def test_solucion_con_categoria_inventada_o_en_blanco(client, db_session):
    cab = _cab(client)
    base = {"titulo": "Impresora atascada", "contenido": "Abrir la bandeja y retirar la hoja."}
    _es_4xx_legible(client.post("/api/admin/soluciones", headers=cab,
                                json={**base, "categoria": "cafetera"}), 422)

    r = client.post("/api/admin/soluciones", headers=cab, json={**base, "categoria": "   "})
    assert r.status_code == 201, r.text
    # En blanco es «general», no una categoría llamada "".
    assert db_session.get(SolucionGeneral, r.json()["id"]).categoria is None


# ======================================================================
# La IA: lo que no se le manda
# ======================================================================

def test_un_mensaje_de_puros_espacios_no_llega_al_chat(client):
    r = client.post("/api/chat/mensaje", json={"mensaje": "      "},
                    headers=_cab(client, "user@test.com"))
    _es_4xx_legible(r, 422)


@pytest.mark.parametrize("ruta", ["/api/ia/normalizar", "/api/ia/similares"])
def test_un_pegado_enorme_no_va_al_modelo(client, ruta):
    """Con aforo 1, 60 000 caracteres dejaban a la planta sin IA minutos."""
    r = client.post(ruta, json={"texto": "x" * 60_000, "sitio_id": 1},
                    headers=_cab(client, "user@test.com"))
    _es_4xx_legible(r, 422)


@pytest.mark.parametrize("ruta", ["panorama", "aprendizaje", "consultas"])
@pytest.mark.parametrize("dias", [0, -5, 10**20])
def test_dias_absurdos_en_conciencia(client, ruta, dias):
    """Veinte cifras desbordaban la resta de fechas: era un 500."""
    r = client.get(f"/api/admin/conciencia/{ruta}", params={"dias": dias}, headers=_cab(client))
    _es_4xx_legible(r, 422)


def test_el_correo_del_proveedor_se_guarda_limpio(client):
    """El aviso sale por correo: se guarda la dirección, sin el nombre."""
    r = _regla(client, accion="proveedor", destinatario="Soporte Zebra <soporte@zebra.com.mx>")
    assert r.status_code == 201, r.text
    assert r.json()["destinatario"] == "soporte@zebra.com.mx"


# ======================================================================
# Cuerpos enormes
# ======================================================================

def test_un_json_enorme_se_corta_antes_de_parsearlo(client):
    """NGINX deja pasar 20 MB; parsear eso en JSON son cientos de MB de RAM."""
    r = client.post("/api/tickets", content=b'{"x": "' + b"a" * (2 * 1024 * 1024) + b'"}',
                    headers={**_cab(client), "content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["detail"] == "La solicitud es demasiado grande."


def test_un_json_enorme_en_trozos_tambien_se_corta(client):
    """Sin `Content-Length` (transferencia en trozos) se cuentan los bytes."""
    def trozos():
        yield b'{"x": "'
        for _ in range(40):
            yield b"a" * 65536
        yield b'"}'

    r = client.post("/api/tickets", content=trozos(),
                    headers={**_cab(client), "content-type": "application/json"})
    assert r.status_code == 413


def test_las_subidas_no_pasan_por_el_tope_de_json(client):
    cab = _cab(client, "user@test.com")
    ticket = _ticket(client, cab).json()
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 13 + b"\x00" * (2 * 1024 * 1024))
    r = client.post(f"/api/tickets/{ticket['id']}/adjuntos", headers=cab,
                    files={"archivo": ("grande.png", png, "image/png")})
    assert r.status_code != 413, r.text


def test_una_sola_sesion_no_acapara_la_ia(client, monkeypatch):
    """La compuerta protege al modelo pero no reparte: un script mantenía la
    sala llena y los demás se quedaban sin asistente."""
    from app.core import limitador as modulo
    monkeypatch.setattr(modulo.limitador_ia, "maximo", 2)
    cab = _cab(client, "user@test.com")
    cuerpo = {"texto": "La impresora no imprime", "categoria": "impresora"}
    for _ in range(2):
        assert client.post("/api/asistente/buscar", json=cuerpo, headers=cab).status_code == 200
    r = client.post("/api/asistente/buscar", json=cuerpo, headers=cab)
    assert r.status_code == 429
    # El cupo es de cada quien: otra persona sigue teniendo el suyo.
    assert client.post("/api/asistente/buscar", json=cuerpo, headers=_cab(client)).status_code == 200
