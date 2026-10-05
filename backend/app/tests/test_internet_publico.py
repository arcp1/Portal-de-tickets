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
