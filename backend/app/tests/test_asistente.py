"""El asistente contesta con lo de la planta, o dice que no sabe.

Lo que se prueba aquí no es que responda bien. Es que **no responda cuando no
debe**. En una planta, un procedimiento inventado manda a un técnico a desarmar
una impresora sana, y eso cuesta más que no haber contestado.

Cuatro cortes, en orden:

  1. Si no hay nada parecido en lo nuestro, no se consulta a ningún modelo.
  2. Si el modelo dice que no sabe, se respeta.
  3. Si contesta sin decir nada, se descarta.
  4. Si lo que dice no viene de las fuentes, se descarta.
"""

import pytest

from app.services.asistente_service import AsistenteService
from app.services.recuperacion_service import Pasaje, RecuperacionService


PASAJES = [
    Pasaje(
        fuente="ticket", referencia_id=7,
        titulo="Raya negra vertical al imprimir",
        # Tal como queda en la base de conocimiento: categoría, descripción y
        # solución completa. Medir el anclaje contra un extracto recortado da
        # números que no se parecen a los de producción.
        texto=("impresora\n"
               "La impresora del almacén saca una raya negra vertical en todas las "
               "hojas que imprime.\n"
               "Se limpió el rodillo de transferencia con un paño seco y sin "
               "solvente. La raya desapareció de inmediato. Si vuelve en menos de "
               "un mes, el rodillo ya está gastado y hay que pedir el repuesto."),
        # 0.69 es lo que dio la medición real de este mismo caso, y queda por
        # debajo del umbral del nivel 0: así estas pruebas ejercitan la
        # redacción. El nivel 0 tiene sus propias pruebas más abajo.
        similitud=0.69, categoria="impresora",
        descartado="Se cambió el tóner primero y siguió igual: no era el tóner.",
    ),
    Pasaje(
        fuente="documento", referencia_id=3,
        titulo="Mantenimiento de impresoras de planta",
        texto="Las impresoras de línea se limpian cada 5 000 impresiones.",
        similitud=0.66, categoria="procedimiento",
    ),
]


def responde(monkeypatch, texto):
    """El modelo local devuelve este texto."""
    monkeypatch.setattr("app.services.asistente_service.ollama.responder_texto",
                        lambda *a, **k: texto)


def encuentra(monkeypatch, pasajes):
    monkeypatch.setattr(RecuperacionService, "buscar",
                        staticmethod(lambda *a, **k: pasajes))


@pytest.fixture(autouse=True)
def sin_gemini(monkeypatch):
    """Por omisión Gemini no está: se prueba el camino barato."""
    monkeypatch.setattr("app.services.asistente_service.gemini.api_key", "")


def con_gemini(monkeypatch, respuesta):
    """Enciende Gemini y le hace devolver `respuesta`."""
    monkeypatch.setattr("app.services.asistente_service.gemini.api_key", "llave")
    monkeypatch.setattr("app.services.asistente_service.gemini.redactar",
                        lambda *a, **k: respuesta)


def espiar_instruccion(monkeypatch, devolver="listo [1]"):
    """Guarda el prompt que recibió el modelo local, para poder revisarlo."""
    visto = {}

    def espia(instruccion, **kwargs):
        visto["prompt"] = instruccion
        return devolver

    monkeypatch.setattr("app.services.asistente_service.ollama.responder_texto", espia)
    return visto


# ----------------------------------------------------------------------
# El corte que más importa
# ----------------------------------------------------------------------
def test_sin_nada_parecido_no_se_consulta_a_ningun_modelo(db_session, monkeypatch):
    """Un modelo al que no se le da nada, se lo inventa. Mejor ni preguntarle."""
    encuentra(monkeypatch, [])
    llamadas = {"n": 0}

    def contar(*a, **k):
        llamadas["n"] += 1
        return "algo que suena bien"

    monkeypatch.setattr("app.services.asistente_service.ollama.responder_texto", contar)

    salida = AsistenteService.responder(db_session, "cómo cambio el aceite del torno", 1)

    assert salida["origen"] == "sin_fundamento"
    assert salida["fundamentada"] is False
    assert salida["respuesta"] is None
    assert llamadas["n"] == 0        # ni se le preguntó


def test_una_pregunta_vacia_no_llega_a_ningun_lado(db_session):
    salida = AsistenteService.responder(db_session, "   ", 1)
    assert salida["origen"] == "pregunta_vacia"


# ----------------------------------------------------------------------
# Cuando sí hay de dónde
# ----------------------------------------------------------------------
def test_responde_citando_la_fuente(db_session, monkeypatch):
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, "Limpie el rodillo de transferencia con un paño seco.")

    salida = AsistenteService.responder(db_session, "sale una raya negra", 1)

    assert salida["origen"] == "ollama"
    assert salida["fundamentada"] is True
    assert "rodillo" in salida["respuesta"]


def test_las_fuentes_son_las_que_se_recuperaron(db_session, monkeypatch):
    """No las que el modelo diga haber usado: un modelo puede mentir en su cita,
    el recuperador no tiene cómo."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, "Limpie el rodillo de transferencia con un paño seco.")

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert [f["referencia_id"] for f in salida["fuentes"]] == [7, 3]


def test_al_modelo_local_no_se_le_da_el_descarte(db_session, monkeypatch):
    """Fallo real: con el descarte en contexto, qwen2.5:3b escribió como paso
    'cambiar el tóner completo nuevamente' —justo lo que no sirve—.

    Un modelo chico no distingue 'esto se probó' de 'esto se hace'.
    """
    encuentra(monkeypatch, PASAJES)
    visto = espiar_instruccion(monkeypatch)

    AsistenteService.responder(db_session, "raya negra", 1)

    assert "tóner" not in visto["prompt"]
    assert "rodillo" in visto["prompt"]


def test_a_gemini_si_se_le_da_el_descarte(db_session, monkeypatch):
    """Un modelo grande sí sabe qué hacer con esa información."""
    visto = {}
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, None)
    monkeypatch.setattr("app.services.asistente_service.gemini.api_key", "llave")

    def espia(instruccion):
        visto["prompt"] = instruccion
        return {"respuesta": "Limpie el rodillo de transferencia con paño seco.",
                "tokens_entrada": 1, "tokens_salida": 1, "modelo": "x"}

    monkeypatch.setattr("app.services.asistente_service.gemini.redactar", espia)
    AsistenteService.responder(db_session, "raya negra", 1)

    assert "no era el tóner" in visto["prompt"]


def test_el_descarte_siempre_llega_a_la_persona(db_session, monkeypatch):
    """Aunque no vaya al modelo, se enseña junto a la fuente."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, "Limpie el rodillo de transferencia con un paño seco.")

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert any(f["descartado"] for f in salida["fuentes"])


def test_las_dos_fuentes_se_mezclan(db_session, monkeypatch):
    """Tickets resueltos y documentación de TI, en el mismo contexto."""
    encuentra(monkeypatch, PASAJES)
    visto = espiar_instruccion(monkeypatch, "ok [1] [2]")

    AsistenteService.responder(db_session, "raya negra", 1)

    assert "Raya negra vertical" in visto["prompt"]
    assert "Mantenimiento de impresoras" in visto["prompt"]


# ----------------------------------------------------------------------
# Cuando el modelo se sale del guion
# ----------------------------------------------------------------------
def test_si_el_modelo_dice_que_no_sabe_se_le_cree(db_session, monkeypatch):
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, "NO_TENGO_INFORMACION")

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "extractos"
    assert salida["respuesta"] is None
    assert len(salida["fuentes"]) == 2      # se le enseñan los extractos


def test_una_respuesta_que_habla_de_otra_cosa_se_descarta(db_session, monkeypatch):
    """El fallo que preocupa: contestar algo plausible que no viene al caso."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, ("Revise el fusor y sustituya el kit de mantenimiento "
                           "siguiendo el manual del fabricante; verifique también "
                           "los sensores ópticos del carro."))

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "extractos"
    assert salida["respuesta"] is None


def test_el_anclaje_se_mide_contra_titulo_texto_y_descarte(db_session, monkeypatch):
    """Mencionar lo que ya se descartó no debe contar como salirse del guion."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, ("Limpie el rodillo de transferencia con paño seco. "
                           "El tóner ya se cambió antes y siguió igual."))

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "ollama"


def test_sin_ningun_modelo_se_entregan_los_extractos(db_session, monkeypatch):
    """Menos cómodo de leer, exactamente igual de cierto."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, None)

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "extractos"
    assert salida["fundamentada"] is True
    assert len(salida["fuentes"]) == 2


def test_una_respuesta_que_solo_cita_no_sirve(db_session, monkeypatch):
    """Pasó de verdad: qwen2.5:3b contestó "[1]" y nada más.

    Cumplía la regla de citar al pie de la letra y no le decía nada a quien lo
    leía. Vale más enseñarle el extracto completo.
    """
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, "[1]")

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "extractos"
    assert salida["respuesta"] is None


def test_una_respuesta_corta_pero_util_si_pasa(db_session, monkeypatch):
    """El corte es por vacío, no por brevedad. Una instrucción corta sirve."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, "Limpie el rodillo con paño seco.")

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "ollama"


# ----------------------------------------------------------------------
# El corte relativo de la búsqueda
# ----------------------------------------------------------------------
def test_lo_que_queda_muy_por_debajo_del_mejor_se_descarta(db_session, monkeypatch):
    """Medido en planta: el ticket correcto sale al 69% y uno de 'cuenta
    bloqueada' al 64%. Los dos pasan cualquier umbral fijo."""
    from app.services.recuperacion_service import RecuperacionService as R

    monkeypatch.setattr(R, "_de_tickets", staticmethod(lambda *a, **k: [
        Pasaje(fuente="ticket", referencia_id=1, titulo="Raya negra al imprimir",
               texto="...", similitud=0.69),
        Pasaje(fuente="ticket", referencia_id=2, titulo="Cuenta bloqueada",
               texto="...", similitud=0.64),
        Pasaje(fuente="ticket", referencia_id=3, titulo="Impresora sin conexión",
               texto="...", similitud=0.62),
    ]))
    monkeypatch.setattr(R, "_de_documentacion", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr("app.services.recuperacion_service.ollama.generar_embedding",
                        lambda *a, **k: [0.0] * 768)

    pasajes = R.buscar(db_session, "linea oscura al imprimir", 1)

    assert len(pasajes) == 1
    assert pasajes[0].referencia_id == 1


def test_si_dos_empatan_arriba_los_dos_sirven(db_session, monkeypatch):
    """El corte es relativo, no un tope de uno."""
    from app.services.recuperacion_service import RecuperacionService as R

    monkeypatch.setattr(R, "_de_tickets", staticmethod(lambda *a, **k: [
        Pasaje(fuente="ticket", referencia_id=1, titulo="A", texto="...", similitud=0.82),
        Pasaje(fuente="ticket", referencia_id=2, titulo="B", texto="...", similitud=0.80),
    ]))
    monkeypatch.setattr(R, "_de_documentacion", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr("app.services.recuperacion_service.ollama.generar_embedding",
                        lambda *a, **k: [0.0] * 768)

    assert len(R.buscar(db_session, "algo", 1)) == 2


def test_sin_embeddings_no_hay_recuperacion_pero_tampoco_error(db_session, monkeypatch):
    from app.services.recuperacion_service import RecuperacionService as R

    monkeypatch.setattr("app.services.recuperacion_service.ollama.generar_embedding",
                        lambda *a, **k: None)

    assert R.buscar(db_session, "algo", 1) == []


# ----------------------------------------------------------------------
# Reparto entre modelos
# ----------------------------------------------------------------------
def test_gemini_no_se_toca_si_el_local_alcanzo(db_session, monkeypatch):
    """Lo que resuelve gratis el modelo local no se paga."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, "Limpie el rodillo de transferencia con un paño seco.")
    llamadas = {"n": 0}
    monkeypatch.setattr("app.services.asistente_service.gemini.api_key", "llave")
    monkeypatch.setattr("app.services.asistente_service.gemini.redactar",
                        lambda *a, **k: llamadas.update(n=llamadas["n"] + 1))

    AsistenteService.responder(db_session, "raya negra", 1)

    assert llamadas["n"] == 0


def test_gemini_entra_cuando_el_local_no_alcanza(db_session, monkeypatch):
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, None)
    con_gemini(monkeypatch, {"respuesta": "Limpie el rodillo de transferencia con un paño seco.",
                             "tokens_entrada": 300, "tokens_salida": 40,
                             "modelo": "gemini-2.5-flash"})

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "gemini"
    assert salida["consumo"]["tokens_entrada"] == 300


def test_a_gemini_tambien_se_le_revisa_el_anclaje(db_session, monkeypatch):
    """Pagar por la respuesta no la vuelve confiable."""
    encuentra(monkeypatch, PASAJES)
    responde(monkeypatch, None)
    con_gemini(monkeypatch, {"respuesta": ("Revise el fusor y sustituya el kit de "
                                           "mantenimiento del fabricante, verificando "
                                           "los sensores ópticos del carro."),
                             "tokens_entrada": 300, "tokens_salida": 40,
                             "modelo": "gemini-2.5-flash"})

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "extractos"


# ----------------------------------------------------------------------
# La operación, de punta a punta
# ----------------------------------------------------------------------
def test_la_operacion_responde_sin_conocimiento_cargado(client):
    """Con la base vacía debe decir que no sabe, no inventar."""
    token = client.post("/api/auth/login",
                        json={"email": "user@test.com", "password": "Secret123!"}).json()
    r = client.post("/api/asistente/preguntar",
                    json={"texto": "la impresora saca una raya negra"},
                    headers={"Authorization": f"Bearer {token['access_token']}"})

    assert r.status_code == 200
    assert r.json()["fundamentada"] is False


def test_la_operacion_pide_sesion(client):
    r = client.post("/api/asistente/preguntar", json={"texto": "hola"})
    assert r.status_code in (401, 403)


# ----------------------------------------------------------------------
# Dónde queda el corte del anclaje
#
# Los números de aquí no son inventados: se midieron contra respuestas reales
# de qwen2.5:3b sobre este mismo pasaje. Este test es lo que evita que alguien
# mueva el umbral "un poquito" y deje pasar la respuesta genérica.
# ----------------------------------------------------------------------
CASOS_ANCLAJE = [
    # (nombre, texto, debe_pasar)
    ("la que contestó el modelo local de verdad",
     "Qué hacer:\n\n1. Limpiar el rodillo de transferencia con un paño seco y sin "
     "solvente.\n\n2. Si la raya persiste, verificar si el rodillo ya está gastado y "
     "si es necesario pedir el repuesto.\n\n3. Si la raya vuelve en menos de un mes, "
     "es posible que el problema esté relacionado con el rodillo.", True),
    ("breve y al grano",
     "Limpie el rodillo de transferencia con un paño seco.", True),
    ("mencionando lo que ya se descartó",
     "Limpie el rodillo de transferencia con paño seco. El tóner ya se cambió antes "
     "y siguió igual.", True),
    ("se fue por otro lado",
     "Revise el fusor y sustituya el kit de mantenimiento siguiendo el manual del "
     "fabricante; verifique también los sensores ópticos del carro.", False),
    ("consejo genérico de internet",
     "Reinicie el equipo, actualice los controladores desde el sitio del fabricante "
     "y ejecute el diagnóstico automático del sistema operativo.", False),
]


@pytest.mark.parametrize("nombre,texto,debe_pasar", CASOS_ANCLAJE,
                         ids=[c[0] for c in CASOS_ANCLAJE])
def test_el_anclaje_separa_lo_bueno_de_lo_inventado(nombre, texto, debe_pasar):
    from app.services.asistente_service import AsistenteService as A

    paso = A._validar(texto, PASAJES) is not None
    assert paso is debe_pasar, (
        f"{nombre}: anclaje medido {A._anclaje(texto, PASAJES):.2f}")


# ----------------------------------------------------------------------
# Nivel 0: cuando la respuesta ya está escrita
#
# Es el peldaño que más trabajo hace y el que menos se nota. Si el parecido no
# deja dudas, meter un modelo a redactar solo agrega latencia y una oportunidad
# de que le cambie el sentido a algo que ya estaba bien.
# ----------------------------------------------------------------------
def clonar(pasaje, **cambios):
    from dataclasses import replace
    return replace(pasaje, **cambios)


def test_una_coincidencia_clara_se_entrega_sin_modelo(db_session, monkeypatch):
    encuentra(monkeypatch, [clonar(PASAJES[0], similitud=0.88)])
    llamadas = {"n": 0}
    monkeypatch.setattr("app.services.asistente_service.ollama.responder_texto",
                        lambda *a, **k: llamadas.update(n=llamadas["n"] + 1))

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "directo"
    assert "rodillo" in salida["respuesta"]
    assert llamadas["n"] == 0        # ningún modelo redactó nada


def test_dos_coincidencias_igual_de_buenas_si_se_redactan(db_session, monkeypatch):
    """La respuesta está repartida entre las dos: hay que juntarlas."""
    encuentra(monkeypatch, [clonar(PASAJES[0], similitud=0.88),
                            clonar(PASAJES[1], similitud=0.86)])
    responde(monkeypatch, "Limpie el rodillo de transferencia con un paño seco.")

    salida = AsistenteService.responder(db_session, "raya negra", 1)

    assert salida["origen"] == "ollama"


def test_el_nivel_0_no_gasta_en_gemini(db_session, monkeypatch):
    encuentra(monkeypatch, [clonar(PASAJES[0], similitud=0.88)])
    llamadas = {"n": 0}
    monkeypatch.setattr("app.services.asistente_service.gemini.api_key", "llave")
    monkeypatch.setattr("app.services.asistente_service.gemini.redactar",
                        lambda *a, **k: llamadas.update(n=llamadas["n"] + 1))

    AsistenteService.responder(db_session, "raya negra", 1)

    assert llamadas["n"] == 0


def test_sin_nada_se_dice_que_levante_ticket(db_session, monkeypatch):
    """El 'no sé' tiene que decir por dónde seguir."""
    encuentra(monkeypatch, [])

    salida = AsistenteService.responder(db_session, "algo nunca visto", 1)

    assert salida["siguiente_paso"] == "levantar_ticket"
