"""Importación masiva de personal desde CSV.

Con 300+ empleados, dar de alta uno por uno no es viable. Lo que se prueba aquí
es que el archivo de RH —con sus encabezados impredecibles y su codificación de
Excel— se convierta en cuentas sin dejar el padrón a medias.

El dato de verificación es la **fecha de nacimiento**: la de ingreso no sirve
porque buena parte de la plantilla no la recuerda.
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


CSV_BUENO = """numero_empleado,nombre,area,email,numero_epp,fecha_nacimiento,fecha_ingreso
30001,Juan Pérez Martínez,Producción,juan@test.com,0421,1978-04-23,2021-03-15
30002,María López Sánchez,Calidad,,1187,1985-12-09,2019-11-02
30003,Pedro Ramírez Cruz,Almacén,,3390,09/06/1966,15/07/2022
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
    csv_rh = ("No. Empleado;Nombre Completo;Departamento;Correo;Fec. Nac.\n"
              "30010;Ana Torres Gómez;Recursos Humanos;ana@test.com;01/05/1990\n")
    r = subir(client, csv_rh)

    assert r.status_code == 200
    datos = r.json()
    assert datos["validas"] == 1
    assert datos["columnas_detectadas"]["numero_empleado"] == "No. Empleado"
    assert datos["columnas_detectadas"]["fecha_nacimiento"] == "Fec. Nac."


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


def test_avisa_de_quien_no_podra_activarse_solo(client):
    """Sin fecha de nacimiento, esa persona necesita código o mostrador."""
    csv_sin = "numero_empleado,nombre\n30060,Sin Datos Persona\n"
    datos = subir(client, csv_sin).json()

    assert datos["sin_fecha_nacimiento"] == 1
    assert "activación asistida" in datos["filas"][0]["aviso"]


def test_rechaza_un_archivo_vacio(client):
    r = client.post("/api/admin/importacion/analizar",
                    files={"archivo": ("vacio.csv", io.BytesIO(b""), "text/csv")},
                    headers=cab(client))
    assert r.status_code == 422


# ----------------------------------------------------------------------
# Mapeo de columnas cuando el archivo viene raro
# ----------------------------------------------------------------------
def test_un_archivo_irreconocible_pide_mapeo_en_vez_de_rendirse(client, monkeypatch):
    """Encabezados que ningún diccionario de alias cubre. No es un callejón."""
    monkeypatch.setattr(settings, "IA_HABILITADA", False)
    datos = subir(client, "COL_A,COL_B,COL_C\n1,Fulano,X\n").json()

    assert datos["ok"] is False
    assert datos["necesita_mapeo"] is True
    assert datos["encabezados"] == ["COL_A", "COL_B", "COL_C"]
    assert "numero_empleado" in datos["campos"]


def test_el_mapeo_manual_manda_sobre_la_deteccion(client):
    """El admin dice qué columna es cuál y el archivo se importa igual."""
    crudo = "COL_A,COL_B,COL_C\n30070,Fulano De Tal,Producción\n"
    mapeo = '{"numero_empleado": "COL_A", "nombre": "COL_B", "area": "COL_C"}'

    datos = subir(client, crudo, mapeo=mapeo).json()

    assert datos["ok"] is True
    assert datos["validas"] == 1
    assert datos["filas"][0]["area"] == "Producción"


def test_sin_ollama_el_mapeo_sigue_siendo_posible(client, monkeypatch):
    """La IA propone; si no está, se mapea a mano. Nunca bloquea."""
    monkeypatch.setattr(settings, "IA_HABILITADA", False)
    datos = subir(client, "COL_A,COL_B\n1,Fulano\n").json()

    assert datos["necesita_mapeo"] is True
    assert datos["sugerencia"] is None


def test_el_parecido_de_palabras_no_necesita_a_ollama(monkeypatch):
    """La primera pasada del mapeo es determinista. Ollama solo completa."""
    from app.services.importacion_service import _mapeo_aproximado, COLUMNAS

    monkeypatch.setattr(settings, "IA_HABILITADA", False)
    propuesta = _mapeo_aproximado(
        ["CLAVE_TRAB", "NOMBRE DEL TRABAJADOR", "ADSCRIPCION", "F_NAC"],
        list(COLUMNAS),
    )

    assert propuesta["numero_empleado"] == "CLAVE_TRAB"
    assert propuesta["fecha_nacimiento"] == "F_NAC"
    assert propuesta["area"] == "ADSCRIPCION"


def test_dos_campos_no_se_pelean_por_la_misma_columna(monkeypatch):
    """Un encabezado se le asigna a un solo campo, al que mejor encaje."""
    from app.services.importacion_service import _mapeo_aproximado, COLUMNAS

    monkeypatch.setattr(settings, "IA_HABILITADA", False)
    propuesta = _mapeo_aproximado(
        ["FECHA_NACIMIENTO", "FECHA_INGRESO"], list(COLUMNAS))

    assert propuesta.get("fecha_nacimiento") == "FECHA_NACIMIENTO"
    assert propuesta.get("fecha_ingreso") == "FECHA_INGRESO"


def test_lo_que_el_modelo_invente_se_descarta(monkeypatch):
    """Un modelo chico copia encabezados del ejemplo. No deben pasar."""
    from app.services import importacion_service as imp

    monkeypatch.setattr(imp, "_mapeo_aproximado", lambda d, f: {})
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.responder_json",
        lambda *a, **k: {
            "numero_empleado": "NUM_EMP",       # del ejemplo, no del archivo
            "campo_inventado": "COL_A",         # no existe como campo
            "nombre": "COL_A",                  # este sí es válido
        },
    )
    propuesta = imp.sugerir_mapeo(["COL_A", "COL_B"], {})

    assert propuesta == {"nombre": "COL_A"}


def test_si_el_modelo_devuelve_basura_no_truena(monkeypatch):
    from app.services import importacion_service as imp

    monkeypatch.setattr(imp, "_mapeo_aproximado", lambda d, f: {})
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.responder_json", lambda *a, **k: "no soy un dict")

    assert imp.sugerir_mapeo(["COL_A"], {}) is None


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
    assert usuario.fecha_nacimiento is not None


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


def test_con_verificacion_se_activa_con_epp_y_cumpleanos(client):
    """Los dos datos que la gente sí recuerda, y hay que acertarlos los dos."""
    subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
          modo_activacion="verificacion")

    r = client.post("/api/auth/activar", json={
        "identificador": "30001", "numero_epp": "0421",
        "fecha_nacimiento": "1978-04-23", "password": "MiClaveDePlanta1"})
    assert r.status_code == 200


def test_importado_con_dos_factores_no_basta_uno(client):
    subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
          modo_activacion="verificacion")

    r = client.post("/api/auth/activar", json={
        "identificador": "30001", "fecha_nacimiento": "1978-04-23",
        "password": "MiClaveDePlanta1"})
    assert r.status_code == 400


def test_el_dato_elegido_es_el_que_se_exige_completo(client):
    """`dato_verificacion` dice qué columna no puede faltarle a ninguna fila."""
    csv_sin_epp = ("numero_empleado,nombre,fecha_nacimiento\n"
                   "30080,Con Cumpleanos,1990-01-01\n"
                   "30081,Sin Nada,\n")

    con_epp = subir(client, csv_sin_epp, ruta="/api/admin/importacion/importar",
                    modo_activacion="verificacion", dato_verificacion="numero_epp").json()
    assert con_epp["importadas"] == 0
    assert "número de EPP" in con_epp["error"]


def test_el_analisis_cuenta_a_quien_quedaria_con_un_solo_factor(client):
    """Es la lista de a quién hay que pedirle a RH el número de EPP."""
    csv_mixto = ("numero_empleado,nombre,numero_epp,fecha_nacimiento\n"
                 "30090,Con Los Dos,0421,1990-01-01\n"
                 "30091,Solo Cumpleanos,,1985-05-05\n")

    datos = subir(client, csv_mixto).json()

    assert datos["con_un_solo_factor"] == 1
    assert datos["sin_numero_epp"] == 1
    assert "un dato de verificación" in datos["filas"][1]["aviso"]


def test_una_fecha_de_nacimiento_equivocada_no_activa(client):
    subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
          modo_activacion="verificacion")

    r = client.post("/api/auth/activar", json={
        "identificador": "30001", "fecha_nacimiento": "1980-01-01",
        "password": "MiClaveDePlanta1"})
    assert r.status_code == 400


def test_verificacion_exige_la_fecha_en_todas_las_filas(client, db_session):
    """Si falta una, no se importa nada: quedaría gente sin poder entrar."""
    csv_incompleto = ("numero_empleado,nombre,fecha_nacimiento\n"
                      "30040,Con Fecha,1990-01-01\n"
                      "30041,Sin Fecha,\n")

    datos = subir(client, csv_incompleto, ruta="/api/admin/importacion/importar",
                  modo_activacion="verificacion").json()

    assert datos["importadas"] == 0
    assert "fecha de nacimiento" in datos["error"]
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


def test_un_dato_de_verificacion_inventado_se_rechaza(client):
    r = subir(client, CSV_BUENO, ruta="/api/admin/importacion/importar",
              modo_activacion="verificacion", dato_verificacion="curp")
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
    for columna in ("numero_empleado", "nombre", "area", "email",
                    "fecha_nacimiento", "fecha_ingreso"):
        assert columna in texto


# ----------------------------------------------------------------------
# Reparto de códigos
# ----------------------------------------------------------------------
def test_el_csv_de_codigos_solo_trae_los_que_tienen(client):
    from app.services.importacion_service import ImportacionService

    filas = [
        {"numero_empleado": "1", "nombre": "Con", "area": "A", "codigo": "AAAA-BBBB"},
        {"numero_empleado": "2", "nombre": "Sin", "area": "B", "codigo": None},
    ]
    csv_salida = ImportacionService.csv_de_codigos(filas)

    assert "AAAA-BBBB" in csv_salida
    assert csv_salida.count("\n") == 2  # encabezado + una fila


def test_los_codigos_se_pueden_repartir_por_area(client):
    """300 papelitos de TI se vuelven ~20 sobres, uno por supervisor."""
    from app.services.importacion_service import ImportacionService

    filas = [
        {"numero_empleado": "1", "nombre": "De Produccion", "area": "Producción",
         "codigo": "AAAA-BBBB"},
        {"numero_empleado": "2", "nombre": "De Calidad", "area": "Calidad",
         "codigo": "CCCC-DDDD"},
    ]
    solo_produccion = ImportacionService.csv_de_codigos(filas, area="producción")

    assert "AAAA-BBBB" in solo_produccion
    assert "CCCC-DDDD" not in solo_produccion
    assert ImportacionService.areas_de(filas) == ["Calidad", "Producción"]
