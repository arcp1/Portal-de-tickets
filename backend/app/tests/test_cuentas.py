"""Alta y activación de cuentas por número de empleado.

En planta no todo el mundo tiene correo corporativo, pero **todos** tienen
número de empleado. Por eso el número es la llave y el correo es opcional.

El flujo: TI da de alta sin contraseña y entrega un código de un solo uso; la
persona define su propia contraseña. TI nunca conoce contraseñas ajenas.
"""

import pytest

from app.core.config import settings
from app.core.limitador import limitador_login
from app.models import Usuario
from app.services.cuentas_service import (
    ACTIVA, PENDIENTE, CuentasService, ErrorCuenta, normalizar_codigo, validar_password,
)


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


def crear_usuario(client, numero="20501", **extra):
    payload = {"nombre": "Persona Nueva", "numero_empleado": numero, "area": "Producción"}
    payload.update(extra)
    return client.post("/api/admin/usuarios", json=payload, headers=cab(client))


# ----------------------------------------------------------------------
# Alta
# ----------------------------------------------------------------------
def test_ti_da_de_alta_y_recibe_un_codigo(client):
    r = crear_usuario(client)

    assert r.status_code == 201
    datos = r.json()
    assert datos["numero_empleado"] == "20501"
    assert len(normalizar_codigo(datos["codigo"])) == 8


def test_se_puede_dar_de_alta_sin_correo(client, db_session):
    """Un operador de línea no tiene correo corporativo y debe poder entrar igual."""
    r = crear_usuario(client, numero="20502")

    assert r.status_code == 201
    usuario = db_session.query(Usuario).filter(Usuario.numero_empleado == "20502").first()
    assert usuario.email is None
    assert usuario.estado_cuenta == PENDIENTE


def test_la_cuenta_nace_sin_contrasena(client, db_session):
    crear_usuario(client)
    usuario = db_session.query(Usuario).filter(Usuario.numero_empleado == "20501").first()
    assert usuario.password_hash is None


def test_el_codigo_no_se_guarda_en_claro(client, db_session):
    codigo = crear_usuario(client).json()["codigo"]
    usuario = db_session.query(Usuario).filter(Usuario.numero_empleado == "20501").first()
    assert normalizar_codigo(codigo) not in (usuario.codigo_activacion_hash or "")


def test_no_se_repite_el_numero_de_empleado(client):
    crear_usuario(client)
    assert crear_usuario(client).status_code == 409


def test_no_se_repite_el_correo(client):
    crear_usuario(client, numero="20503", email="alguien@test.com")
    r = crear_usuario(client, numero="20504", email="alguien@test.com")
    assert r.status_code == 409


def test_si_hay_correo_se_valida_el_dominio(client):
    r = crear_usuario(client, numero="20505", email="alguien@gmail.com")
    assert r.status_code == 409
    assert "dominio" in r.json()["detail"].lower()


def test_solo_ti_da_de_alta(client):
    r = client.post("/api/admin/usuarios",
                    json={"nombre": "Otra Persona", "numero_empleado": "20599"},
                    headers=cab(client, "user@test.com"))
    assert r.status_code == 403


# ----------------------------------------------------------------------
# Activación con código
# ----------------------------------------------------------------------
def test_la_persona_activa_con_su_numero_y_codigo(client):
    codigo = crear_usuario(client).json()["codigo"]

    r = client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": codigo, "password": "MiClaveSegura1"})

    assert r.status_code == 200
    assert "access_token" in r.json()
    assert r.json()["user"]["numero_empleado"] == "20501"


def test_tras_activar_entra_con_su_numero(client):
    codigo = crear_usuario(client).json()["codigo"]
    client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": codigo, "password": "MiClaveSegura1"})

    assert client.post("/api/auth/login", json={
        "email": "20501", "password": "MiClaveSegura1"}).status_code == 200


def test_quien_tiene_correo_puede_entrar_con_cualquiera_de_los_dos(client):
    codigo = crear_usuario(client, numero="20506", email="dual@test.com").json()["codigo"]
    client.post("/api/auth/activar", json={
        "identificador": "20506", "codigo": codigo, "password": "MiClaveSegura1"})

    assert client.post("/api/auth/login", json={
        "email": "20506", "password": "MiClaveSegura1"}).status_code == 200
    assert client.post("/api/auth/login", json={
        "email": "dual@test.com", "password": "MiClaveSegura1"}).status_code == 200


def test_el_codigo_sirve_una_sola_vez(client):
    codigo = crear_usuario(client).json()["codigo"]
    client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": codigo, "password": "MiClaveSegura1"})

    segundo = client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": codigo, "password": "OtraClaveMia22"})
    assert segundo.status_code == 400


def test_el_codigo_se_acepta_como_lo_teclee_la_persona(client):
    codigo = crear_usuario(client).json()["codigo"]
    r = client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": codigo.replace("-", "").lower(),
        "password": "MiClaveSegura1"})
    assert r.status_code == 200


def test_un_codigo_equivocado_no_activa(client):
    crear_usuario(client)
    r = client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": "AAAA-BBBB", "password": "MiClaveSegura1"})
    assert r.status_code == 400


def test_no_se_revela_quien_esta_dado_de_alta(client):
    crear_usuario(client)

    fantasma = client.post("/api/auth/activar", json={
        "identificador": "99999", "codigo": "AAAA-BBBB", "password": "MiClaveSegura1"})
    real = client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": "AAAA-BBBB", "password": "MiClaveSegura1"})

    assert fantasma.status_code == real.status_code == 400
    assert fantasma.json()["detail"] == real.json()["detail"]


def test_regenerar_el_codigo_invalida_el_anterior(client):
    creado = crear_usuario(client).json()
    nuevo = client.post(f"/api/admin/usuarios/{creado['usuario_id']}/regenerar-codigo",
                        headers=cab(client)).json()["codigo"]

    assert client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": creado["codigo"],
        "password": "MiClaveSegura1"}).status_code == 400
    assert client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": nuevo,
        "password": "MiClaveSegura1"}).status_code == 200


# ----------------------------------------------------------------------
# Activación por verificación (la que hace viable cargar 300)
# ----------------------------------------------------------------------
def test_se_activa_con_la_fecha_de_ingreso(client):
    """Sin repartir códigos: la persona usa un dato que ya sabe."""
    crear_usuario(client, numero="20510", fecha_ingreso="2021-03-15")

    r = client.post("/api/auth/activar", json={
        "identificador": "20510", "fecha_ingreso": "2021-03-15",
        "password": "MiClaveSegura1"})

    assert r.status_code == 200


def test_la_fecha_se_acepta_en_formato_mexicano(client):
    crear_usuario(client, numero="20511", fecha_ingreso="2021-03-15")

    r = client.post("/api/auth/activar", json={
        "identificador": "20511", "fecha_ingreso": "15/03/2021",
        "password": "MiClaveSegura1"})
    assert r.status_code == 200


def test_una_fecha_equivocada_no_activa(client):
    crear_usuario(client, numero="20512", fecha_ingreso="2021-03-15")

    r = client.post("/api/auth/activar", json={
        "identificador": "20512", "fecha_ingreso": "2020-01-01",
        "password": "MiClaveSegura1"})
    assert r.status_code == 400


def test_sin_fecha_registrada_no_se_puede_activar_asi(client):
    """Quien no traiga fecha en el padrón necesita código sí o sí."""
    crear_usuario(client, numero="20513")

    r = client.post("/api/auth/activar", json={
        "identificador": "20513", "fecha_ingreso": "2021-03-15",
        "password": "MiClaveSegura1"})
    assert r.status_code == 400


def test_hay_que_mandar_codigo_o_fecha(client):
    crear_usuario(client, numero="20514")
    r = client.post("/api/auth/activar", json={
        "identificador": "20514", "password": "MiClaveSegura1"})
    assert r.status_code == 400


def test_el_estado_dice_que_metodo_acepta(client):
    crear_usuario(client, numero="20515", fecha_ingreso="2021-03-15")

    estado = client.post("/api/auth/estado-cuenta", json={"identificador": "20515"}).json()
    assert estado["accion"] == "activar"
    assert estado["acepta_codigo"] is True
    assert estado["acepta_verificacion"] is True


def test_el_estado_no_delata_a_nadie(client):
    inexistente = client.post("/api/auth/estado-cuenta", json={"identificador": "99999"}).json()
    activo = client.post("/api/auth/estado-cuenta", json={"identificador": "1001"}).json()
    assert inexistente["accion"] == activo["accion"] == "iniciar_sesion"


# ----------------------------------------------------------------------
# Contraseñas
# ----------------------------------------------------------------------
@pytest.mark.parametrize("mala", ["corta1", "1234567890123", "password"])
def test_se_rechazan_contrasenas_debiles(mala):
    assert validar_password(mala) is not None


def test_una_contrasena_razonable_se_acepta():
    assert validar_password("MiClaveDePlanta1") is None


def test_la_persona_cambia_su_contrasena(client):
    codigo = crear_usuario(client).json()["codigo"]
    sesion = client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": codigo, "password": "MiClaveSegura1"}).json()

    r = client.post("/api/auth/cambiar-password", json={
        "password_actual": "MiClaveSegura1", "password_nueva": "OtraDistinta2026"},
        headers={"Authorization": f"Bearer {sesion['access_token']}"})

    assert r.status_code == 200
    assert client.post("/api/auth/login", json={
        "email": "20501", "password": "OtraDistinta2026"}).status_code == 200


def test_no_se_cambia_sin_saber_la_actual(client):
    codigo = crear_usuario(client).json()["codigo"]
    sesion = client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": codigo, "password": "MiClaveSegura1"}).json()

    r = client.post("/api/auth/cambiar-password", json={
        "password_actual": "equivocada", "password_nueva": "OtraDistinta2026"},
        headers={"Authorization": f"Bearer {sesion['access_token']}"})
    assert r.status_code == 400


def test_restablecer_anula_la_contrasena_anterior(client):
    creado = crear_usuario(client).json()
    client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": creado["codigo"], "password": "MiClaveSegura1"})

    nuevo = client.post(f"/api/admin/usuarios/{creado['usuario_id']}/restablecer",
                        headers=cab(client)).json()["codigo"]

    assert client.post("/api/auth/login", json={
        "email": "20501", "password": "MiClaveSegura1"}).status_code == 401
    assert client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": nuevo,
        "password": "ClaveNueva2026"}).status_code == 200


# ----------------------------------------------------------------------
# Panel
# ----------------------------------------------------------------------
def test_el_panel_lista_a_las_personas(client):
    crear_usuario(client)
    filas = client.get("/api/admin/usuarios", headers=cab(client)).json()
    assert "20501" in [f["numero_empleado"] for f in filas]


def test_se_puede_buscar_por_numero(client):
    crear_usuario(client)
    filas = client.get("/api/admin/usuarios?buscar=20501", headers=cab(client)).json()
    assert len(filas) == 1


def test_el_panel_muestra_lo_que_cada_quien_tiene_a_su_cargo(client, db_session):
    from app.models import Equipo
    usuario = db_session.query(Usuario).filter(Usuario.numero_empleado == "1002").first()
    db_session.add(Equipo(sitio_id=1, tipo="activo", categoria="laptop", marca="HP",
                          modelo="440", estado="asignado", asignado_a=usuario.id))
    db_session.commit()

    filas = client.get("/api/admin/usuarios", headers=cab(client)).json()
    fila = next(f for f in filas if f["numero_empleado"] == "1002")
    assert fila["equipos_a_cargo"] == 1


def test_el_panel_es_solo_para_ti(client):
    assert client.get("/api/admin/usuarios", headers=cab(client, "user@test.com")).status_code == 403


def test_no_se_puede_quedar_sin_administradores(client, db_session):
    admin = db_session.query(Usuario).filter(Usuario.numero_empleado == "1001").first()
    r = client.patch(f"/api/admin/usuarios/{admin.id}", json={"rol": "usuario"}, headers=cab(client))
    assert r.status_code == 422


def test_nadie_se_desactiva_a_si_mismo(client, db_session):
    admin = db_session.query(Usuario).filter(Usuario.numero_empleado == "1001").first()
    r = client.patch(f"/api/admin/usuarios/{admin.id}", json={"activo": False}, headers=cab(client))
    assert r.status_code == 422


def test_desactivar_impide_entrar(client):
    creado = crear_usuario(client).json()
    client.post("/api/auth/activar", json={
        "identificador": "20501", "codigo": creado["codigo"], "password": "MiClaveSegura1"})

    client.patch(f"/api/admin/usuarios/{creado['usuario_id']}",
                 json={"activo": False}, headers=cab(client))

    assert client.post("/api/auth/login", json={
        "email": "20501", "password": "MiClaveSegura1"}).status_code == 400


def test_no_se_duplica_el_numero_al_editar(client):
    creado = crear_usuario(client).json()
    r = client.patch(f"/api/admin/usuarios/{creado['usuario_id']}",
                     json={"numero_empleado": "1001"}, headers=cab(client))
    assert r.status_code == 409


def test_se_registra_el_ultimo_acceso(client, db_session):
    client.post("/api/auth/login", json={"email": "1001", "password": "Secret123!"})
    admin = db_session.query(Usuario).filter(Usuario.numero_empleado == "1001").first()
    db_session.refresh(admin)
    assert admin.ultimo_acceso is not None
