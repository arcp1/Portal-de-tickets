"""Las dos formas de sacar a alguien del portal, que no son la misma.

**Dar de baja** le corta el acceso y se deshace: la persona sigue en el padrón,
bajo su filtro, y mañana se le puede devolver la entrada.

**Eliminar** la saca del padrón para siempre. Lo que dejó hecho —tickets,
comentarios, resguardos, documentos— se conserva con su nombre puesto, porque
un historial firmado por nadie no le sirve a quien lo lea dentro de un año.
Lo que desaparece es lo que la identifica y lo que la dejaba entrar.

Lo que estas pruebas cuidan es justo la diferencia entre las dos: que la baja
sea reversible y no se vea salvo que se pida, y que la eliminación no se lleve
por delante el historial ni deje una puerta abierta.
"""

import pytest

from app.core.config import settings
from app.core.limitador import limitador_login
from app.models import Ticket, Usuario


def token(client, identificador="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": password})
    return r.json()["access_token"]


def cab(client, identificador="admin@test.com"):
    return {"Authorization": f"Bearer {token(client, identificador=identificador)}"}


@pytest.fixture(autouse=True)
def sin_limites(monkeypatch):
    limitador_login._intentos.clear()
    monkeypatch.setattr(settings, "DOMINIOS_PERMITIDOS", "test.com")
    yield
    limitador_login._intentos.clear()


def crear_usuario(client, numero="20501", nombre="Persona Nueva", **extra):
    payload = {"nombre": nombre, "numero_empleado": numero, "area": "Producción"}
    payload.update(extra)
    return client.post("/api/admin/usuarios", json=payload, headers=cab(client)).json()


def dar_de_baja(client, usuario_id):
    return client.patch(f"/api/admin/usuarios/{usuario_id}",
                        json={"activo": False}, headers=cab(client))


def numeros(client, consulta=""):
    filas = client.get(f"/api/admin/usuarios{consulta}", headers=cab(client)).json()
    return [f["numero_empleado"] for f in filas]


# ----------------------------------------------------------------------
# Baja: se ve solo cuando se pide
# ----------------------------------------------------------------------
def test_quien_esta_de_baja_no_sale_en_la_lista_normal(client):
    creado = crear_usuario(client)
    dar_de_baja(client, creado["usuario_id"])

    assert "20501" not in numeros(client)


def test_quien_esta_de_baja_sale_con_su_filtro(client):
    creado = crear_usuario(client)
    dar_de_baja(client, creado["usuario_id"])

    assert "20501" in numeros(client, "?estado=baja")


def test_el_filtro_de_bajas_no_trae_a_quien_si_tiene_acceso(client):
    crear_usuario(client)
    assert "20501" not in numeros(client, "?estado=baja")


def test_buscar_por_nombre_tampoco_saca_a_un_dado_de_baja(client):
    """Si no, la baja se ve igual: basta teclear el nombre para tenerla delante."""
    creado = crear_usuario(client)
    dar_de_baja(client, creado["usuario_id"])

    assert numeros(client, "?buscar=Persona") == []


def test_los_filtros_de_estado_de_cuenta_solo_miran_a_quien_entra(client):
    """«Por activar» habla de la cuenta; una cuenta sin acceso no está por
    activar para nadie."""
    creado = crear_usuario(client)
    dar_de_baja(client, creado["usuario_id"])

    assert "20501" not in numeros(client, "?estado=pendiente_activacion")


def test_la_baja_se_deshace(client):
    creado = crear_usuario(client)
    dar_de_baja(client, creado["usuario_id"])

    client.patch(f"/api/admin/usuarios/{creado['usuario_id']}",
                 json={"activo": True}, headers=cab(client))

    assert "20501" in numeros(client)


# ----------------------------------------------------------------------
# Eliminación: la persona se va, su historial se queda
# ----------------------------------------------------------------------
def test_eliminar_saca_a_la_persona_de_todas_las_listas(client):
    creado = crear_usuario(client)

    r = client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    assert r.status_code == 200
    assert numeros(client) == ["1001", "1002"]
    # Ni siquiera bajo el filtro de bajas: para el portal esa persona ya no está.
    assert numeros(client, "?estado=baja") == []
    assert numeros(client, "?buscar=Persona") == []


def test_eliminar_conserva_los_tickets_con_el_nombre_puesto(client, db_session):
    """El motivo por el que la fila no se borra: once columnas apuntan aquí."""
    creado = crear_usuario(client)
    db_session.add(Ticket(
        sitio_id=1, usuario_id=creado["usuario_id"], folio="TICK-QRO-2026-0900",
        categoria="impresora", descripcion_original="No imprime", estado="cerrado",
    ))
    db_session.commit()

    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    ticket = db_session.query(Ticket).filter(Ticket.folio == "TICK-QRO-2026-0900").first()
    assert ticket is not None
    assert ticket.usuario.nombre == "Persona Nueva"


def test_eliminar_libera_el_numero_de_empleado(client):
    """La plantilla rota y los números se reutilizan; si el número se quedara
    ocupado por alguien que ya no está, el alta siguiente chocaría contra un
    fantasma."""
    creado = crear_usuario(client, numero="20501")
    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    r = client.post("/api/admin/usuarios",
                    json={"nombre": "Otra Persona", "numero_empleado": "20501"},
                    headers=cab(client))

    assert r.status_code == 201


def test_una_cuenta_eliminada_no_vuelve_a_entrar(client):
    creado = crear_usuario(client)
    client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": creado["codigo"], "password": "MiClaveSegura1"})

    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    r = client.post("/api/auth/login", json={"email": "20501", "password": "MiClaveSegura1"})
    assert r.status_code == 401


def test_eliminar_borra_lo_que_identifica_a_la_persona(client, db_session):
    creado = crear_usuario(client, email="persona@test.com", numero_epp="0421")
    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    usuario = db_session.query(Usuario).filter(Usuario.id == creado["usuario_id"]).first()
    assert usuario.eliminado_en is not None
    assert usuario.numero_empleado is None
    assert usuario.email is None
    assert usuario.numero_epp is None
    assert usuario.password_hash is None
    assert usuario.codigo_activacion_hash is None
    # Lo único que sobrevive es lo que hace legible el historial.
    assert usuario.nombre == "Persona Nueva"


def test_eliminar_echa_fuera_la_sesion_que_estuviera_abierta(client):
    """Sin esto, quien tuviera el portal abierto seguía dentro sus ocho horas."""
    creado = crear_usuario(client)
    client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": creado["codigo"], "password": "MiClaveSegura1"})
    suyo = {"Authorization": f"Bearer {token(client, '20501', 'MiClaveSegura1')}"}
    assert client.get("/api/auth/me", headers=suyo).status_code == 200

    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    assert client.get("/api/auth/me", headers=suyo).status_code == 401


def test_no_se_le_puede_asignar_nada_a_quien_fue_eliminado(client):
    """El selector de «asignado a» y el de emisión de resguardos beben de aquí."""
    creado = crear_usuario(client)
    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    lista = client.get("/api/auth/usuarios?solo_activos=false", headers=cab(client)).json()
    assert creado["usuario_id"] not in [u["id"] for u in lista]


def test_sobre_una_cuenta_eliminada_no_se_opera(client):
    """Y responde 404, no «fue eliminada»: si lo dijera, recorrer ids sería una
    forma de averiguar quién trabajó aquí."""
    creado = crear_usuario(client)
    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    ident = creado["usuario_id"]
    assert client.patch(f"/api/admin/usuarios/{ident}", json={"activo": True},
                        headers=cab(client)).status_code == 404
    assert client.post(f"/api/admin/usuarios/{ident}/restablecer",
                       headers=cab(client)).status_code == 404
    assert client.delete(f"/api/admin/usuarios/{ident}", headers=cab(client)).status_code == 404


def test_eliminar_queda_en_la_bitacora(client, db_session):
    from app.models import Auditoria
    creado = crear_usuario(client)
    client.delete(f"/api/admin/usuarios/{creado['usuario_id']}", headers=cab(client))

    entrada = db_session.query(Auditoria).filter(
        Auditoria.accion == "usuario.eliminado").first()
    assert entrada is not None
    # Con la huella de lo que se borró: después ya no se puede reconstruir.
    assert entrada.detalle["numero_empleado"] == "20501"


# ----------------------------------------------------------------------
# Lo que la operación no deja hacer
# ----------------------------------------------------------------------
def test_nadie_se_elimina_a_si_mismo(client, db_session):
    admin = db_session.query(Usuario).filter(Usuario.numero_empleado == "1001").first()
    r = client.delete(f"/api/admin/usuarios/{admin.id}", headers=cab(client))
    assert r.status_code == 422


def test_el_sitio_nunca_se_queda_sin_administrador(client, db_session):
    """La regla que de verdad protege al sitio es la de arriba: nadie se
    elimina a sí mismo.

    Con ella puesta, borrar al «último» administrador no es alcanzable —quien
    ejecuta la operación es un administrador activo y no es el objetivo—, así
    que lo que se comprueba aquí es la consecuencia: se puede eliminar a otro
    administrador, y siempre queda al menos quien lo hizo.
    """
    otro = crear_usuario(client, numero="20777", nombre="Segundo Admin")
    client.patch(f"/api/admin/usuarios/{otro['usuario_id']}",
                 json={"rol": "admin"}, headers=cab(client))

    assert client.delete(f"/api/admin/usuarios/{otro['usuario_id']}",
                         headers=cab(client)).status_code == 200

    quedan = db_session.query(Usuario).filter(
        Usuario.rol == "admin", Usuario.activo.is_(True),
        Usuario.eliminado_en.is_(None)).count()
    assert quedan >= 1


def test_eliminar_es_solo_de_ti(client):
    creado = crear_usuario(client)
    r = client.delete(f"/api/admin/usuarios/{creado['usuario_id']}",
                      headers=cab(client, "user@test.com"))
    assert r.status_code == 403
