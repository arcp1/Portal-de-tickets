"""Lo que el inventario no puede permitirse.

El número de serie es lo que distingue el equipo físico: es lo que se imprime
en el resguardo que la persona firma y lo que se lee del activo cuando lo
devuelve. Si dos filas dicen ser el mismo equipo, el inventario cuenta dos
donde hay uno y un resguardo firmado puede apuntar a la equivocada; el papel
deja de identificar el activo, que es lo único que tenía que hacer.

El resto de columnas —`tipo`, `estado`— son enumeraciones que el modelo guarda
como texto. Un valor inventado no rompe nada visiblemente: hace que el equipo
desaparezca de donde se le busca, porque el formulario de resguardos solo
lista los "disponible".
"""

import pytest


def cab(client, identificador="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def alta(client, **extra):
    payload = {
        "sitio_id": 1,
        "tipo": "activo",
        "categoria": "Impresora",
        "marca": "Zebra",
        "modelo": "ZT230",
        "numero_serie": "ZEB-0001",
    }
    payload.update(extra)
    return client.post("/api/equipos", json=payload, headers=cab(client))


# ----------------------------------------------------------------------
# Número de serie
# ----------------------------------------------------------------------

def test_no_se_registra_dos_veces_la_misma_serie(client):
    assert alta(client).status_code == 201

    repetida = alta(client, modelo="ZT230 clonada")
    assert repetida.status_code == 409
    assert "ZEB-0001" in repetida.json()["detail"]


def test_no_se_le_pega_a_otro_equipo_la_serie_de_uno_existente(client):
    primero = alta(client).json()
    segundo = alta(client, numero_serie="CIS-0002", marca="Cisco", modelo="Catalyst").json()

    choque = client.patch(f"/api/equipos/{segundo['id']}",
                          json={"numero_serie": primero["numero_serie"]}, headers=cab(client))
    assert choque.status_code == 409


def test_un_equipo_puede_reescribir_su_propia_serie(client):
    """La comprobación se excluye a sí misma: guardar la ficha sin tocar la
    serie no puede chocar consigo mismo."""
    equipo = alta(client).json()

    r = client.patch(f"/api/equipos/{equipo['id']}",
                     json={"numero_serie": "ZEB-0001", "ubicacion": "Línea 3"},
                     headers=cab(client))
    assert r.status_code == 200, r.text
    assert r.json()["ubicacion"] == "Línea 3"


def test_la_serie_en_blanco_se_guarda_como_nula(client):
    """Un activo puede llegar sin serie legible. La cadena vacía que manda el
    formulario tiene que volverse NULL: si no, todos los equipos sin serie
    comparten la serie "" y chocan entre sí."""
    primero = alta(client, numero_serie="   ")
    segundo = alta(client, numero_serie="", modelo="Otra sin serie")

    assert primero.status_code == 201
    assert primero.json()["numero_serie"] is None
    # Dos equipos sin serie conviven sin problema.
    assert segundo.status_code == 201
    assert segundo.json()["numero_serie"] is None


# ----------------------------------------------------------------------
# Enumeraciones
# ----------------------------------------------------------------------

@pytest.mark.parametrize("campo,valor", [
    ("tipo", "etereo"),
    ("estado", "pulverizado"),
])
def test_un_valor_inventado_se_rechaza_al_dar_de_alta(client, campo, valor):
    r = alta(client, **{campo: valor})
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("campo,valor", [
    ("tipo", "etereo"),
    ("estado", "pulverizado"),
])
def test_un_valor_inventado_se_rechaza_al_editar(client, campo, valor):
    equipo = alta(client).json()
    r = client.patch(f"/api/equipos/{equipo['id']}", json={campo: valor}, headers=cab(client))
    assert r.status_code == 422, r.text


def test_asignar_a_alguien_que_no_existe_no_revienta(client):
    """Antes el id viajaba tal cual a la clave foránea y salía un 500."""
    equipo = alta(client).json()
    r = client.patch(f"/api/equipos/{equipo['id']}", json={"asignado_a": 99999}, headers=cab(client))
    assert r.status_code == 422, r.text
