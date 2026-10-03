"""Cambio de contraseña hecho por la propia persona.

El endpoint existía desde el principio y no tenía ni una prueba. Es el único
camino por el que alguien puede cambiar su contraseña sin pasar por TI, y de
él depende una promesa concreta que la pantalla de activación hace con todas
sus letras: «Solo usted la va a conocer. Ni el área de TI puede verla».

Lo que se fija aquí: que haga falta la vigente, que la nueva pase por las
mismas reglas que en el alta, que no valga repetir la que ya se tenía, y
—sobre todo— que cambiarla eche fuera las sesiones abiertas con la anterior.
Esa última es la razón por la que uno cambia la contraseña cuando cree que se
la vieron; sin ella el token robado seguiría entrando ocho horas más.
"""

VIGENTE = "Secret123!"
NUEVA = "bicicleta.verde.otonio"


def token(client, identificador=VIGENTE and "user@test.com", password=VIGENTE):
    r = client.post("/api/auth/login", json={"email": identificador, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def cab(client, **kw):
    return {"Authorization": f"Bearer {token(client, **kw)}"}


def cambiar(client, cabeceras, actual, nueva):
    return client.post("/api/auth/cambiar-password",
                       json={"password_actual": actual, "password_nueva": nueva},
                       headers=cabeceras)


# ----------------------------------------------------------------------
# El camino feliz
# ----------------------------------------------------------------------

def test_se_cambia_y_la_nueva_sirve_para_entrar(client):
    assert cambiar(client, cab(client), VIGENTE, NUEVA).status_code == 200

    con_nueva = client.post("/api/auth/login", json={"email": "user@test.com", "password": NUEVA})
    con_vieja = client.post("/api/auth/login", json={"email": "user@test.com", "password": VIGENTE})

    assert con_nueva.status_code == 200
    assert con_vieja.status_code == 401


def test_cambiarla_cierra_las_sesiones_abiertas(client):
    """Lo que de verdad importa: el token de antes deja de valer en el acto.

    Es la razón por la que alguien cambia su contraseña cuando cree que se la
    vieron. Sin esto, quien tuviera el token seguía dentro hasta que expirara.
    """
    cabeceras = cab(client)
    assert client.get("/api/auth/me", headers=cabeceras).status_code == 200

    cambiar(client, cabeceras, VIGENTE, NUEVA)

    assert client.get("/api/auth/me", headers=cabeceras).status_code == 401


# ----------------------------------------------------------------------
# Lo que no se acepta
# ----------------------------------------------------------------------

def test_sin_la_vigente_no_se_cambia(client):
    """Un token robado no basta para quedarse con la cuenta."""
    r = cambiar(client, cab(client), "la-que-no-es", NUEVA)

    assert r.status_code == 400
    assert "actual" in r.json()["detail"].lower()


def test_la_nueva_pasa_por_las_mismas_reglas_que_en_el_alta(client):
    """Las mismas reglas que en el alta, no unas mas flojas por ser un cambio.

    La lista de contrasenas prohibidas compara la cadena entera, no por
    fragmentos: "password" se rechaza y "password123" no. Es deliberado —la
    lista esta curada para esta planta (cgrmexico, queretaro, temporal1) y no
    pretende ser un diccionario— y quien de verdad frena esos casos es el
    minimo de diez caracteres junto con la regla de no usar los datos propios.
    """
    for mala, motivo in [
        ("corta1", "por debajo del minimo"),
        ("1234567890123", "solo numeros"),
        ("--------------", "sin ninguna letra"),
        ("password", "esta en la lista de comunes"),
    ]:
        r = cambiar(client, cab(client), VIGENTE, mala)
        assert r.status_code == 400, f"{mala} ({motivo}) deberia rechazarse"


def test_no_vale_la_contrasena_hecha_con_los_datos_propios(client):
    """Quien acaba de activarse tecleando su nombre tiende a ponerlo de
    contrasena, y ese dato esta en la lista de RH: seria dejar la puerta con
    la misma llave con la que se abrio."""
    r = cambiar(client, cab(client), VIGENTE, "usertest1234")

    assert r.status_code == 400, r.text


def test_no_vale_repetir_la_que_ya_se_tenia(client):
    """Cambiarla por la misma no cierra sesiones ni arregla nada: es cambiarla
    sin cambiarla, y quien lo haga se queda creyendo que ya está a salvo."""
    r = cambiar(client, cab(client), VIGENTE, VIGENTE)

    assert r.status_code == 400
    assert "distinta" in r.json()["detail"].lower()


def test_no_se_cambia_sin_sesion(client):
    r = client.post("/api/auth/cambiar-password",
                    json={"password_actual": VIGENTE, "password_nueva": NUEVA})
    assert r.status_code == 401


def test_no_se_le_cambia_la_contrasena_a_otro(client):
    """El endpoint no recibe a quién: siempre actúa sobre quien pide. Se fija
    aquí para que nadie le añada un `usuario_id` sin pensarlo dos veces."""
    cambiar(client, cab(client), VIGENTE, NUEVA)

    # El admin conserva la suya intacta.
    assert client.post("/api/auth/login",
                       json={"email": "admin@test.com", "password": VIGENTE}).status_code == 200


def test_adivinar_la_contrasena_actual_tiene_el_mismo_freno_que_el_login(client, monkeypatch):
    """Con una sesión ajena abierta se podía probar contraseñas aquí sin límite."""
    from app.core import limitador as modulo
    monkeypatch.setattr(modulo.limitador_login, "maximo", 3)
    r = client.post("/api/auth/login", json={"email": "user@test.com", "password": "Secret123!"})
    cab = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for _ in range(3):
        r = client.post("/api/auth/cambiar-password", headers=cab,
                        json={"password_actual": "adivinanza1", "password_nueva": "OtraClaveLarga2026"})
        assert r.status_code == 400
    r = client.post("/api/auth/cambiar-password", headers=cab,
                    json={"password_actual": "Secret123!", "password_nueva": "OtraClaveLarga2026"})
    assert r.status_code == 429
