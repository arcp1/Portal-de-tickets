"""Documentación de TI: lo que hoy vive en la cabeza de dos personas.

El módulo entero —seis endpoints, con búsqueda por significado— no tenía
ninguna prueba. Es donde se guardan procedimientos, direccionamiento y datos
de proveedores: si algo de aquí se filtra o se pierde, no se nota hasta el día
que hace falta y ya no está.

Dos cosas se fijan por encima del resto: que sea solo de TI —un procedimiento
puede incluir a quién llamar y con qué contrato, y eso no lo lee la planta— y
que la búsqueda siga funcionando aunque Ollama no responda, porque la caída
de la IA nunca puede dejar a alguien sin encontrar el procedimiento.
"""

import pytest


def cab(client, identificador="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def alta(client, **extra):
    payload = {
        "titulo": "Reinicio del switch del IDC principal",
        "contenido": ("Antes de reiniciar el Catalyst del IDC hay que avisar a producción: "
                      "la línea 1 pierde red unos cuarenta segundos."),
        "categoria": "red",
    }
    payload.update(extra)
    return client.post("/api/documentacion", json=payload, headers=cab(client))


# ----------------------------------------------------------------------
# Quién entra
# ----------------------------------------------------------------------

@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/api/documentacion"),
    ("get", "/api/documentacion/categorias"),
    ("post", "/api/documentacion"),
    ("post", "/api/documentacion/buscar"),
])
def test_es_solo_de_ti(client, metodo, ruta):
    """Un procedimiento puede decir a quién llamar y con qué contrato."""
    cabeceras = cab(client, "user@test.com")
    llamar = getattr(client, metodo)
    r = llamar(ruta, headers=cabeceras) if metodo == "get" else llamar(ruta, json={}, headers=cabeceras)
    assert r.status_code == 403, ruta


def test_un_usuario_no_borra_documentacion(client):
    documento = alta(client).json()

    r = client.delete(f"/api/documentacion/{documento['id']}", headers=cab(client, "user@test.com"))

    assert r.status_code == 403
    assert client.get("/api/documentacion", headers=cab(client)).json() != []


# ----------------------------------------------------------------------
# Alta y categorías
# ----------------------------------------------------------------------

def test_se_da_de_alta_y_aparece_en_el_listado(client):
    assert alta(client).status_code == 201

    listado = client.get("/api/documentacion", headers=cab(client)).json()

    assert len(listado) == 1
    assert listado[0]["categoria"] == "red"


def test_una_categoria_inventada_se_rechaza(client):
    """Las categorías son las pestañas por las que se busca: una inventada
    esconde el documento en una pestaña que no existe."""
    assert alta(client, categoria="telepatia").status_code == 422


def test_las_categorias_que_ofrece_son_las_que_acepta(client):
    """Si el desplegable ofreciera una categoría que el alta rechaza, el
    formulario fallaría eligiendo justo lo que él mismo propuso."""
    ofrecidas = client.get("/api/documentacion/categorias", headers=cab(client)).json()["categorias"]

    for categoria in ofrecidas:
        r = alta(client, categoria=categoria, titulo=f"Procedimiento de {categoria}")
        assert r.status_code == 201, categoria


# ----------------------------------------------------------------------
# Encontrarlo
# ----------------------------------------------------------------------

def test_se_encuentra_por_palabras_del_titulo_o_del_contenido(client):
    alta(client)

    por_titulo = client.get("/api/documentacion?buscar=switch", headers=cab(client)).json()
    por_contenido = client.get("/api/documentacion?buscar=producción", headers=cab(client)).json()

    assert len(por_titulo) == 1
    assert len(por_contenido) == 1


def test_la_busqueda_por_significado_responde(client):
    alta(client)

    r = client.post("/api/documentacion/buscar",
                    json={"texto": "cómo apagar el aparato de red de la planta"},
                    headers=cab(client))

    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_sin_ollama_la_busqueda_sigue_encontrando(client, monkeypatch):
    """La caída de la IA nunca puede dejar a alguien sin su procedimiento.

    Cuando Ollama no responde, `generar_embedding` devuelve None —lo captura
    todo por dentro, que es su contrato— y el endpoint cae a la búsqueda por
    palabras. Lo que se fija aquí es que esa caída **encuentre**, no que
    simplemente no reviente: devolver una lista vacía sería tan inútil como
    un error, solo que más difícil de diagnosticar.
    """
    from app.api import documentacion_ti

    monkeypatch.setattr(documentacion_ti.ollama, "generar_embedding",
                        lambda *a, **kw: None, raising=False)
    alta(client)

    r = client.post("/api/documentacion/buscar",
                    json={"texto": "switch"}, headers=cab(client))

    assert r.status_code == 200, r.text
    assert len(r.json()) == 1, "sin Ollama tenia que encontrarlo por texto"


def test_un_texto_de_dos_letras_no_es_una_busqueda(client):
    r = client.post("/api/documentacion/buscar", json={"texto": "ab"}, headers=cab(client))
    assert r.status_code == 422
