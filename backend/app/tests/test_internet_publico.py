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
