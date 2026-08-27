"""Importación masiva de personal desde CSV.

Con 300+ empleados, dar de alta uno por uno no es viable. Lo que se prueba aquí
es que el archivo de RH —con sus encabezados impredecibles y su codificación de
Excel— se convierta en cuentas sin dejar el padrón a medias.
"""

import io

import pytest

from app.core.config import settings
from app.models import Usuario


def token(client, identificador="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": password})
    return r.json()["access_token"]


def cab(client, identificador="admin@test.com"):
    return {"Authorization": f"Bearer {token(client, identificador=identificador)}"}


@pytest.fixture(autouse=True)
def dominio_de_prueba(monkeypatch):
    monkeypatch.setattr(settings, "DOMINIOS_PERMITIDOS", "test.com")


CSV_BUENO = """numero_empleado,nombre,area,email,fecha_ingreso
30001,Juan Pérez Martínez,Producción,juan@test.com,2021-03-15
30002,María López Sánchez,Calidad,,2019-11-02
30003,Pedro Ramírez Cruz,Almacén,,15/07/2022
"""


def subir(client, contenido, ruta="/api/admin/importacion/analizar", **datos):
    return client.post(
        ruta,
        files={"archivo": ("personal.csv", io.BytesIO(
            contenido.encode("utf-8") if isinstance(contenido, str) else contenido
        ), "text/csv")},
        data=datos,
        headers=cab(client),
    )


# ----------------------------------------------------------------------
# Análisis previo
# ----------------------------------------------------------------------
def test_el_analisis_no_escribe_nada(client, db_session):
    """Se corre antes de importar: nadie carga 300 filas a ciegas."""
    r = subir(client, CSV_BUENO)

    assert r.status_code == 200
    assert r.json()["validas"] == 3
    assert db_session.query(Usuario).filter(Usuario.numero_empleado == "30001").first() is None


def test_reconoce_encabezados_de_rh(client):
    """Las listas de RH nunca traen los nombres que uno quisiera."""
    csv_rh = ("No. Empleado;Nombre Completo;Departamento;Correo;Fecha de Ingreso\n"
              "30010;Ana Torres Gómez;Recursos Humanos;ana@test.com;2020-05-01\n")
    r = subir(client, csv_rh)

    assert r.status_code == 200
    assert r.json()["validas"] == 1
    assert r.json()["columnas_detectadas"]["numero_empleado"] == "No. Empleado"


def test_lee_archivos_de_excel_en_windows(client):
    """Excel exporta en cp1252, no en UTF-8."""
    contenido = "numero_empleado,nombre,area\n30020,José Muñoz Peña,Producción\n".encode("cp1252")
    r = subir(client, contenido)

    assert r.status_code == 200
    assert r.json()["validas"] == 1
    assert "Muñoz" in r.json()["filas"][0]["nombre"]


def test_detecta_duplicados_dentro_del_archivo(client):
    csv_malo = ("numero_empleado,nombre\n"
                "30030,Persona Uno\n"
                "30030,Persona Dos\n")
    datos = subir(client, csv_malo).json()

    assert datos["validas"] == 1
    assert datos["con_error"] == 1
    assert "repite" in datos["filas"][1]["error"]


def test_detecta_choques_con_lo_ya_existente(client):
    csv_choque = "numero_empleado,nombre\n1001,Alguien Más\n"
    datos = subir(client, csv_choque).json()

    assert datos["con_error"] == 1
    assert "Ya existe" in datos["filas"][0]["error"]


def test_avisa_de_quien_no_trae_correo(client):
    datos = subir(client, CSV_BUENO).json()
    assert datos["sin_correo"] == 2
    assert "no recibirá avisos" in datos["filas"][1]["aviso"]


def test_rechaza_un_archivo_sin_las_columnas_minimas(client):
    datos = subir(client, "algo,otra_cosa\n1,2\n").json()
    assert datos["ok"] is False
    assert "numero_empleado" in datos["error"]


def test_rechaza_un_archivo_vacio(client):
    r = client.post("/api/admin/importacion/analizar",
                    files={"archivo": ("vacio.csv", io.BytesIO(b""), "text/csv")},
                    headers=cab(client))
    assert r.status_code == 422


# ----------------------------------------------------------------------
# Importación
# ----------------------------------------------------------------------
def test_importa_y_genera_codigos(client, db_session):
    r = subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
              modo_activacion="codigo")

    assert r.status_code == 200
    datos = r.json()
    assert datos["importadas"] == 3
    assert all(f["codigo"] for f in datos["filas"])
    assert db_session.query(Usuario).filter(Usuario.numero_empleado == "30001").first() is not None


def test_las_cuentas_importadas_nacen_pendientes(client, db_session):
    subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar")

    usuario = db_session.query(Usuario).filter(Usuario.numero_empleado == "30002").first()
    assert usuario.estado_cuenta == "pendiente_activacion"
    assert usuario.password_hash is None
    assert usuario.email is None       # no traía correo y se respeta
    assert usuario.fecha_ingreso is not None


def test_la_persona_importada_puede_activar_con_su_codigo(client):
    datos = subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar").json()
    fila = datos["filas"][0]

    r = client.post("/api/auth/activar", json={
        "identificador": fila["numero_empleado"], "codigo": fila["codigo"],
        "password": "MiClaveDePlanta1"})

    assert r.status_code == 200


def test_el_modo_verificacion_no_genera_codigos(client):
    """Lo que hace viable cargar 300: no hay nada que repartir."""
    datos = subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
                  modo_activacion="verificacion").json()

    assert datos["importadas"] == 3
    assert all(f["codigo"] is None for f in datos["filas"])


def test_con_verificacion_se_activa_con_la_fecha(client):
    subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
          modo_activacion="verificacion")

    r = client.post("/api/auth/activar", json={
        "identificador": "30001", "fecha_ingreso": "2021-03-15",
        "password": "MiClaveDePlanta1"})
    assert r.status_code == 200


def test_verificacion_exige_fecha_en_todas_las_filas(client, db_session):
    """Si falta una fecha, no se importa nada: quedaría gente sin poder entrar."""
    csv_incompleto = ("numero_empleado,nombre,fecha_ingreso\n"
                      "30040,Con Fecha,2021-01-01\n"
                      "30041,Sin Fecha,\n")

    datos = subir(client, csv_incompleto, ruta="/api/admin/importacion/importar",
                  modo_activacion="verificacion").json()

    assert datos["importadas"] == 0
    assert "fecha de ingreso" in datos["error"]
    assert db_session.query(Usuario).filter(Usuario.numero_empleado == "30040").first() is None


def test_las_filas_con_error_no_frenan_a_las_buenas(client, db_session):
    csv_mixto = ("numero_empleado,nombre\n"
                 "30050,Persona Buena\n"
                 ",Sin Numero\n"
                 "30051,Otra Buena\n")

    datos = subir(client, csv_mixto, ruta="/api/admin/importacion/importar").json()

    assert datos["importadas"] == 2
    assert datos["con_error"] == 1
    assert db_session.query(Usuario).filter(Usuario.numero_empleado == "30050").first() is not None


def test_un_modo_inventado_se_rechaza(client):
    r = subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
              modo_activacion="magia")
    assert r.status_code == 422


def test_solo_ti_importa(client):
    r = client.post("/api/admin/importacion/analizar",
                    files={"archivo": ("p.csv", io.BytesIO(CSV_BUENO.encode()), "text/csv")},
                    headers=cab(client, "user@test.com"))
    assert r.status_code == 403


def test_la_plantilla_trae_los_encabezados_correctos(client):
    r = client.get("/api/admin/importacion/plantilla", headers=cab(client))

    assert r.status_code == 200
    texto = r.content.decode()
    for columna in ("numero_empleado", "nombre", "area", "email", "fecha_ingreso"):
        assert columna in texto


def test_el_csv_de_codigos_solo_trae_los_que_tienen(client):
    from app.services.importacion_service import ImportacionService

    filas = [
        {"numero_empleado": "1", "nombre": "Con", "area": "A", "codigo": "AAAA-BBBB"},
        {"numero_empleado": "2", "nombre": "Sin", "area": "B", "codigo": None},
    ]
    csv_salida = ImportacionService.csv_de_codigos(filas)

    assert "AAAA-BBBB" in csv_salida
    assert csv_salida.count("\n") == 2  # encabezado + una fila
