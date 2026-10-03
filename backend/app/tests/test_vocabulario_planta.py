"""El atajo de vocabulario: lo que resuelve sin llamar a ningun modelo.

**Por que importa mas de lo que parece.** Medido en esta maquina, clasificar con
el modelo cuesta entre 2 y 10 segundos segun acierte la cache de Ollama, y a los
10 se pasa del timeout y el chat cae a los desplegables. El atajo contesta en
microsegundos, es determinista y se corrige editando una linea.

Las dos propiedades que lo hacen fiable, y que estas pruebas vigilan:

  1. **Precision antes que cobertura.** Cuando contesta, acierta. Un atajo que
     se equivoca es peor que no tenerlo: manda la incidencia a la cola
     equivocada sin que nadie lo revise.
  2. **Ante la duda, se calla.** Si la frase menciona dos mundos a la vez, no
     adivina: devuelve None y decide el modelo o la persona.
"""

import pytest

from app.services.ollama_client import CATEGORIAS_VALIDAS, OllamaClient

#: Frases como las escribe la gente en planta, con su categoria correcta.
#: Las cinco primeras ya las atrapaba; las demas se anadieron al ampliar la
#: tabla, y estan aqui para que nadie las pierda sin enterarse.
FRASES = [
    ("no jala la impresora del anden 2", "impresora"),
    ("se cae el wifi en el almacen", "red"),
    ("la laptop no enciende", "equipo"),
    ("no puedo entrar al correo", "accesos"),
    ("el sistema marca error al guardar", "software"),
    ("la maquina de la linea 3 se reinicia sola", "equipo"),
    ("se cae la senal en la zona de embarques", "red"),
    ("no me carga el tablero de produccion", "software"),
    ("la terminal del comedor no lee el gafete", "equipo"),
    ("se traba al generar el reporte de fin de turno", "software"),
    ("no me deja entrar al sistema con mi contrasena", "accesos"),
]

#: Frases que mencionan dos mundos a la vez. El atajo **tiene** que callarse.
AMBIGUAS = [
    "la impresora no aparece en la red",
    "el escaner no conecta con el wifi",
]


@pytest.mark.parametrize("texto,esperada", FRASES)
def test_el_atajo_acierta_cuando_contesta(texto, esperada):
    """Precision: si devuelve una categoria, es la correcta.

    Es la propiedad que justifica saltarse el modelo. En cuanto el atajo
    empiece a equivocarse deja de ser un atajo y pasa a ser un error rapido.
    """
    voto = OllamaClient.clasificar_por_vocabulario(texto)
    assert voto is not None, f"«{texto}» ya no la atrapa el vocabulario"
    assert voto["categoria"] == esperada
    assert voto["categoria"] in CATEGORIAS_VALIDAS
    assert 0.0 <= voto["confianza"] <= 1.0


@pytest.mark.parametrize("texto", AMBIGUAS)
def test_ante_la_duda_se_calla(texto):
    """Dos mundos mencionados a la vez: no se adivina.

    "La impresora no aparece en la red" puede ser el driver o el cable. El
    atajo devuelve None y la decision sube al modelo, o a la persona.
    """
    assert OllamaClient.clasificar_por_vocabulario(texto) is None


def test_la_cobertura_no_baja():
    """Guarda contra una poda descuidada de la tabla.

    Se amplio midiendo: de 5 de 12 frases reales a 10 de 12, sin perder
    precision. Si alguien quita terminos, esto lo dice antes de que el chat
    empiece a tardar diez segundos donde antes tardaba cero.
    """
    atrapadas = sum(
        1 for texto, _ in FRASES
        if OllamaClient.clasificar_por_vocabulario(texto) is not None
    )
    assert atrapadas >= len(FRASES), (
        f"el vocabulario solo atrapa {atrapadas} de {len(FRASES)} frases conocidas"
    )


def test_un_texto_sin_nada_reconocible_no_inventa():
    """Sin coincidencias no hay categoria. El modelo decide, o los desplegables."""
    assert OllamaClient.clasificar_por_vocabulario("buenos dias, una consulta") is None
    assert OllamaClient.clasificar_por_vocabulario("") is None
