"""Propiedades de seguridad que se rompieron una vez y no deben volver a romperse.

Cada prueba de aquí corresponde a un hallazgo real de la auditoría. No prueban
funcionalidad: prueban que **no** se pueda hacer algo. Por eso viven juntas y no
repartidas por los archivos de cada módulo — si mañana alguien "simplifica" una
comprobación de permisos, esto es lo que se pone en rojo.
"""

from datetime import datetime

import pytest

from app.core.limitador import Limitador
from app.core.security import create_access_token
from app.models import BaseConocimiento, Sitio, SugerenciaKB, Ticket, Usuario
from app.services.cuentas_service import CuentasService, validar_password
from app.services.importacion_service import _neutro


def token(client, email="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


def cab(client, email="admin@test.com", password="Secret123!"):
    return {"Authorization": f"Bearer {token(client, email, password)}"}


# ======================================================================
# Fuga entre plantas
# ======================================================================

def test_la_busqueda_no_deja_elegir_la_planta(client, db_session):
    """`/ia/similares` aceptaba el `sitio_id` del cuerpo.

    Con eso, cualquiera con sesión podía pedir la planta que quisiera y leerse
    la base de conocimiento ajena entera: título y solución completa.
    """
    otra = Sitio(clave="MTY", nombre="Planta Monterrey", pais="México", activo=True)
    db_session.add(otra)
    db_session.commit()
    db_session.refresh(otra)

    db_session.add(BaseConocimiento(
        sitio_id=otra.id,
        titulo="Secreto de la otra planta",
        contenido="Procedimiento que no debe salir de Monterrey.",
        categoria="equipo",
    ))
    db_session.commit()

    r = client.post("/api/ia/similares", headers=cab(client), json={
        "texto": "Procedimiento que no debe salir de Monterrey",
        "sitio_id": otra.id,          # se pide explícitamente la planta ajena
        "categoria": "equipo",
    })

    assert r.status_code == 200
    titulos = [s["titulo"] for s in r.json()["resultados"]]
    assert "Secreto de la otra planta" not in titulos



def test_ti_alcanza_tickets_de_todas_las_plantas_y_una_persona_no(client, db_session):
    """TI es global; una persona de planta no ve ni el ticket ajeno."""
    otra = Sitio(clave="MTY", nombre="Planta Monterrey", pais="México", activo=True)
    db_session.add(otra)
    db_session.commit()
    db_session.refresh(otra)

    ajeno = Usuario(sitio_id=otra.id, nombre="De Monterrey", email="mty@test.com",
                    numero_empleado="9001", rol="usuario", activo=True,
                    estado_cuenta="activa")
    db_session.add(ajeno)
    db_session.commit()
    db_session.refresh(ajeno)

    ticket = Ticket(sitio_id=otra.id, folio="TICK-MTY-2026-0001", usuario_id=ajeno.id,
                    categoria="equipo", descripcion_original="Falla en Monterrey",
                    prioridad="media", estado="abierto")
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(ticket)

    ti = cab(client)
    r = client.get(f"/api/tickets/{ticket.id}", headers=ti)
    assert r.status_code == 200
    assert r.json()["sitio"]["clave"] == "MTY"

    persona = cab(client, "user@test.com")  # de Querétaro
    # 404 y no 403: a quien no le corresponde, el ticket ni siquiera existe.
    assert client.get(f"/api/tickets/{ticket.id}", headers=persona).status_code == 404
    assert client.post(f"/api/tickets/{ticket.id}/comments", headers=persona,
                       json={"comentario": "hola"}).status_code == 404



def test_no_se_levanta_un_ticket_en_otra_planta(client, db_session, otra_planta):
    """`sitio_id` viene del cliente: tiene que existir y ser de quien levanta."""
    cuerpo = {"categoria": "otro", "descripcion_original": "Intento de crear en otra planta",
              "prioridad": "media"}
    persona = cab(client, "user@test.com")
    for sitio in (999, otra_planta.id):
        r = client.post("/api/tickets", headers=persona, json={**cuerpo, "sitio_id": sitio})
        assert r.status_code == 422, (sitio, r.status_code)


# ======================================================================
# Integridad de las métricas
# ======================================================================

def test_no_se_vota_una_sugerencia_ajena(client, db_session):
    """`veces_util / veces_sugerida` es lo que calibra el umbral de similitud.

    Se aceptaba cualquier `sugerencia_id`, así que con una sesión cualquiera se
    podían votar sugerencias de otros y degradar las de toda la planta.
    """
    entrada = BaseConocimiento(sitio_id=1, titulo="Una entrada",
                               contenido="Contenido suficientemente largo.",
                               categoria="equipo", veces_sugerida=1, veces_util=0)
    db_session.add(entrada)
    db_session.commit()
    db_session.refresh(entrada)

    duenio = db_session.query(Usuario).filter(Usuario.email == "admin@test.com").first()
    fila = SugerenciaKB(kb_id=entrada.id, usuario_id=duenio.id, similitud=0.9, fue_util=None)
    db_session.add(fila)
    db_session.commit()
    db_session.refresh(fila)

    # Otra persona intenta votarla.
    r = client.post("/api/kb/feedback", headers=cab(client, "user@test.com"),
                    json={"sugerencia_id": fila.id, "fue_util": True})
    assert r.status_code == 404

    db_session.refresh(entrada)
    assert entrada.veces_util == 0


# ======================================================================
# Sesiones
# ======================================================================

def test_cambiar_la_contrasena_invalida_las_sesiones_abiertas(client):
    """Antes el token seguía valiendo sus ocho horas pasara lo que pasara.

    Quien cambia su contraseña porque cree que se la vieron espera justamente
    lo contrario: que quien estuviera dentro se quede fuera.
    """
    viejo = cab(client, "user@test.com")
    assert client.get("/api/auth/me", headers=viejo).status_code == 200

    assert client.post("/api/auth/cambiar-password", headers=viejo, json={
        "password_actual": "Secret123!",
        "password_nueva": "OtraClaveLarga9",
    }).status_code == 200

    # El token de antes ya no sirve.
    assert client.get("/api/auth/me", headers=viejo).status_code == 401
    # El nuevo, sí.
    assert client.get("/api/auth/me",
                      headers=cab(client, "user@test.com", "OtraClaveLarga9")).status_code == 200


def test_un_token_con_version_vieja_no_entra(client, db_session):
    """La comprobación no depende de por dónde se cambió la contraseña."""
    persona = db_session.query(Usuario).filter(Usuario.email == "user@test.com").first()
    persona.version_token = 5
    db_session.commit()

    caducado = create_access_token(subject=persona.id, version_token=4)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {caducado}"})
    assert r.status_code == 401

    vigente = create_access_token(subject=persona.id, version_token=5)
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {vigente}"}).status_code == 200


# ======================================================================
# La pantalla de entrada no sirve para averiguar quién trabaja aquí
# ======================================================================

def test_el_login_responde_igual_exista_o_no_la_cuenta(client, db_session):
    """Distinguir 400/409/401 confirmaba la existencia y el estado de la cuenta.

    Con números de empleado consecutivos, eso es recorrer un rango y quedarse
    con el padrón completo.
    """
    pendiente = Usuario(sitio_id=1, nombre="Sin activar", numero_empleado="7777",
                        rol="usuario", activo=True, estado_cuenta="pendiente_activacion",
                        password_hash=None)
    baja = Usuario(sitio_id=1, nombre="Dada de baja", numero_empleado="8888",
                   rol="usuario", activo=False, estado_cuenta="activa",
                   password_hash=None)
    db_session.add_all([pendiente, baja])
    db_session.commit()

    codigos = set()
    cuerpos = set()
    for identificador in ("7777", "8888", "1002", "0000-no-existe"):
        r = client.post("/api/auth/login",
                        json={"email": identificador, "password": "LoQueSea123"})
        codigos.add(r.status_code)
        cuerpos.add(r.json().get("detail"))

    assert codigos == {401}, f"se distinguen los casos: {codigos}"
    assert len(cuerpos) == 1, f"el texto delata el caso: {cuerpos}"


# ======================================================================
# Robustez del limitador
# ======================================================================

def test_el_limitador_no_crece_sin_limite():
    """`purgar()` existía y nadie lo llamaba: bastaba con mandar un
    identificador distinto por petición para agotar la memoria del proceso."""
    limitador = Limitador(maximo=3, ventana_segundos=0)
    for i in range(Limitador.BARRIDO_CADA * 2):
        limitador.permitido(f"correo:inventado-{i}@ejemplo.com")

    # Con la ventana en cero, todo lo registrado vence de inmediato: tras el
    # barrido no debe quedar practicamente nada.
    assert len(limitador._intentos) < Limitador.BARRIDO_CADA


# ======================================================================
# El CSV que se reparte a los supervisores
# ======================================================================

@pytest.mark.parametrize("entrada", ["=cmd|'/c calc'!A1", "+1+1", "-2+3", "@SUM(A1)"])
def test_una_hoja_de_calculo_no_ejecuta_lo_que_venga_en_el_padron(entrada):
    """El nombre sale del archivo de RH y acaba en un CSV que se abre en Excel."""
    assert _neutro(entrada).startswith("'")


@pytest.mark.parametrize("entrada", ["Ana Pérez", "10001", "Línea 2", ""])
def test_un_dato_normal_no_se_toca(entrada):
    assert _neutro(entrada) == entrada

# ======================================================================
# Activación: el eslabón más débil, y por qué se acota así
# ======================================================================

def _pendiente(db_session, numero="4321", epp="0987", nacimiento=datetime(1985, 7, 14)):
    persona = Usuario(sitio_id=1, nombre="Operador Nuevo", numero_empleado=numero,
                      numero_epp=epp, fecha_nacimiento=nacimiento, rol="usuario",
                      activo=True, estado_cuenta="pendiente_activacion", password_hash=None)
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def test_desde_internet_no_basta_con_datos_personales(client, db_session):
    """Numero de EPP y fecha de nacimiento salen de la misma lista de RH.

    Contra un desconocido son ~27 bits; contra un compañero, cero. Dentro de la
    planta ese riesgo es acotado e identificable. Desde internet no, asi que por
    la via publica se exige el codigo de un solo uso.
    """
    _pendiente(db_session)

    r = client.post("/api/auth/activar",
                    headers={"X-Portal-Origen": "publico"},
                    json={"identificador": "4321", "password": "UnaClaveLarga1",
                          "nombre_completo": "Operador Nuevo",
                          "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"})
    assert r.status_code == 403

    # Los mismos datos, desde dentro, si activan.
    r = client.post("/api/auth/activar",
                    json={"identificador": "4321", "password": "UnaClaveLarga1",
                          "nombre_completo": "Operador Nuevo",
                          "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"})
    assert r.status_code == 200


def test_el_codigo_si_vale_desde_internet(client, db_session):
    """Lo que se cierra afuera es la via debil, no la activacion entera."""
    persona = _pendiente(db_session, numero="4322")
    codigo = CuentasService.regenerar_codigo(db_session, persona)

    r = client.post("/api/auth/activar",
                    headers={"X-Portal-Origen": "publico"},
                    json={"identificador": "4322", "password": "UnaClaveLarga1",
                          "codigo": codigo})
    assert r.status_code == 200


def test_a_los_cinco_fallos_la_cuenta_cierra_esa_via(client, db_session):
    """Es lo que convierte ~17 000 cumpleaños posibles en cinco tiros."""
    persona = _pendiente(db_session, numero="4323")

    for dia in range(1, 6):
        r = client.post("/api/auth/activar",
                        json={"identificador": "4323", "password": "UnaClaveLarga1",
                              "nombre_completo": "Operador Nuevo",
                              "numero_epp": "0987", "fecha_nacimiento": f"1985-07-0{dia}"})
        assert r.status_code == 400

    db_session.refresh(persona)
    assert persona.verificacion_bloqueada is True

    # Ni siquiera con los datos correctos: ya solo entra con codigo de TI.
    r = client.post("/api/auth/activar",
                    json={"identificador": "4323", "password": "UnaClaveLarga1",
                          "nombre_completo": "Operador Nuevo",
                          "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"})
    assert r.status_code == 400
    assert "código" in r.json()["detail"]


# ======================================================================
# La contraseña no puede ser el dato con el que se abrio la puerta
# ======================================================================

@pytest.mark.parametrize("password,motivo", [
    ("clave4321segura", "su número de empleado"),
    ("clave0987segura", "su número de EPP"),
    ("clave14071985x", "su fecha de nacimiento"),
    ("OperadorNuevo1", "su nombre"),
])
def test_la_contrasena_no_sale_de_los_datos_propios(db_session, password, motivo):
    """Quien acaba de activarse tecleando su EPP y su cumpleaños tiende a poner
    justo eso como contraseña. Serian los mismos datos de la lista de RH."""
    persona = _pendiente(db_session, numero="4321", epp="0987")
    problema = validar_password(password, persona)
    assert problema is not None, f"se aceptó {password!r}"
    assert motivo in problema


def test_una_contrasena_normal_se_acepta(db_session):
    persona = _pendiente(db_session, numero="4321", epp="0987")
    assert validar_password("Tortuga.Verde.2026", persona) is None


def test_el_nombre_solo_estorba_si_la_contrasena_se_apoya_en_el(db_session):
    """La regla es proporcional a proposito.

    Rechazar cualquier contraseña que lleve dentro cuatro letras del nombre es
    demasiado: media planta se apellida Cruz, Luna, Mora o Leon, que ademas son
    palabras corrientes. Lo que se corta es "Perez2026", no que el apellido
    aparezca de pasada dentro de algo mas largo.
    """
    persona = _pendiente(db_session, numero="4324")
    persona.nombre = "Juan Perez Luna"

    # Se apoya en el nombre: fuera.
    assert validar_password("JuanPerez12", persona) is not None
    assert validar_password("PerezLuna99", persona) is not None
    # Lo lleva dentro pero no se apoya en el: pasa.
    assert validar_password("Bicicleta.Luna.2026", persona) is None


# ======================================================================
# El asistente de activacion no es un directorio de personal
# ======================================================================

def test_el_primer_paso_responde_igual_exista_o_no_la_cuenta(client, db_session):
    """El paso 1 del asistente pregunta el numero de empleado.

    Si ahi se confirmara que la cuenta existe, recorrer del 1 al 600 devolveria
    quien trabaja en la planta y en que estado esta cada quien. Por eso responde
    lo mismo siempre y la validacion real ocurre al final.
    """
    _pendiente(db_session, numero="4400")

    respuestas = set()
    for identificador in ("4400", "1002", "999999"):
        r = client.post("/api/auth/estado-cuenta", json={"identificador": identificador})
        assert r.status_code == 200
        d = r.json()
        respuestas.add((d["accion"], tuple(d["datos_verificacion"]),
                        d["acepta_codigo"], d["acepta_verificacion"]))

    assert len(respuestas) == 1, f"los casos se distinguen: {respuestas}"


def test_el_nombre_se_compara_como_lo_teclea_la_gente(client, db_session):
    """Sin acentos, sin mayusculas y sin exigir los apellidos completos.

    Pedir la cadena exacta habria dejado fuera a media planta por una tilde.
    """
    persona = _pendiente(db_session, numero="4401")
    persona.nombre = "María López Herrera"
    db_session.commit()

    r = client.post("/api/auth/activar", json={
        "identificador": "4401", "password": "Ventana.Clara.88",
        "nombre_completo": "maria lopez",      # sin tilde, sin el segundo apellido
        "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"})
    assert r.status_code == 200


def test_una_sola_palabra_no_basta_como_nombre(client, db_session):
    """Con "Maria" a secas se acertaria en decenas de cuentas."""
    persona = _pendiente(db_session, numero="4402")
    persona.nombre = "María López Herrera"
    db_session.commit()

    r = client.post("/api/auth/activar", json={
        "identificador": "4402", "password": "Ventana.Clara.88",
        "nombre_completo": "maria",
        "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"})
    assert r.status_code == 400


def test_el_nombre_por_si_solo_no_activa_nada(client, db_session):
    """El agujero que abrio anadir el nombre como factor, y por que se cerro.

    El nombre lo tiene toda cuenta, asi que si contara para decidir "esta
    persona tiene con que verificarse", la respuesta seria siempre que si. Una
    cuenta sin EPP ni fecha registrados quedaba activable con numero de empleado
    y nombre —los dos van impresos en el gafete—, que no es verificar a nadie.
    """
    persona = Usuario(sitio_id=1, nombre="Sin Datos Registrados",
                      numero_empleado="4500", rol="usuario", activo=True,
                      estado_cuenta="pendiente_activacion", password_hash=None)
    db_session.add(persona)
    db_session.commit()

    r = client.post("/api/auth/activar", json={
        "identificador": "4500", "password": "UnaClaveLarga1",
        "nombre_completo": "Sin Datos Registrados"})
    assert r.status_code == 400

    db_session.refresh(persona)
    assert persona.estado_cuenta == "pendiente_activacion"


# ======================================================================
# La pantalla de activacion tiene que ser alcanzable
# ======================================================================

def test_los_requisitos_de_contrasena_no_piden_sesion(client):
    """La pantalla de activacion la abre gente que **todavia no tiene cuenta**.

    Cualquier llamada con sesion obligatoria en ese camino rebota al login por
    el interceptor de 401 del navegador, y la activacion queda inalcanzable
    escribiendo la direccion. Paso: `/estado/horario` se consultaba desde un
    proveedor que envuelve la aplicacion entera, rutas publicas incluidas.
    """
    r = client.get("/api/auth/requisitos-password")
    assert r.status_code == 200
    assert r.json()["longitud_minima"] >= 8


def test_se_ofrecen_frases_que_cumplen_la_politica(client):
    """De nada sirve sugerir una frase que el portal luego rechaza.

    Y de nada sirve pedirle a un operador de sesenta anios que invente
    "Xk9$mQ2p": acaba escrita en un papel pegado al monitor, y ahi ya no
    protege nada.
    """
    from app.services.cuentas_service import validar_password

    frases = client.get("/api/auth/requisitos-password").json()["sugerencias"]
    assert len(frases) == 3
    assert len(set(frases)) == 3, "se repiten entre si"
    for frase in frases:
        assert validar_password(frase) is None, f"el portal rechazaria {frase!r}"
