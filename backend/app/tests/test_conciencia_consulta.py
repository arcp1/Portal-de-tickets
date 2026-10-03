"""La consulta que alimenta el grafo: misma respuesta, contando por donde va.

`/conciencia/consultar` tiene que ser intercambiable con
`/asistente/preguntar` —mismo contenido, misma forma— y ademas emitir la traza.
Lo que se prueba aqui es justo eso, en este orden de importancia:

  1. **La respuesta no cambia.** Si el grafo alterara lo que se contesta,
     habriamos cambiado el comportamiento del portal por una animacion.
  2. **La traza cuenta la verdad.** Un grafo que enciende nodos que no
     trabajaron es peor que no tener grafo: se usa para diagnosticar.
  3. **La traza nunca rompe la consulta.** Si el canal falla, la respuesta
     sale igual.

La traza se recoge con un doble en vez de con un WebSocket de verdad. No es por
comodidad: `test_eventos.py` ya dejo escrito que mantener abierta una conexion
de streaming dentro de `TestClient` es una forma conocida de colgar la suite. El
apreton de manos y la autenticacion del WebSocket se comprueban contra el portal
corriendo; lo que se mira aqui es que los pasos emitidos sean los correctos.
"""

import pytest

from app.core.config import settings
from app.services import traza_service
from app.services.recuperacion_service import Pasaje


class DifusorFalso:
    """Se queda con los pasos en una lista, sin bucle ni colas de por medio."""

    def __init__(self):
        self.pasos = []

    def publicar(self, usuario_id, evento):
        self.pasos.append((usuario_id, evento))

    def hay_alguien(self, usuario_id):
        return True

    def nodos(self):
        return [e["nodo"] for _, e in self.pasos]

    def de(self, nodo):
        return [e for _, e in self.pasos if e["nodo"] == nodo]


@pytest.fixture
def traza(monkeypatch):
    falso = DifusorFalso()
    monkeypatch.setattr(traza_service, "difusor_traza", falso)
    return falso


def token(client, email="user@test.com"):
    respuesta = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def _pasaje(similitud=0.72):
    return Pasaje(
        fuente="ticket",
        referencia_id=1,
        titulo="Linea oscura al imprimir",
        texto="Se limpio el rodillo de transferencia y la linea desaparecio.",
        similitud=similitud,
        categoria="impresora",
    )


def test_sin_embeddings_se_dice_que_no_hay_nada_y_no_se_llama_a_ningun_modelo(
    client, traza, monkeypatch
):
    """Ollama caido: se contesta "no hay nada escrito" y el grafo lo ensena.

    Es la degradacion de siempre. Lo que anade el grafo es poder distinguirla
    de la otra: aqui el nodo de vectorizacion queda en `error` —Ollama no
    contesto— y no en `omitido`, que seria "no habia nada parecido". Desde el
    texto de la respuesta las dos se ven igual; desde el grafo, no.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: None
    )

    respuesta = client.post(
        "/api/conciencia/consultar",
        json={"texto": "me sale una raya negra al imprimir"},
        headers=token(client),
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["origen"] == "sin_fundamento"
    assert cuerpo["respuesta"] is None
    assert cuerpo["siguiente_paso"] == "levantar_ticket"
    assert cuerpo["traza"], "la respuesta no trae el identificador de la traza"

    assert traza.de("embedding")[-1]["estado"] == "error"
    assert traza.de("conocimiento")[-1]["estado"] == "omitido"
    assert traza.de("ia_local")[-1]["detalle"]["motivo"] == "sin_fundamento"


def test_la_traza_recorre_el_camino_completo_y_cuadra_con_la_respuesta(
    client, traza, monkeypatch
):
    """Camino normal: usuario, vectorizacion, conocimiento, modelo, respuesta.

    Y el nodo del modelo tiene que coincidir con quien redacto de verdad: si la
    respuesta dice `ollama`, el grafo no puede ensenar ese nodo apagado.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768
    )
    monkeypatch.setattr(
        "app.services.recuperacion_service.RecuperacionService.buscar",
        lambda *a, **k: [_pasaje(0.72)],
    )
    monkeypatch.setattr(
        "app.services.asistente_service.AsistenteService.responder",
        lambda *a, **k: {
            "respuesta": "Limpie el rodillo de transferencia.",
            "origen": "ollama",
            "fundamentada": True,
            "fuentes": [_pasaje().a_dict()],
            "consumo": None,
            "siguiente_paso": "listo",
        },
    )

    respuesta = client.post(
        "/api/conciencia/consultar",
        json={"texto": "me sale una raya negra al imprimir", "categoria": "impresora"},
        headers=token(client),
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["origen"] == "ollama"
    assert cuerpo["respuesta"] == "Limpie el rodillo de transferencia."

    # El camino, en orden y sin saltarse ninguno.
    assert traza.nodos()[0] == "usuario"
    for nodo in ("embedding", "conocimiento", "ia_local", "respuesta"):
        assert nodo in traza.nodos(), f"el grafo nunca encendio {nodo}"

    assert traza.de("embedding")[-1]["estado"] == "listo"
    assert traza.de("embedding")[-1]["detalle"]["dimensiones"] == 768

    conocimiento = traza.de("conocimiento")[-1]
    assert conocimiento["estado"] == "listo"
    assert conocimiento["detalle"]["pasajes"] == 1
    assert conocimiento["detalle"]["similitud"] == 0.72

    # Redacto el local: su nodo queda encendido, no omitido.
    assert traza.de("ia_local")[-1]["estado"] == "listo"
    assert traza.de("respuesta")[-1]["detalle"]["origen"] == "ollama"

    # Todos los pasos son de la misma consulta y de su dueno.
    assert len({e["traza"] for _, e in traza.pasos}) == 1
    assert len({u for u, _ in traza.pasos}) == 1


def test_una_coincidencia_directa_deja_el_nodo_del_modelo_apagado(
    client, traza, monkeypatch
):
    """Nivel 0 de la escalera: la respuesta ya estaba escrita.

    Ningun modelo redacta, asi que su nodo se queda `omitido` — que en el grafo
    se pinta en gris punteado, no en rojo. Es la diferencia entre "no hizo
    falta" y "fallo", y confundirlas en la pantalla haria que TI fuera a
    revisar un Ollama que esta perfectamente.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768
    )
    monkeypatch.setattr(
        "app.services.recuperacion_service.RecuperacionService.buscar",
        lambda *a, **k: [_pasaje(0.91)],
    )
    monkeypatch.setattr(
        "app.services.asistente_service.AsistenteService.responder",
        lambda *a, **k: {
            "respuesta": "Se limpio el rodillo de transferencia.",
            "origen": "directo",
            "fundamentada": True,
            "fuentes": [_pasaje(0.91).a_dict()],
            "consumo": None,
            "siguiente_paso": "listo",
        },
    )

    respuesta = client.post(
        "/api/conciencia/consultar",
        json={"texto": "raya negra vertical en las hojas"},
        headers=token(client),
    )

    assert respuesta.json()["origen"] == "directo"
    modelo = traza.de("ia_local")[-1]
    assert modelo["estado"] == "omitido"
    assert modelo["detalle"]["motivo"] == "coincidencia_directa"


def test_si_redacta_gemini_el_grafo_lo_ensena(client, traza, monkeypatch):
    """Subir al peldano de pago se ve, porque cuesta dinero.

    El nodo de Gemini cuelga aparte en el grafo justamente para que se note
    cuando entra: son las pocas consultas al mes que justifican el gasto, y
    verlas es como se sabe si son pocas de verdad.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768
    )
    monkeypatch.setattr(
        "app.services.recuperacion_service.RecuperacionService.buscar",
        lambda *a, **k: [_pasaje(0.66)],
    )
    monkeypatch.setattr(
        "app.services.asistente_service.AsistenteService.responder",
        lambda *a, **k: {
            "respuesta": "Revise el rodillo.",
            "origen": "gemini",
            "fundamentada": True,
            "fuentes": [_pasaje(0.66).a_dict()],
            "consumo": {"tokens": 120},
            "siguiente_paso": "listo",
        },
    )

    client.post(
        "/api/conciencia/consultar",
        json={"texto": "la impresora marca un error raro"},
        headers=token(client),
    )

    assert traza.de("ia_local")[-1]["estado"] == "omitido"
    assert traza.de("gemini")[-1]["estado"] == "listo"
    # La linea final sale de Gemini, no del modelo local: el grafo tiene que
    # dibujar el desvio, no un atajo que no ocurrio.
    assert traza.de("respuesta")[-1]["desde"] == "gemini"


def test_sin_sesion_no_se_consulta(client):
    """La ruta pide token como todas las demas."""
    respuesta = client.post(
        "/api/conciencia/consultar", json={"texto": "no deberia contestar"}
    )
    assert respuesta.status_code == 401


def test_un_fallo_de_la_traza_no_tumba_la_consulta(client, monkeypatch):
    """Si el canal del grafo revienta, la respuesta sale igual.

    Es la garantia que permite que esto exista: la traza es decorativa, y una
    decoracion no puede impedir que alguien reciba la ayuda que pidio ni que
    levante un ticket.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: None
    )

    class DifusorRoto:
        def publicar(self, *a, **k):
            raise RuntimeError("el canal de la traza se cayo")

        def hay_alguien(self, *a, **k):
            return True

    monkeypatch.setattr(traza_service, "difusor_traza", DifusorRoto())

    respuesta = client.post(
        "/api/conciencia/consultar",
        json={"texto": "me sale una raya negra al imprimir"},
        headers=token(client),
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["origen"] == "sin_fundamento"

