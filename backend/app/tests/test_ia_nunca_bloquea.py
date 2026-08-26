"""Un fallo de Ollama nunca puede bloquear el flujo de tickets.

Es la diferencia entre un sistema con IA y un sistema que depende de la IA.
Todo lo de aquí se ejecuta con Ollama inalcanzable a propósito.
"""

import pytest

from app.core.config import settings
from app.services.ollama_client import OllamaClient, ollama

SOLUCION_VALIDA = "Se reemplazó el cable de red del switch de piso y se validó el enlace a 1 Gbps."

# Puerto cerrado: la conexión se rechaza de inmediato, sin esperar timeouts.
HOST_MUERTO = "http://127.0.0.1:1"


@pytest.fixture
def ollama_caido(monkeypatch):
    """Deja a Ollama inalcanzable durante la prueba."""
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(ollama, "host", HOST_MUERTO)
    yield


def get_token(client, email="admin@test.com", password="Secret123!"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


# ----------------------------------------------------------------------
# El cliente degrada en lugar de levantar excepción
# ----------------------------------------------------------------------
def test_cliente_no_levanta_excepcion_con_host_muerto():
    cliente = OllamaClient(host=HOST_MUERTO)

    assert cliente.disponible() is False
    assert cliente.generar_embedding("la impresora no imprime") is None
    assert cliente.normalizar_descripcion("la impresora no imprime") is None


def test_cliente_respeta_el_interruptor_de_ia(monkeypatch):
    monkeypatch.setattr(settings, "IA_HABILITADA", False)
    cliente = OllamaClient(host=HOST_MUERTO)

    assert cliente.disponible() is False
    assert cliente.generar_embedding("texto") is None
    assert cliente.normalizar_descripcion("texto") is None


def test_cliente_ignora_texto_vacio():
    cliente = OllamaClient(host=HOST_MUERTO)

    assert cliente.generar_embedding("") is None
    assert cliente.generar_embedding("   ") is None
    assert cliente.normalizar_descripcion("") is None


# ----------------------------------------------------------------------
# El flujo de tickets sigue funcionando
# ----------------------------------------------------------------------
def test_el_ticket_se_crea_con_ollama_caido(client, ollama_caido):
    """Se crea con la descripción original y el usuario ni se entera."""
    headers = {"Authorization": f"Bearer {get_token(client)}"}
    descripcion = "no me deja imprimir ya le pique varias veces y nada"

    response = client.post(
        "/api/tickets",
        json={
            "sitio_id": 1,
            "categoria": "impresora",
            "descripcion_original": descripcion,
            "prioridad": "media",
        },
        headers=headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["descripcion_original"] == descripcion
    # La normalización es una mejora, no un requisito.
    assert data["descripcion_normalizada"] is None


def test_el_ticket_se_cierra_con_ollama_caido(client, ollama_caido):
    """El cierre es válido aunque no se pueda indexar."""
    headers = {"Authorization": f"Bearer {get_token(client)}"}

    ticket_id = client.post(
        "/api/tickets",
        json={
            "sitio_id": 1,
            "categoria": "red",
            "descripcion_original": "Sin red en el área de calidad",
            "prioridad": "alta",
        },
        headers=headers,
    ).json()["id"]

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"estado": "cerrado", "solucion": SOLUCION_VALIDA},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["estado"] == "cerrado"
    assert data["solucion"] == SOLUCION_VALIDA
    # Queda pendiente de indexar; lo recoge reindexar_kb.py.
    assert data["indexado_kb"] is False


def test_busqueda_similares_degrada_sin_error(client, ollama_caido):
    """200 con lista vacía, nunca un 500 ni un error de IA en pantalla."""
    headers = {"Authorization": f"Bearer {get_token(client)}"}

    response = client.post(
        "/api/ia/similares",
        json={"texto": "la impresora de embarques no responde", "sitio_id": 1},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["resultados"] == []
    assert data["degradado"] is True
    assert data["umbral_usado"] == settings.KB_UMBRAL_SIMILITUD
