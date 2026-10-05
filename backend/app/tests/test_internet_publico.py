"""El portal en internet abierto (auditoría del 2026-10-04).

Lo que cambia cuando cualquiera del mundo puede llegar a la puerta: los frenos
de intentos no pueden convertirse en un arma contra la planta, y una IPv6 no
puede valer por dieciocho trillones de intentos.

El camino público lo marca nginx con `X-Portal-Origen: publico` y la IP real
viaja en `X-Forwarded-For` (ver nginx/comun/). Aquí se mandan a mano.
"""

import pytest

from app.core.config import settings
from app.core.limitador import clave_de_red, limitador_login_ip

PUBLICO = {"X-Portal-Origen": "publico"}


def _entrar(client, email, password, **cabeceras):
    return client.post("/api/auth/login", json={"email": email, "password": password},
                       headers=cabeceras)


def test_fallar_desde_internet_no_deja_fuera_a_la_planta(client):
    """El freno por cuenta cerraba la cuenta para todos. Con los números de
    empleado consecutivos, cualquiera en internet dejaba sin entrar a la
    plantilla entera con ocho contraseñas malas por persona."""
    for _ in range(settings.LOGIN_MAX_INTENTOS):
        r = _entrar(client, "user@test.com", "no-es-la-buena", **PUBLICO)
        assert r.status_code == 401

    # Por internet esa cuenta queda frenada, aun con la contraseña buena...
    r = _entrar(client, "user@test.com", "Secret123!", **PUBLICO)
    assert r.status_code == 429

    # ...pero desde la planta se sigue entrando.
    assert _entrar(client, "user@test.com", "Secret123!").status_code == 200


def test_los_fallos_desde_la_planta_siguen_frenando_desde_la_planta(client):
    """Separar los contadores no regala intentos: cada camino tiene los suyos."""
    for _ in range(settings.LOGIN_MAX_INTENTOS):
        _entrar(client, "user@test.com", "no-es-la-buena")
    assert _entrar(client, "user@test.com", "Secret123!").status_code == 429


def test_una_red_ipv6_cuenta_como_un_solo_cliente(client, monkeypatch):
    """Cambiar de dirección dentro del mismo /64 en cada intento burlaba el
    freno por IP: cada dirección tenía su propio contador."""
    monkeypatch.setattr(limitador_login_ip, "maximo", 3)
    for n in (1, 2, 3):
        r = _entrar(client, f"nadie{n}@test.com", "x" * 12,
                    **PUBLICO, **{"X-Forwarded-For": f"2001:db8:1:2::{n}"})
        assert r.status_code == 401

    # Otra dirección de la misma red: ya no le quedan intentos.
    r = _entrar(client, "nadie4@test.com", "x" * 12,
                **PUBLICO, **{"X-Forwarded-For": "2001:db8:1:2:ffff::99"})
    assert r.status_code == 429

    # Una red distinta no paga por la otra.
    r = _entrar(client, "nadie5@test.com", "x" * 12,
                **PUBLICO, **{"X-Forwarded-For": "2001:db8:1:3::1"})
    assert r.status_code == 401


@pytest.mark.parametrize("ip,clave", [
    ("198.51.100.7", "198.51.100.7"),
    ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
    ("2001:DB8:1:2:abcd:ef01:2345:6789", "2001:db8:1:2::/64"),
    ("::ffff:198.51.100.7", "198.51.100.7"),
    ("no-es-ip", "no-es-ip"),
    (None, "desconocida"),
    ("", "desconocida"),
])
def test_la_clave_de_red(ip, clave):
    assert clave_de_red(ip) == clave


# ----------------------------------------------------------------------
# Los bcrypt en fila: una inundación de intentos no se lleva la CPU
# ----------------------------------------------------------------------

@pytest.fixture
def sin_turnos(monkeypatch):
    """Todos los turnos de bcrypt ocupados, como en mitad de un ataque."""
    import threading

    from app.core import security

    lleno = threading.BoundedSemaphore(1)
    lleno.acquire()
    monkeypatch.setattr(security, "_turnos_hash", lleno)
    monkeypatch.setattr(settings, "HASH_ESPERA_S", 0.05)
    yield lleno
    lleno.release()


def test_sin_turno_para_bcrypt_se_contesta_503_al_momento(client, sin_turnos):
    r = _entrar(client, "user@test.com", "Secret123!", **PUBLICO)
    assert r.status_code == 503
    assert r.headers.get("retry-after")
    r = client.post("/api/auth/activar", headers=PUBLICO,
                    json={"identificador": "30001", "codigo": "ABCD2345", "password": "x" * 12})
    assert r.status_code == 503


def test_lo_que_no_se_llego_a_intentar_no_gasta_el_cupo(client, sin_turnos):
    """Rechazado por saturación no es un intento fallido: ni la cuenta ni la IP
    lo pagan. Si no, una inundación dejaría frenadas a las cuentas que toca."""
    for _ in range(settings.LOGIN_MAX_INTENTOS * 2):
        assert _entrar(client, "user@test.com", "no-es-la-buena", **PUBLICO).status_code == 503
    sin_turnos.release()
    try:
        assert _entrar(client, "user@test.com", "Secret123!", **PUBLICO).status_code == 200
    finally:
        sin_turnos.acquire()


def test_la_fila_de_espera_tiene_tope(monkeypatch):
    """Con la fila llena no se espera: se rechaza al instante y no ocupa un hilo."""
    import time

    from app.core import security

    monkeypatch.setattr(settings, "HASH_COLA_MAXIMA", 0)
    monkeypatch.setattr(settings, "HASH_ESPERA_S", 5)
    inicio = time.monotonic()
    with pytest.raises(security.HashOcupado):
        with security.turno_de_hash():
            pass
    assert time.monotonic() - inicio < 0.5


def test_veinte_intentos_a_la_vez_no_pasan_de_cuatro_bcrypt(client, monkeypatch):
    """La prueba de verdad: peticiones simultáneas, cada bcrypt medido.

    Veinte intentos a la vez contra veinte cuentas distintas —lo que no ve
    ningún freno por cuenta— no corren nunca más de `HASH_EN_PARALELO` bcrypt
    a la vez; los que no caben en la fila se rechazan al instante con 503.
    """
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app.api import auth

    monkeypatch.setattr(settings, "HASH_EN_PARALELO", 4)
    monkeypatch.setattr(settings, "HASH_COLA_MAXIMA", 12)
    monkeypatch.setattr(settings, "HASH_ESPERA_S", 5)
    from app.core import security
    monkeypatch.setattr(security, "_turnos_hash", threading.BoundedSemaphore(4))

    corriendo, pico = 0, 0
    candado = threading.Lock()
    original = auth.verify_password

    def bcrypt_medido(*args):
        nonlocal corriendo, pico
        with candado:
            corriendo += 1
            pico = max(pico, corriendo)
        try:
            time.sleep(0.2)
            return original(*args)
        finally:
            with candado:
                corriendo -= 1

    monkeypatch.setattr(auth, "verify_password", bcrypt_medido)
    with ThreadPoolExecutor(max_workers=20) as hilos:
        codigos = list(hilos.map(
            lambda n: _entrar(client, f"nadie{n}@test.com", "x" * 12, **PUBLICO,
                              **{"X-Forwarded-For": f"198.51.100.{n}"}).status_code,
            range(20)))

    assert pico <= 4
    assert set(codigos) <= {401, 503}
    assert codigos.count(401) >= 4   # los que cupieron se atendieron


# ----------------------------------------------------------------------
# Contraseñas: lo primero que prueba un ataque repartido entre cuentas
# ----------------------------------------------------------------------

@pytest.mark.parametrize("password", [
    "password123", "Qwerty12345", "iloveyou12",          # de la lista, tal cual
    "Password2026!", "Summer2026", "Mexico2026!",         # palabra común + números
    "Produccion2026", "Queretaro.2026",                   # palabras de la casa
])
def test_se_rechazan_las_contrasenas_que_prueba_un_ataque(password):
    """El freno por cuenta da ocho intentos cada cinco minutos: de sobra para
    probar las diez contraseñas más comunes contra cada cuenta del padrón. Lo
    que lo impide es que esas contraseñas no se puedan elegir."""
    from app.services.cuentas_service import validar_password

    assert validar_password(password) is not None


@pytest.mark.parametrize("password", [
    "Ventana.Clara.88", "MiClaveSegura1", "tornillo azul de marzo", "Correcaminos-Lunes-31",
])
def test_una_contrasena_propia_sigue_valiendo(password):
    from app.services.cuentas_service import validar_password

    assert validar_password(password) is None


def test_las_frases_que_sugiere_el_portal_no_se_rechazan():
    """Se las damos a la gente para que las memorice: rechazarlas después
    sería decirle que no a lo que el propio portal le recomendó."""
    from app.services.cuentas_service import contrasenas_comunes, validar_password
    from app.services.frases_service import sugerencias

    assert len(contrasenas_comunes()) > 50_000
    for frase in sugerencias(300):
        assert validar_password(frase) is None, frase


def test_cambiar_a_una_contrasena_comun_se_rechaza(client):
    token = _entrar(client, "user@test.com", "Secret123!").json()["access_token"]
    r = client.post("/api/auth/cambiar-password", headers={"Authorization": f"Bearer {token}"},
                    json={"password_actual": "Secret123!", "password_nueva": "Password2026!"})
    assert r.status_code == 400
    assert "se adivina" in r.json()["detail"]


# ----------------------------------------------------------------------
# La IP de la planta, por internet, es la planta (2026-10-05)
# ----------------------------------------------------------------------

PLANTA = "189.254.199.194"


@pytest.fixture
def con_planta(monkeypatch):
    """La planta sale a internet por su enlace, con una sola IP pública."""
    monkeypatch.setattr(settings, "REDES_DE_PLANTA", PLANTA)


def _desde(ip):
    return {**PUBLICO, "X-Forwarded-For": ip}


def test_desde_la_planta_por_internet_se_activa_con_datos_personales(client, db_session, con_planta):
    """La activación con EPP y fecha de nacimiento se cerró para internet; la
    planta, que ahora entra por internet, tiene que poder usarla."""
    from app.tests.test_seguridad import _pendiente

    _pendiente(db_session, numero="4401")
    _pendiente(db_session, numero="4402")
    datos = {"password": "UnaClaveLarga1", "nombre_completo": "Operador Nuevo",
             "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"}

    r = client.post("/api/auth/activar", headers=_desde(PLANTA),
                    json={"identificador": "4401", **datos})
    assert r.status_code == 200

    # Desde cualquier otra IP de internet sigue cerrada.
    r = client.post("/api/auth/activar", headers=_desde("203.0.113.9"),
                    json={"identificador": "4402", **datos})
    assert r.status_code == 403


def test_los_fallos_de_la_planta_no_cierran_la_entrada_a_toda_la_planta(client, con_planta,
                                                                      monkeypatch):
    """Setenta personas detrás de una IP: con freno por IP, unos cuantos
    errores de teclear —o un compañero— dejaban a todas sin entrar."""
    monkeypatch.setattr(limitador_login_ip, "maximo", 3)
    for n in range(6):
        r = _entrar(client, f"nadie{n}@test.com", "x" * 12, **_desde(PLANTA))
        assert r.status_code == 401
    assert _entrar(client, "user@test.com", "Secret123!", **_desde(PLANTA)).status_code == 200

    # Cualquier otra IP sí tiene su freno.
    for n in range(3):
        _entrar(client, f"otro{n}@test.com", "x" * 12, **_desde("203.0.113.9"))
    assert _entrar(client, "otro9@test.com", "x" * 12, **_desde("203.0.113.9")).status_code == 429


def test_quien_se_equivoca_en_la_planta_solo_se_bloquea_a_si_mismo(client, con_planta):
    """El freno por cuenta sigue en pie: protege a cada persona sin castigar
    a las demás."""
    for _ in range(settings.LOGIN_MAX_INTENTOS):
        _entrar(client, "user@test.com", "no-es-la-buena", **_desde(PLANTA))
    assert _entrar(client, "user@test.com", "Secret123!", **_desde(PLANTA)).status_code == 429
    assert _entrar(client, "admin@test.com", "Secret123!", **_desde(PLANTA)).status_code == 200


def test_sin_redes_de_planta_todo_lo_de_internet_es_publico(client, db_session, monkeypatch):
    """Vacío —el valor por defecto—, nada cambia: es lo que vale si falta en el .env."""
    from app.tests.test_seguridad import _pendiente

    # Se fija aquí y no se da por supuesto: la suite corre con el .env de la
    # máquina, y desde el 2026-10-05 el de producción trae la red de la planta.
    monkeypatch.setattr(settings, "REDES_DE_PLANTA", "")

    _pendiente(db_session, numero="4403")
    r = client.post("/api/auth/activar", headers=_desde(PLANTA),
                    json={"identificador": "4403", "password": "UnaClaveLarga1",
                          "numero_epp": "0987", "fecha_nacimiento": "1985-07-14"})
    assert r.status_code == 403


@pytest.mark.parametrize("ip,es", [
    ("189.254.199.194", True),
    ("::ffff:189.254.199.194", True),
    ("10.4.5.6", True),
    ("2001:db8:aa:1::5", True),
    ("189.254.199.195", False),
    ("2001:db8:ab::1", False),
    ("no-es-ip", False),
    (None, False),
])
def test_es_red_de_planta(monkeypatch, ip, es):
    from app.core.limitador import es_red_de_planta

    # Varias redes, con espacios y una entrada inválida que se ignora.
    monkeypatch.setattr(settings, "REDES_DE_PLANTA",
                        "189.254.199.194, 10.0.0.0/8, no-es-red, 2001:db8:aa::/48")
    assert es_red_de_planta(ip) is es
