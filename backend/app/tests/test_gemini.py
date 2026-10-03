"""Gemini: que ayude cuando está, y que no estorbe cuando no.

Gemini es un servicio ajeno, de pago y fuera de la planta. Las tres cosas
significan lo mismo: **va a fallar algún día**. Lo que se prueba aquí es que ese
día el portal siga funcionando igual, solo sin redactar respuestas.

Ninguna función de `gemini_client` puede levantar una excepción. Devuelve `None`
y quien llama sigue su camino.
"""

import httpx
import pytest

from app.core.config import settings
from app.services.gemini_client import GeminiClient


EXTRACTOS = ["Problema: la impresora no imprime. Solución: se reinició la cola."]


@pytest.fixture
def cliente():
    return GeminiClient(api_key="llave-de-prueba")


def responder(monkeypatch, cuerpo=None, status=200, excepcion=None):
    """Sustituye la llamada HTTP real por una respuesta controlada."""
    def falso_post(self, url, **kwargs):
        if excepcion:
            raise excepcion
        return httpx.Response(status, json=cuerpo or {}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", falso_post)


RESPUESTA_BUENA = {
    "candidates": [{"content": {"parts": [{"text": "Reinicie la cola de impresión."}]}}],
    "usageMetadata": {"promptTokenCount": 320, "candidatesTokenCount": 40},
}


# ----------------------------------------------------------------------
# Cuando funciona
# ----------------------------------------------------------------------
def test_responde_apoyandose_en_los_extractos(cliente, monkeypatch):
    responder(monkeypatch, RESPUESTA_BUENA)

    salida = cliente.responder_con_contexto("no imprime", EXTRACTOS)

    assert "cola de impresión" in salida["respuesta"]
    assert salida["tokens_entrada"] == 320


def test_informa_el_consumo_para_poder_vigilar_el_gasto(cliente, monkeypatch):
    """Sin esto, el costo solo se descubre en la factura."""
    responder(monkeypatch, RESPUESTA_BUENA)

    salida = cliente.responder_con_contexto("no imprime", EXTRACTOS)

    assert salida["tokens_entrada"] > 0
    assert salida["tokens_salida"] > 0
    assert salida["modelo"] == settings.GEMINI_MODELO


def test_no_manda_mas_extractos_de_los_configurados(cliente, monkeypatch):
    """Cada extracto cuesta tokens de entrada: el tope acota la factura."""
    enviados = {}

    def espia(self, url, **kwargs):
        enviados["texto"] = kwargs["json"]["contents"][0]["parts"][0]["text"]
        return httpx.Response(200, json=RESPUESTA_BUENA, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", espia)
    # Marca que no aparece en el prompt base, para contar solo lo que se mandó.
    cliente.responder_con_contexto("x", [f"TICKET-{i}" for i in range(20)])

    assert enviados["texto"].count("TICKET-") == settings.GEMINI_MAX_EXTRACTOS


# ----------------------------------------------------------------------
# Cuando no funciona: nada de esto puede tronar
# ----------------------------------------------------------------------
def test_sin_llave_no_se_intenta_siquiera():
    """El caso normal hasta que alguien saque la llave: el portal va igual."""
    sin_llave = GeminiClient(api_key="")

    assert sin_llave.configurado is False
    assert sin_llave.responder_con_contexto("hola", EXTRACTOS) is None
    assert sin_llave.disponible() is False


def test_si_google_no_contesta_se_devuelve_none(cliente, monkeypatch):
    responder(monkeypatch, excepcion=httpx.ConnectError("sin red"))

    assert cliente.responder_con_contexto("hola", EXTRACTOS) is None


def test_un_timeout_no_levanta_excepcion(cliente, monkeypatch):
    responder(monkeypatch, excepcion=httpx.TimeoutException("tardó"))

    assert cliente.responder_con_contexto("hola", EXTRACTOS) is None


def test_un_error_del_servidor_no_levanta_excepcion(cliente, monkeypatch):
    responder(monkeypatch, {"error": "algo"}, status=500)

    assert cliente.responder_con_contexto("hola", EXTRACTOS) is None


def test_una_respuesta_con_forma_rara_no_truena(cliente, monkeypatch):
    """Si Google cambia el formato, se degrada; no se cae."""
    responder(monkeypatch, {"candidates": []})

    assert cliente.responder_con_contexto("hola", EXTRACTOS) is None


def test_una_respuesta_vacia_cuenta_como_no_respuesta(cliente, monkeypatch):
    responder(monkeypatch, {"candidates": [{"content": {"parts": [{"text": "   "}]}}]})

    assert cliente.responder_con_contexto("hola", EXTRACTOS) is None


# ----------------------------------------------------------------------
# Cuota
# ----------------------------------------------------------------------
def test_al_agotarse_la_cuota_deja_de_insistir(cliente, monkeypatch):
    """Insistir gasta el timeout completo en cada petición, para nada."""
    intentos = {"n": 0}

    def contar(self, url, **kwargs):
        intentos["n"] += 1
        return httpx.Response(429, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", contar)

    assert cliente.responder_con_contexto("hola", EXTRACTOS) is None
    assert cliente.responder_con_contexto("otra", EXTRACTOS) is None
    assert intentos["n"] == 1        # la segunda ni se intentó


def test_la_espera_por_cuota_se_ve_en_el_diagnostico(cliente, monkeypatch):
    responder(monkeypatch, {}, status=429)
    cliente.responder_con_contexto("hola", EXTRACTOS)

    assert cliente.diagnostico()["en_espera"] is True


# ----------------------------------------------------------------------
# La llave
# ----------------------------------------------------------------------
def test_el_diagnostico_no_enseña_la_llave(cliente):
    """TI necesita saber cuál llave está puesta, no cuál es."""
    diag = cliente.diagnostico()

    assert "llave-de-prueba" not in str(diag)
    assert diag["llave"] == "…ueba"


def test_el_interruptor_apaga_sin_borrar_la_llave(cliente, monkeypatch):
    """Para frenar el gasto sin perder la configuración."""
    monkeypatch.setattr(settings, "GEMINI_HABILITADO", False)

    assert cliente.configurado is False
    assert cliente.responder_con_contexto("hola", EXTRACTOS) is None


def test_una_respuesta_cortada_por_el_tope_no_se_devuelve(cliente, monkeypatch):
    """`MAX_TOKENS` llega con un 200 y con medio texto dentro.

    Es el mismo fallo que tenía el modelo local: al agotarse el presupuesto de
    tokens, el proveedor se detiene donde iba —no donde terminaba— y devuelve
    el trozo como si fuera la respuesta. Medio procedimiento con aspecto de
    estar entero es peor que ninguno, porque le falta el final, que es donde
    suelen ir las advertencias.

    Aquí pesa más que en el local: a Gemini se le llama *porque* el local no
    alcanzó, así que lo que conteste es lo que se publica.
    """
    responder(monkeypatch, {
        "candidates": [{
            "content": {"parts": [{"text": "1. Apague la impresora.\n2. Limpie la"}]},
            "finishReason": "MAX_TOKENS",
        }],
        "usageMetadata": {"promptTokenCount": 320, "candidatesTokenCount": 400},
    })
    assert cliente.redactar("redacte el procedimiento") is None


def test_una_respuesta_terminada_si_se_devuelve(cliente, monkeypatch):
    """El contrapeso: con `STOP` la respuesta pasa igual que antes."""
    responder(monkeypatch, {
        "candidates": [{
            "content": {"parts": [{"text": "Reinicie la cola de impresión."}]},
            "finishReason": "STOP",
        }],
        "usageMetadata": {"promptTokenCount": 320, "candidatesTokenCount": 40},
    })
    resultado = cliente.redactar("redacte el procedimiento")
    assert resultado is not None
    assert resultado["respuesta"] == "Reinicie la cola de impresión."
