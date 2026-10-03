"""El aforo de la CPU: que deje pasar a unos, espere a otros y rechace al resto.

Esto es lo que decide como se porta la maquina cuando entran cinco peticiones a
la vez, asi que conviene que este demostrado y no supuesto. Las pruebas de aqui
son deterministas —no miden tiempos reales de Ollama, que variarian— y lo que
comprueban es el contrato:

  1. No entran mas de `aforo` a la vez. Nunca.
  2. **Nunca se espera para despues fallar.** A quien no le alcanza el
     presupuesto se le dice que no en cero segundos, no tras hacerle cola.
  3. A quien si entra a la cola se le sirve: admitido es admitido.
  4. Un rechazo es `None` para quien llamo, no una excepcion: es la degradacion
     que ya tenia escrita `ollama_client` desde el primer dia.

El punto 4 es el que permite que este modulo exista sin riesgo —un rechazo no
revienta el ticket de nadie—. El punto 2 es el que lo hace util: costo dos
calibraciones fallidas contra el Ollama real descubrir que un plazo fijo no
puede cumplirlo, porque no sabe cuanto tarda una generacion y una generacion no
tarda siempre lo mismo. Ver la cabecera de `app/services/cola_ia.py`.
"""

import threading
import time

import pytest

from app.core.config import settings
from app.services.cola_ia import Compuerta
from app.services.ollama_client import ollama


def _abrir_en_hilo(compuerta, resultados, indice, soltar, espera=None):
    """Pide turno en un hilo y lo retiene hasta que `soltar` se active."""
    def tarea():
        with compuerta.turno(espera_maxima=espera) as hay_turno:
            resultados[indice] = hay_turno
            if hay_turno:
                soltar.wait(timeout=5)
    hilo = threading.Thread(target=tarea, daemon=True)
    hilo.start()
    return hilo


def test_no_entran_mas_de_los_que_caben():
    """Con aforo 1, el segundo espera. No hay dos generaciones simultaneas."""
    compuerta = Compuerta("prueba", aforo=1, sala=2, espera_maxima=5,
                          duracion_inicial=0.01)
    soltar = threading.Event()
    resultados = {}

    primero = _abrir_en_hilo(compuerta, resultados, 0, soltar)
    # Se espera a que el primero este dentro antes de medir.
    for _ in range(100):
        if compuerta.metricas()["en_curso"] == 1:
            break
        time.sleep(0.01)

    segundo = _abrir_en_hilo(compuerta, resultados, 1, soltar)
    for _ in range(100):
        if compuerta.metricas()["esperando"] == 1:
            break
        time.sleep(0.01)

    estado = compuerta.metricas()
    assert estado["en_curso"] == 1, "entro mas de uno con aforo 1"
    assert estado["esperando"] == 1, "el segundo deberia estar esperando turno"

    soltar.set()
    primero.join(timeout=5)
    segundo.join(timeout=5)

    # El segundo entro al liberarse la plaza: esperar no es ser rechazado.
    assert resultados == {0: True, 1: True}
    assert compuerta.metricas()["en_curso"] == 0


def test_con_la_sala_llena_se_dice_que_no_en_el_acto():
    """El que llega de mas no hace cola: se le contesta ya.

    Es la propiedad que evita que cinco personas se queden mirando una ruedita.
    Se comprueba con el reloj: si el rechazo tardara, seria porque hizo cola —y
    hacer cola con la sala llena es justo lo que no debe pasar—.
    """
    compuerta = Compuerta("prueba", aforo=1, sala=1, espera_maxima=30,
                          duracion_inicial=0.01)
    soltar = threading.Event()
    resultados = {}

    dentro = _abrir_en_hilo(compuerta, resultados, 0, soltar)
    for _ in range(100):
        if compuerta.metricas()["en_curso"] == 1:
            break
        time.sleep(0.01)

    esperando = _abrir_en_hilo(compuerta, resultados, 1, soltar)
    for _ in range(100):
        if compuerta.metricas()["esperando"] == 1:
            break
        time.sleep(0.01)

    # Sala con capacidad 1 y ya hay uno esperando: este sobra.
    inicio = time.monotonic()
    with compuerta.turno() as hay_turno:
        tardanza = time.monotonic() - inicio
        assert hay_turno is False, "se admitio con la sala llena"

    assert tardanza < 0.5, (
        f"el rechazo tardo {tardanza:.2f}s: hizo cola en vez de contestar ya"
    )
    assert compuerta.metricas()["rechazados_sala"] == 1

    soltar.set()
    dentro.join(timeout=5)
    esperando.join(timeout=5)


def test_a_quien_no_le_alcanza_el_presupuesto_se_le_dice_que_no_sin_esperar():
    """**La propiedad central: nunca esperar para despues fallar.**

    Aqui la sala tiene sitio de sobra —caben cuatro— pero el trabajo dura mas
    que el presupuesto de espera. La respuesta correcta no es "espera 0.2 s y
    luego te digo que no": es decirlo ya.

    Esto es lo que un plazo fijo no podia dar, y por eso se cambio el
    mecanismo. Medido contra el Ollama real, con el plazo fijo en 8 s, tres de
    cada cinco personas esperaban los 8 s completos **para acabar sin nada**,
    porque la generacion que tenian delante tardaba 14. La cola les cobraba el
    tiempo y no les entregaba la ayuda.
    """
    # Un trabajo que dura 10 s supuestos contra un presupuesto de 0.2 s: no cabe.
    compuerta = Compuerta("prueba", aforo=1, sala=4, espera_maxima=0.2,
                          duracion_inicial=10)
    soltar = threading.Event()
    resultados = {}

    dentro = _abrir_en_hilo(compuerta, resultados, 0, soltar)
    for _ in range(100):
        if compuerta.metricas()["en_curso"] == 1:
            break
        time.sleep(0.01)

    inicio = time.monotonic()
    with compuerta.turno() as hay_turno:
        assert hay_turno is False, "se admitio a alguien que no cabia en el presupuesto"
    tardanza = time.monotonic() - inicio

    assert tardanza < 0.1, (
        f"tardo {tardanza:.2f}s en decir que no: hizo esperar y despues fallo, "
        "que es justo lo que este diseño existe para evitar"
    )
    # Se rechazo en la puerta, no tras agotar la espera. La distincion importa:
    # `rechazados_espera` deberia quedarse en cero en operacion normal, y si
    # sube es que alguna generacion se esta eternizando.
    estado = compuerta.metricas()
    assert estado["rechazados_sala"] == 1
    assert estado["rechazados_espera"] == 0

    soltar.set()
    dentro.join(timeout=5)


def test_quien_si_entra_a_la_cola_acaba_servido():
    """Admitido es admitido: no se le suelta a mitad de la espera.

    La contraparte de la prueba de arriba. Si el presupuesto alcanza, la
    promesa se cumple aunque el trabajo tarde algo mas de lo estimado — de otro
    modo volveriamos a tener gente esperando para nada, solo que mas tarde.
    """
    compuerta = Compuerta("prueba", aforo=1, sala=2, espera_maxima=5,
                          duracion_inicial=0.05)
    soltar = threading.Event()
    resultados = {}

    dentro = _abrir_en_hilo(compuerta, resultados, 0, soltar)
    for _ in range(100):
        if compuerta.metricas()["en_curso"] == 1:
            break
        time.sleep(0.01)

    segundo = _abrir_en_hilo(compuerta, resultados, 1, soltar)
    for _ in range(100):
        if compuerta.metricas()["esperando"] == 1:
            break
        time.sleep(0.01)

    # El primero tarda bastante mas de lo que la estimacion suponia.
    time.sleep(0.4)
    soltar.set()
    dentro.join(timeout=5)
    segundo.join(timeout=5)

    assert resultados[1] is True, "se solto a alguien que ya habia sido admitido"


def test_la_compuerta_aprende_cuanto_tardan_los_trabajos():
    """La estimacion sale de lo medido, no de una constante.

    Es lo que hace que esto se ajuste solo cuando el modelo cambia de
    velocidad: otro modelo, una GPU, o simplemente una maquina mas ocupada.
    Nadie tiene que volver a calibrar un numero.
    """
    compuerta = Compuerta("prueba", aforo=1, sala=2, espera_maxima=5,
                          duracion_inicial=99)

    # Sin muestras manda el valor supuesto.
    assert compuerta.metricas()["duracion_mediana_s"] == 99.0

    for _ in range(3):
        with compuerta.turno() as hay_turno:
            assert hay_turno is True
            time.sleep(0.05)

    medida = compuerta.metricas()["duracion_mediana_s"]
    assert 0.0 < medida < 1.0, (
        f"la mediana quedo en {medida}s: sigue usando el valor supuesto en vez "
        "de lo que tardaron los trabajos de verdad"
    )


def test_la_plaza_se_libera_aunque_el_trabajo_reviente():
    """Una excepcion dentro del `with` no deja la plaza ocupada para siempre.

    Sin esto, el primer fallo de httpx dejaria el aforo en cero permanente: el
    portal se quedaria sin IA hasta el siguiente reinicio, y sin nada en los
    registros que apunte a la causa.
    """
    compuerta = Compuerta("prueba", aforo=1, sala=1, espera_maxima=1,
                          duracion_inicial=0.01)

    with pytest.raises(RuntimeError):
        with compuerta.turno() as hay_turno:
            assert hay_turno is True
            raise RuntimeError("se cayo Ollama a media llamada")

    assert compuerta.metricas()["en_curso"] == 0, "la plaza quedo ocupada tras el fallo"

    # Y la siguiente entra sin problema.
    with compuerta.turno() as hay_turno:
        assert hay_turno is True


def test_cinco_a_la_vez_ni_se_atropellan_ni_se_cuelgan():
    """El caso real: cinco personas preguntando a la vez.

    Con aforo 1 y sala 3, la cuenta tiene que salir exacta: uno trabaja, tres
    esperan y **uno se va rechazado**. Lo que no puede pasar de ninguna manera
    es que los cinco entren —serian cinco generaciones compitiendo por la misma
    CPU, que es mas lento para todos que hacerlas en fila— ni que alguno se
    quede colgado sin respuesta.
    """
    compuerta = Compuerta("prueba", aforo=1, sala=3, espera_maxima=5,
                          duracion_inicial=0.01)
    soltar = threading.Event()
    resultados = {}
    hilos = []

    for i in range(5):
        hilos.append(_abrir_en_hilo(compuerta, resultados, i, soltar))
        # Entran de forma escalonada, como llegarian de verdad.
        time.sleep(0.05)

    estado = compuerta.metricas()
    assert estado["en_curso"] == 1
    assert estado["esperando"] == 3
    assert estado["rechazados_sala"] == 1

    soltar.set()
    for hilo in hilos:
        hilo.join(timeout=10)
        assert not hilo.is_alive(), "un hilo se quedo colgado esperando turno"

    # Los cinco recibieron respuesta: cuatro un turno y uno un "ahora no".
    assert len(resultados) == 5
    assert sum(1 for v in resultados.values() if v) == 4
    assert sum(1 for v in resultados.values() if not v) == 1


def test_sin_turno_el_cliente_de_ollama_devuelve_none(monkeypatch):
    """El contrato que sostiene todo esto: un rechazo es `None`, no una excepcion.

    Si quedarse sin turno levantara, cada pico de carga se convertiria en un
    500 en la cara del usuario. Devolviendo `None` entra el camino que
    `ollama_client` ya tenia escrito desde el primer dia —se guarda la
    descripcion original, se piden los dropdowns, se muestran los extractos— y
    el ticket se levanta igual.
    """
    from app.services import cola_ia
    from app.services.ollama_client import ollama

    # La suite apaga la IA por defecto; aqui hace falta encendida para que las
    # llamadas lleguen hasta la compuerta en vez de salirse antes.
    monkeypatch.setattr(settings, "IA_HABILITADA", True)

    # Una compuerta sin plazas ni sala: rechaza todo, al instante.
    cerrada = Compuerta("cerrada", aforo=1, sala=0, espera_maxima=0.1)
    soltar = threading.Event()
    resultados = {}
    ocupante = _abrir_en_hilo(cerrada, resultados, 0, soltar)
    for _ in range(100):
        if cerrada.metricas()["en_curso"] == 1:
            break
        time.sleep(0.01)

    monkeypatch.setattr(cola_ia, "generacion", cerrada)
    monkeypatch.setattr(cola_ia, "embeddings", cerrada)

    # Ninguna de estas llega a tocar la red: la compuerta las corta antes.
    assert ollama.generar_embedding("la impresora saca una raya negra") is None
    assert ollama.normalizar_descripcion("no jala la impresora de embarques") is None
    assert ollama.responder_texto("redacta los pasos") is None
    assert ollama.responder_json("devuelve un objeto") is None

    soltar.set()
    ocupante.join(timeout=5)


# ----------------------------------------------------------------------
# La caché de vectores
# ----------------------------------------------------------------------
def test_el_mismo_texto_no_se_vectoriza_dos_veces(monkeypatch):
    """La misma frase se pide varias veces en la misma pantalla.

    Al escribir la descripción de un ticket consultan por separado las
    sugerencias parecidas, la respuesta del asistente y el catálogo visual, y
    cada una mandaba el mismo texto al modelo: ~80 ms de CPU por cabeza, en la
    máquina donde la CPU es el recurso escaso, repetidos en cada pausa de
    escritura.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    llamadas = []

    class RespuestaFalsa:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"embedding": [0.5] * 768}

    class ClienteFalso:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **k):
            llamadas.append(json.get("prompt"))
            return RespuestaFalsa()

    monkeypatch.setattr("app.services.ollama_client.httpx.Client", ClienteFalso)

    primero = ollama.generar_embedding("la copia sale borrosa", tarea="consulta")
    segundo = ollama.generar_embedding("la copia sale borrosa", tarea="consulta")

    assert primero == segundo
    assert len(llamadas) == 1


def test_consulta_y_documento_no_comparten_vector(monkeypatch):
    """El mismo texto como consulta y como documento son dos cosas distintas.

    nomic está entrenado con prefijos de tarea, así que confundirlos devolvería
    el vector equivocado **sin que nada fallara**: la búsqueda encontraría peor,
    en silencio, que es la peor clase de fallo que puede tener una caché.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(settings, "OLLAMA_MODELO_EMBEDDING", "nomic-embed-text")
    prompts = []

    class RespuestaFalsa:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"embedding": [float(len(prompts))] * 768}

    class ClienteFalso:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **k):
            prompts.append(json.get("prompt"))
            return RespuestaFalsa()

    monkeypatch.setattr("app.services.ollama_client.httpx.Client", ClienteFalso)

    consulta = ollama.generar_embedding("la copia sale borrosa", tarea="consulta")
    documento = ollama.generar_embedding("la copia sale borrosa", tarea="documento")

    assert len(prompts) == 2
    assert prompts[0].startswith("search_query: ")
    assert prompts[1].startswith("search_document: ")
    assert consulta != documento


def test_un_fallo_no_se_recuerda_como_respuesta(monkeypatch):
    """Guardar el `None` convertiría un fallo momentáneo en uno permanente."""
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    intentos = []

    class ClienteQueFalla:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            intentos.append(1)
            raise RuntimeError("Ollama caído")

    monkeypatch.setattr("app.services.ollama_client.httpx.Client", ClienteQueFalla)

    assert ollama.generar_embedding("la copia sale borrosa") is None
    assert ollama.generar_embedding("la copia sale borrosa") is None
    assert len(intentos) == 2


# ----------------------------------------------------------------------
# La sala no puede volver a mandar sobre el presupuesto
# ----------------------------------------------------------------------

#: Lo que tarda una generación corriente, medido en la ruta real con el modelo
#: usando cuatro hilos: normalizar 1.50 s, clasificar 0.95 s. Se toma el peor de
#: los dos, que es el que aprieta.
DURACION_CORRIENTE_S = 1.5


def test_la_sala_no_corta_muy_por_debajo_del_presupuesto():
    """El presupuesto de espera es quien debe decidir; la sala es un tope duro.

    Hay dos motivos de rechazo independientes: sala llena, o espera estimada
    por encima del presupuesto. Si la sala se llena cuando la espera estimada
    todavía está muy por debajo del presupuesto, **el presupuesto no llega a
    opinar nunca** y toda la estimación medida sobra.

    Eso pasaba con la sala en tres: desde que el modelo usa cuatro hilos, una
    generación corriente tarda ~1,5 s, así que el cuarto que llegaba se iba sin
    IA con una espera estimada de 6 s —un 20 % del presupuesto—.

    Se fija la relación, no el número. El corte en 40 % no es mágico: es
    "que la sala no se cierre en el primer tercio de lo que estamos dispuestos
    a esperar". Si alguien baja la sala, o el modelo se vuelve tan rápido que
    llenarla ya no supone espera, esta prueba lo dice.
    """
    from app.core.config import settings

    # El que llega con la sala llena esperaría `sala + 1` turnos (aforo 1).
    al_llenarse = (settings.IA_SALA_GENERACION + 1) * DURACION_CORRIENTE_S
    fraccion = al_llenarse / settings.IA_ESPERA_MAXIMA_GENERACION
    assert fraccion >= 0.40, (
        f"la sala ({settings.IA_SALA_GENERACION}) se llena cuando la espera "
        f"estimada es de solo {al_llenarse:.1f} s, un {fraccion:.0%} del "
        f"presupuesto de {settings.IA_ESPERA_MAXIMA_GENERACION:.0f} s: rechaza "
        f"a gente que cabía de sobra y deja sin efecto la estimación medida"
    )


def test_la_sala_sigue_siendo_un_tope_de_hilos():
    """El contrapeso: tampoco puede crecer sin freno.

    Cada uno esperando retiene un hilo del *pool* de FastAPI, que trae cuarenta.
    """
    from app.core.config import settings

    assert settings.IA_SALA_GENERACION <= 16, (
        "la sala de generación retiene un hilo del pool por cada persona "
        "esperando; con el pool de FastAPI en 40, pasar de 16 es arriesgado"
    )
