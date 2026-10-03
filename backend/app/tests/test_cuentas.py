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
from app.services.cuentas_service import PENDIENTE, normalizar_codigo, validar_password


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
        "identificador": "20510", "nombre_completo": "Persona Nueva",
        "fecha_ingreso": "2021-03-15",
        "password": "MiClaveSegura1"})

    assert r.status_code == 200


def test_la_fecha_se_acepta_en_formato_mexicano(client):
    crear_usuario(client, numero="20511", fecha_ingreso="2021-03-15")

    r = client.post("/api/auth/activar", json={
        "identificador": "20511", "nombre_completo": "Persona Nueva",
        "fecha_ingreso": "15/03/2021",
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


# ----------------------------------------------------------------------
# Fecha de nacimiento: el dato que la gente sí recuerda
# ----------------------------------------------------------------------
def test_se_activa_con_la_fecha_de_nacimiento(client):
    """La de ingreso no la recuerda medio mundo; su cumpleaños sí."""
    crear_usuario(client, numero="20520", fecha_nacimiento="1966-06-09")

    r = client.post("/api/auth/activar", json={
        "identificador": "20520", "nombre_completo": "Persona Nueva",
        "fecha_nacimiento": "09/06/1966",
        "password": "MiClaveSegura1"})

    assert r.status_code == 200


def test_una_fecha_de_nacimiento_equivocada_no_activa(client):
    crear_usuario(client, numero="20521", fecha_nacimiento="1966-06-09")

    r = client.post("/api/auth/activar", json={
        "identificador": "20521", "fecha_nacimiento": "1966-06-10",
        "password": "MiClaveSegura1"})
    assert r.status_code == 400


def test_no_se_puede_activar_con_la_fecha_de_otro_campo(client):
    """Traer una fecha no habilita la otra: cada dato verifica lo suyo."""
    crear_usuario(client, numero="20522", fecha_nacimiento="1966-06-09")

    r = client.post("/api/auth/activar", json={
        "identificador": "20522", "fecha_ingreso": "1966-06-09",
        "password": "MiClaveSegura1"})
    assert r.status_code == 400


def test_el_estado_dice_que_datos_pedir(client):
    """La pantalla pide siempre lo mismo, tenga lo que tenga la cuenta.

    Antes adaptaba los campos a cada quien, y eso era la fuga: la lista
    devuelta describia que datos hay registrados de esa persona. Se cambio por
    una lista fija; quien no tenga esos datos falla al final, sin que la
    pantalla haya dicho nada de el por el camino.
    """
    crear_usuario(client, numero="20523", fecha_nacimiento="1966-06-09")
    crear_usuario(client, numero="20524", fecha_ingreso="2021-03-15")

    con_nacimiento = client.post("/api/auth/estado-cuenta",
                                 json={"identificador": "20523"}).json()
    con_ingreso = client.post("/api/auth/estado-cuenta",
                              json={"identificador": "20524"}).json()

    assert con_nacimiento == con_ingreso


def test_sin_ningun_dato_no_hay_verificacion(client):
    crear_usuario(client, numero="20525")
    estado = client.post("/api/auth/estado-cuenta", json={"identificador": "20525"}).json()

    # La pantalla ofrece la via igual que a todos —no delata que esta cuenta no
    # tiene datos—, pero intentarla no lleva a ningun lado: hace falta codigo.
    assert estado["datos_verificacion"] == [
        "nombre_completo", "numero_epp", "fecha_nacimiento"]
    assert client.post("/api/auth/activar", json={
        "identificador": "20525", "nombre_completo": "Persona Nueva",
        "numero_epp": "0421", "fecha_nacimiento": "1966-06-09",
        "password": "MiClaveSegura1"}).status_code == 400


# ----------------------------------------------------------------------
# Número de EPP: el segundo factor
#
# Cada quien tiene cuatro dígitos con los que saca su equipo de protección. Los
# usa seguido, así que se los sabe. Eso permite pedir dos datos en vez de uno.
# ----------------------------------------------------------------------
def test_con_epp_y_cumpleanos_se_piden_los_dos(client):
    crear_usuario(client, numero="20540", numero_epp="0421",
                  fecha_nacimiento="1966-06-09")

    estado = client.post("/api/auth/estado-cuenta",
                         json={"identificador": "20540"}).json()

    # La lista es fija. Devolver los factores reales delataba que tiene
    # registrado cada cuenta: una con solo nombre respondia uno y una completa
    # tres, y esa diferencia ya es un dato sobre esa persona.
    assert estado["datos_verificacion"] == [
        "nombre_completo", "numero_epp", "fecha_nacimiento"]


def test_acertando_los_dos_se_activa(client):
    crear_usuario(client, numero="20541", numero_epp="0421",
                  fecha_nacimiento="1966-06-09")

    r = client.post("/api/auth/activar", json={
        "identificador": "20541", "nombre_completo": "Persona Nueva",
        "numero_epp": "0421",
        "fecha_nacimiento": "09/06/1966", "password": "MiClaveSegura1"})

    assert r.status_code == 200


def test_acertar_uno_de_dos_no_alcanza(client):
    """Sin crédito parcial: media identidad no es identidad."""
    crear_usuario(client, numero="20542", numero_epp="0421",
                  fecha_nacimiento="1966-06-09")

    solo_fecha = client.post("/api/auth/activar", json={
        "identificador": "20542", "fecha_nacimiento": "09/06/1966",
        "password": "MiClaveSegura1"})
    solo_epp = client.post("/api/auth/activar", json={
        "identificador": "20542", "numero_epp": "0421",
        "password": "MiClaveSegura1"})

    assert solo_fecha.status_code == 400
    assert solo_epp.status_code == 400


def test_el_epp_se_acepta_con_o_sin_ceros(client):
    """La misma persona lo escribe 0421 o 421 según el día."""
    crear_usuario(client, numero="20543", numero_epp="0421",
                  fecha_nacimiento="1966-06-09")

    r = client.post("/api/auth/activar", json={
        "identificador": "20543", "nombre_completo": "Persona Nueva",
        "numero_epp": "421",
        "fecha_nacimiento": "1966-06-09", "password": "MiClaveSegura1"})

    assert r.status_code == 200


def test_un_epp_equivocado_no_activa(client):
    crear_usuario(client, numero="20544", numero_epp="0421",
                  fecha_nacimiento="1966-06-09")

    r = client.post("/api/auth/activar", json={
        "identificador": "20544", "numero_epp": "9999",
        "fecha_nacimiento": "1966-06-09", "password": "MiClaveSegura1"})

    assert r.status_code == 400


def test_la_fecha_de_ingreso_nunca_se_pide_como_segundo_factor(client):
    """Pedirla sería repetir el error que dejó fuera a media planta."""
    crear_usuario(client, numero="20545", fecha_nacimiento="1966-06-09",
                  fecha_ingreso="2021-03-15")

    # Se comprueba contra lo que el backend exige de verdad, no contra lo que
    # la pantalla muestra: eso ahora es una lista fija para todos.
    filas = client.get("/api/admin/usuarios?buscar=20545", headers=cab(client)).json()
    assert filas[0]["datos_verificacion"] == ["fecha_nacimiento"]
    assert client.post("/api/auth/activar", json={
        "identificador": "20545", "nombre_completo": "Persona Nueva",
        "fecha_nacimiento": "1966-06-09",
        "password": "MiClaveSegura1"}).status_code == 200


def test_con_un_solo_factor_se_pide_uno(client):
    """No se puede exigir un dato que nadie capturó."""
    crear_usuario(client, numero="20546", numero_epp="0421")

    estado = client.post("/api/auth/estado-cuenta",
                         json={"identificador": "20546"}).json()
    # Se piden siempre los mismos tres, tenga lo que tenga la cuenta.
    assert estado["datos_verificacion"] == [
        "nombre_completo", "numero_epp", "fecha_nacimiento"]

    # Y se activa con lo que si tiene registrado: nombre y EPP.
    assert client.post("/api/auth/activar", json={
        "identificador": "20546", "nombre_completo": "Persona Nueva",
        "numero_epp": "0421",
        "password": "MiClaveSegura1"}).status_code == 200


def test_se_puede_exigir_un_solo_factor_por_configuracion(client, monkeypatch):
    """El tope es ajustable: en una planta chica quizá con uno basta."""
    monkeypatch.setattr(settings, "VERIFICACION_FACTORES", 1)
    crear_usuario(client, numero="20547", numero_epp="0421",
                  fecha_nacimiento="1966-06-09")

    r = client.post("/api/auth/activar", json={
        "identificador": "20547", "nombre_completo": "Persona Nueva",
        "numero_epp": "0421",
        "password": "MiClaveSegura1"})

    assert r.status_code == 200


def test_el_panel_dice_quien_quedo_con_un_solo_factor(client):
    """Para que TI sepa a quién pedirle a RH el número de EPP."""
    crear_usuario(client, numero="20548", fecha_nacimiento="1966-06-09")
    crear_usuario(client, numero="20549", numero_epp="0421",
                  fecha_nacimiento="1966-06-09")

    filas = client.get("/api/admin/usuarios?buscar=2054", headers=cab(client)).json()
    por_numero = {u["numero_empleado"]: u for u in filas}

    # El nombre no aparece: no es un secreto, y contarlo escondería justo las
    # cuentas débiles que esta columna existe para señalar.
    assert por_numero["20548"]["datos_verificacion"] == ["fecha_nacimiento"]
    assert len(por_numero["20549"]["datos_verificacion"]) == 2


def test_se_puede_buscar_por_numero_de_epp(client):
    """En el almacén la gente llega diciendo su número de EPP, no el otro."""
    crear_usuario(client, numero="20550", numero_epp="7788")

    filas = client.get("/api/admin/usuarios?buscar=7788", headers=cab(client)).json()

    assert any(u["numero_empleado"] == "20550" for u in filas)


# ----------------------------------------------------------------------
# Activación asistida en mostrador
#
# La salida para quien no recuerda ninguna fecha y nunca va a recibir un
# papelito: TI comprueba el gafete y la persona teclea su contraseña ahí mismo.
# ----------------------------------------------------------------------
def test_ti_abre_una_activacion_en_mostrador(client):
    crear_usuario(client, numero="20530")

    r = client.post("/api/admin/usuarios/{}/activacion-asistida".format(
        _id_de(client, "20530")), headers=cab(client))

    assert r.status_code == 200
    assert r.json()["codigo"]


def test_la_persona_define_su_contrasena_en_el_mostrador(client, db_session):
    """Lo importante: TI abre la puerta, pero la contraseña no la conoce."""
    crear_usuario(client, numero="20531")
    codigo = client.post(
        "/api/admin/usuarios/{}/activacion-asistida".format(_id_de(client, "20531")),
        headers=cab(client)).json()["codigo"]

    r = client.post("/api/auth/activar", json={
        "identificador": "20531", "codigo": codigo, "password": "LaQueYoElija1"})

    assert r.status_code == 200
    assert client.post("/api/auth/login", json={
        "email": "20531", "password": "LaQueYoElija1"}).status_code == 200


def test_la_asistida_sirve_una_sola_vez(client):
    crear_usuario(client, numero="20532")
    codigo = client.post(
        "/api/admin/usuarios/{}/activacion-asistida".format(_id_de(client, "20532")),
        headers=cab(client)).json()["codigo"]

    client.post("/api/auth/activar", json={
        "identificador": "20532", "codigo": codigo, "password": "LaQueYoElija1"})
    segunda = client.post("/api/auth/activar", json={
        "identificador": "20532", "codigo": codigo, "password": "OtraDistinta12"})

    assert segunda.status_code == 400


def test_la_asistida_dura_minutos_no_dias(client, db_session):
    """No es un código para entregar: se gasta en el momento."""
    from datetime import datetime

    crear_usuario(client, numero="20533")
    client.post("/api/admin/usuarios/{}/activacion-asistida".format(
        _id_de(client, "20533")), headers=cab(client))

    usuario = db_session.query(Usuario).filter(Usuario.numero_empleado == "20533").first()
    db_session.refresh(usuario)
    minutos = (usuario.codigo_expira - datetime.utcnow()).total_seconds() / 60
    assert 0 < minutos <= settings.ACTIVACION_ASISTIDA_MINUTOS + 1


def test_tambien_sirve_para_quien_ya_tenia_contrasena(client, db_session):
    """Se le olvidó y está enfrente: se le reabre sin inventarle una temporal."""
    crear_usuario(client, numero="20534", fecha_nacimiento="1966-06-09")
    client.post("/api/auth/activar", json={
        "identificador": "20534", "fecha_nacimiento": "1966-06-09",
        "password": "LaPrimeraQueUse"})

    client.post("/api/admin/usuarios/{}/activacion-asistida".format(
        _id_de(client, "20534")), headers=cab(client))

    usuario = db_session.query(Usuario).filter(Usuario.numero_empleado == "20534").first()
    db_session.refresh(usuario)
    assert usuario.estado_cuenta == PENDIENTE
    assert usuario.password_hash is None


def test_la_asistida_es_solo_de_ti(client):
    crear_usuario(client, numero="20535")
    r = client.post("/api/admin/usuarios/{}/activacion-asistida".format(
        _id_de(client, "20535")), headers=cab(client, "user@test.com"))
    assert r.status_code == 403


def test_la_asistida_queda_en_bitacora(client):
    """Es una acción con poder: tiene que saberse quién asistió a quién."""
    crear_usuario(client, numero="20536")
    client.post("/api/admin/usuarios/{}/activacion-asistida".format(
        _id_de(client, "20536")), headers=cab(client))

    bitacora = client.get("/api/auditoria?accion=usuario.activacion_asistida",
                          headers=cab(client)).json()
    eventos = bitacora if isinstance(bitacora, list) else bitacora.get("items", [])
    assert len(eventos) >= 1


def _id_de(client, numero):
    """El id de una persona, buscándola por su número de empleado."""
    resultado = client.get(f"/api/admin/usuarios?buscar={numero}", headers=cab(client)).json()
    filas = resultado if isinstance(resultado, list) else resultado.get("items", [])
    return next(u["id"] for u in filas if u["numero_empleado"] == numero)


def test_el_estado_no_delata_a_nadie(client):
    """La respuesta es identica exista la cuenta, no exista, o este activa.

    Antes se distinguian: una cuenta pendiente contestaba "activar" con sus
    factores y las demas "iniciar_sesion". Con numeros del 1 al 600, recorrer
    el rango devolvia el padron entero.
    """
    inexistente = client.post("/api/auth/estado-cuenta", json={"identificador": "99999"}).json()
    activo = client.post("/api/auth/estado-cuenta", json={"identificador": "1001"}).json()
    crear_usuario(client, numero="20599", numero_epp="0421", fecha_nacimiento="1980-01-01")
    pendiente = client.post("/api/auth/estado-cuenta", json={"identificador": "20599"}).json()

    assert inexistente == activo == pendiente


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

    # 401 y no 400: el login responde lo mismo para "no existe", "contrasena
    # incorrecta", "sin activar" y "dada de baja". Distinguirlos convertia la
    # pantalla de entrada en una forma de averiguar quien trabaja aqui.
    assert client.post("/api/auth/login", json={
        "email": "20501", "password": "MiClaveSegura1"}).status_code == 401


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


# ----------------------------------------------------------------------
# Corregir el número de empleado (2026-10-02)
# ----------------------------------------------------------------------

def test_se_corrige_el_numero_de_una_cuenta_sin_activar(client, db_session):
    """Un número mal tecleado en el alta solo se arreglaba borrando la cuenta.
    El código ya entregado sigue sirviendo con el número corregido."""
    from app.models import Auditoria

    creado = crear_usuario(client, numero="20599").json()
    r = client.patch(f"/api/admin/usuarios/{creado['usuario_id']}",
                     json={"numero_empleado": "20509"}, headers=cab(client))
    assert r.status_code == 200, r.text

    entrada = db_session.query(Auditoria).filter_by(accion="usuario.numero_corregido").one()
    assert entrada.detalle == {"antes": "20599", "despues": "20509"}

    r = client.post("/api/auth/activar", json={
        "identificador": "20509", "codigo": creado["codigo"], "password": "UnaClaveLarga2026"})
    assert r.status_code == 200, r.text


def test_no_se_corrige_el_numero_de_una_cuenta_activa(client, db_session):
    """Ya entra con él: cambiarlo la dejaría fuera con la contraseña en la mano."""
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.patch(f"/api/admin/usuarios/{usuario.id}",
                     json={"numero_empleado": "1099"}, headers=cab(client))
    assert r.status_code == 422
    assert "no se ha activado" in r.json()["detail"]
    db_session.refresh(usuario)
    assert usuario.numero_empleado == "1002"


def test_mandar_el_mismo_numero_de_una_cuenta_activa_no_es_un_cambio(client, db_session):
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    r = client.patch(f"/api/admin/usuarios/{usuario.id}",
                     json={"numero_empleado": "1002"}, headers=cab(client))
    assert r.status_code == 200


def test_el_numero_provisional_se_sustituye_aunque_la_cuenta_este_activa(client, db_session):
    usuario = db_session.query(Usuario).filter_by(email="user@test.com").one()
    usuario.numero_empleado = "TMP-00002"
    db_session.commit()
    r = client.patch(f"/api/admin/usuarios/{usuario.id}",
                     json={"numero_empleado": "1002"}, headers=cab(client))
    assert r.status_code == 200, r.text


def test_corregir_a_un_numero_ocupado_choca(client):
    creado = crear_usuario(client, numero="20598").json()
    r = client.patch(f"/api/admin/usuarios/{creado['usuario_id']}",
                     json={"numero_empleado": "1002"}, headers=cab(client))
    assert r.status_code == 409
