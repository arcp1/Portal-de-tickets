"""Directorio de documentos: quién ve qué, qué entra y qué pasa al borrar.

Lo que se fija aquí, por orden de gravedad:

  * **La visibilidad no se cruza.** Una carpeta «solo TI» o de otra planta no
    existe para la planta: 404 al abrirla, ausente del árbol, de la raíz y de
    la búsqueda. Y lo de dentro hereda lo de la raíz.
  * **Nada ejecutable entra**, tampoco disfrazado: un .exe renombrado, una
    página con extensión .txt, un ZIP con un .exe o con otro ZIP dentro, un
    Word con macros —suelto o metido en un ZIP—.
  * **La papelera esconde todo el subárbol y lo devuelve igual**, y a los 30
    días se borra de verdad, binarios incluidos.
  * **Diez versiones como mucho**, y los binarios que sobran se borran.
"""

import io
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.models import Archivo, ArchivoVersion, Auditoria, Carpeta, Usuario
from app.services import directorio_service as srv

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def cab(client, identificador="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": identificador, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def carpeta(client, nombre="Manuales", **extra):
    r = client.post("/api/directorio/carpetas", json={"nombre": nombre, **extra}, headers=cab(client))
    assert r.status_code == 201, r.text
    return r.json()


def subir(client, carpeta_id, *archivos, quien="admin@test.com"):
    return client.post(f"/api/directorio/carpetas/{carpeta_id}/archivos",
                       files=[("archivos", (n, c, "application/octet-stream")) for n, c in archivos],
                       headers=cab(client, quien))


def zip_con(**miembros) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as z:
        for nombre, contenido in miembros.items():
            z.writestr(nombre.replace("__", "/"), contenido)
    return salida.getvalue()


def docx(macros=False) -> bytes:
    miembros = {"[Content_Types].xml": "<Types/>", "word__document.xml": "<w:document/>"}
    if macros:
        miembros["word__vbaProject.bin"] = b"\x00VBA"
    return zip_con(**miembros)


def en_disco(nombre_guardado) -> Path:
    return Path(settings.DOCUMENTOS_RUTA) / "directorio" / nombre_guardado


# ----------------------------------------------------------------------
# Quién escribe
# ----------------------------------------------------------------------

def test_la_planta_no_escribe(client):
    c = carpeta(client, visibilidad="todos")
    usuario = cab(client, "user@test.com")
    assert client.post("/api/directorio/carpetas", json={"nombre": "X"}, headers=usuario).status_code == 403
    assert client.patch(f"/api/directorio/carpetas/{c['id']}", json={"nombre": "Y"},
                        headers=usuario).status_code == 403
    assert client.delete(f"/api/directorio/carpetas/{c['id']}", headers=usuario).status_code == 403
    assert subir(client, c["id"], ("a.pdf", PDF), quien="user@test.com").status_code == 403
    assert client.get("/api/directorio/papelera", headers=usuario).status_code == 403


# ----------------------------------------------------------------------
# Visibilidad
# ----------------------------------------------------------------------

def test_una_raiz_nueva_es_solo_de_ti(client):
    c = carpeta(client)
    assert c["visibilidad"] == "ti"
    usuario = cab(client, "user@test.com")
    assert client.get(f"/api/directorio/carpetas/{c['id']}", headers=usuario).status_code == 404
    assert client.get("/api/directorio/raiz", headers=usuario).json()["carpetas"] == []


def test_todos_ve_la_carpeta_y_lo_de_dentro(client):
    raiz = carpeta(client, "Formatos", visibilidad="todos")
    hija = carpeta(client, "Compras", padre_id=raiz["id"])
    assert hija["visibilidad"] is None
    subir(client, hija["id"], ("orden.pdf", PDF))
    usuario = cab(client, "user@test.com")
    r = client.get(f"/api/directorio/carpetas/{hija['id']}", headers=usuario)
    assert r.status_code == 200
    datos = r.json()
    assert datos["carpeta"]["visibilidad_efectiva"] == "todos"
    assert [m["nombre"] for m in datos["migas"]] == ["Formatos", "Compras"]
    assert [a["nombre"] for a in datos["archivos"]] == ["orden.pdf"]
    assert datos["puede_editar"] is False
    # La planta no ve a qué plantas está abierta una carpeta.
    assert "plantas" not in datos["carpeta"]


def test_plantas_solo_las_suyas(client, db_session, otra_planta):
    qro = db_session.query(Usuario).filter_by(email="user@test.com").one().sitio_id
    de_mty = carpeta(client, "Monterrey", visibilidad="plantas", sitio_ids=[otra_planta.id])
    de_qro = carpeta(client, "Querétaro", visibilidad="plantas", sitio_ids=[qro])
    hija_mty = carpeta(client, "Planos", padre_id=de_mty["id"])
    subir(client, hija_mty["id"], ("plano.pdf", PDF))
    usuario = cab(client, "user@test.com")

    raiz = client.get("/api/directorio/raiz", headers=usuario).json()
    assert [c["nombre"] for c in raiz["carpetas"]] == ["Querétaro"]
    assert client.get(f"/api/directorio/carpetas/{de_qro['id']}", headers=usuario).status_code == 200
    for cid in (de_mty["id"], hija_mty["id"]):
        assert client.get(f"/api/directorio/carpetas/{cid}", headers=usuario).status_code == 404
    arbol = client.get("/api/directorio/arbol", headers=usuario).json()
    assert {c["id"] for c in arbol} == {de_qro["id"]}
    busqueda = client.get("/api/directorio/buscar", params={"q": "plano"}, headers=usuario).json()
    assert busqueda == {"carpetas": [], "archivos": []}
    archivo = db_session.query(Archivo).filter_by(nombre="plano.pdf").one()
    assert client.get(f"/api/directorio/archivos/{archivo.id}/descarga", headers=usuario).status_code == 404
    assert client.get(f"/api/directorio/archivos/{archivo.id}/versiones", headers=usuario).status_code == 404


def test_plantas_exige_alguna(client):
    r = client.post("/api/directorio/carpetas", json={"nombre": "X", "visibilidad": "plantas"},
                    headers=cab(client))
    assert r.status_code == 422


def test_la_visibilidad_solo_va_en_la_raiz(client):
    raiz = carpeta(client, visibilidad="todos")
    r = client.post("/api/directorio/carpetas",
                    json={"nombre": "Hija", "padre_id": raiz["id"], "visibilidad": "ti"}, headers=cab(client))
    assert r.status_code == 422
    hija = carpeta(client, "Hija", padre_id=raiz["id"])
    r = client.patch(f"/api/directorio/carpetas/{hija['id']}", json={"visibilidad": "todos"},
                     headers=cab(client))
    assert r.status_code == 422


# ----------------------------------------------------------------------
# Qué entra
# ----------------------------------------------------------------------

def test_sube_varios_y_rechaza_los_que_no_entran(client):
    c = carpeta(client)
    r = subir(client, c["id"],
              ("manual.pdf", PDF),
              ("lista.csv", b"equipo,serie\nHP,123\n"),
              ("virus.exe", b"MZ\x90\x00"),
              ("pagina.html", b"<html></html>"),
              ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"))
    assert r.status_code == 201, r.text
    datos = r.json()
    assert sorted(a["nombre"] for a in datos["subidos"]) == ["lista.csv", "manual.pdf"]
    assert sorted(x["nombre"] for x in datos["rechazados"]) == ["logo.svg", "pagina.html", "virus.exe"]


@pytest.mark.parametrize("nombre,contenido", [
    ("factura.pdf", b"MZ\x90\x00\x03"),                       # un .exe renombrado
    ("notas.txt", b"MZ\x90\x00\x03\x00\x00\x00"),              # binario como texto
    ("notas.txt", b"<!DOCTYPE html><script>alert(1)</script>"),
    ("foto.png", b"<html></html>"),
    ("hoja.xlsx", b"PK\x03\x04no es un zip"),
    ("paquete.zip", zip_con(**{"leeme.txt": "hola", "instalar.exe": b"MZ"})),
    ("paquete.zip", zip_con(**{"otro.zip": zip_con(**{"a.exe": b"MZ"})})),
    ("paquete.zip", zip_con(**{"carpeta__script.ps1": "Remove-Item"})),
    ("paquete.zip", zip_con(**{"index.html": "<html></html>"})),
    ("informe.docx", docx(macros=True)),
    ("paquete.zip", zip_con(**{"informe.docx": docx(macros=True)})),
    ("viejo.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "_VBA_PROJECT".encode("utf-16-le")),
    ("informe.docm", docx()),
    ("vacio.pdf", b""),
])
def test_nada_ejecutable_entra(client, nombre, contenido):
    c = carpeta(client)
    r = subir(client, c["id"], (nombre, contenido))
    assert r.status_code == 422, (nombre, r.text)


@pytest.mark.parametrize("nombre,contenido", [
    ("informe.docx", docx()),
    ("paquete.zip", zip_con(**{"leeme.txt": "hola", "datos.csv": "a,b", "informe.docx": docx()})),
    ("viejo.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64),
    ("hoja.ods", zip_con(mimetype="application/vnd.oasis.opendocument.spreadsheet", **{"content.xml": "<x/>"})),
    ("notas.txt", "Configuración del switch: VLAN 20".encode("utf-8")),
])
def test_lo_legitimo_entra(client, nombre, contenido):
    c = carpeta(client)
    r = subir(client, c["id"], (nombre, contenido))
    assert r.status_code == 201, (nombre, r.text)


def test_el_tipo_lo_decide_el_portal(client, db_session):
    c = carpeta(client)
    client.post(f"/api/directorio/carpetas/{c['id']}/archivos",
                files=[("archivos", ("manual.pdf", PDF, "text/html"))], headers=cab(client))
    assert db_session.query(Archivo).one().tipo_mime == "application/pdf"


def test_una_foto_pierde_el_gps(client, db_session):
    exif = Image.Exif()
    exif[0x010F] = "CamaraSecreta"
    exif[0x8825] = {1: "N", 2: (20.0, 35.0, 12.0), 3: "W", 4: (100.0, 23.0, 1.0)}
    salida = io.BytesIO()
    Image.new("RGB", (16, 12), (200, 30, 30)).save(salida, "JPEG", exif=exif.tobytes())
    c = carpeta(client)
    assert subir(client, c["id"], ("equipo.jpg", salida.getvalue())).status_code == 201
    guardado = en_disco(db_session.query(Archivo).one().nombre_guardado).read_bytes()
    assert b"CamaraSecreta" not in guardado
    with Image.open(io.BytesIO(guardado)) as im:
        assert 0x8825 not in im.getexif()


def test_nombres_repetidos_sin_distinguir_mayusculas(client):
    c = carpeta(client)
    assert subir(client, c["id"], ("Manual.pdf", PDF)).status_code == 201
    r = subir(client, c["id"], ("MANUAL.PDF", PDF))
    assert r.status_code == 422
    assert "versión nueva" in r.json()["detail"]
    assert client.post("/api/directorio/carpetas", json={"nombre": "manuales"},
                       headers=cab(client)).status_code == 409


def test_nombre_sin_ruta_ni_caracteres_raros(client, db_session):
    c = carpeta(client)
    assert subir(client, c["id"], ("C:\\Users\\ana\\..\\informe<1>.pdf", PDF)).status_code == 201
    assert db_session.query(Archivo).one().nombre == "informe1.pdf"


def test_tope_por_subida(client, monkeypatch):
    monkeypatch.setattr(settings, "DIRECTORIO_MAX_MB", 1)
    c = carpeta(client)
    grande = b"%PDF-1.4\n" + b"0" * (1024 * 1024)
    r = subir(client, c["id"], ("grande.pdf", grande))
    assert r.status_code == 413
    # Lo que ya se había escrito de esa subida no se queda en el disco.
    assert not [p for p in (Path(settings.DOCUMENTOS_RUTA) / "directorio").iterdir()]


# ----------------------------------------------------------------------
# Descarga
# ----------------------------------------------------------------------

def test_pdf_en_linea_y_lo_demas_como_descarga(client, db_session):
    raiz = carpeta(client, visibilidad="todos")
    subir(client, raiz["id"], ("manual.pdf", PDF), ("lista.csv", b"a,b\n"))
    usuario = cab(client, "user@test.com")
    pdf = db_session.query(Archivo).filter_by(nombre="manual.pdf").one()
    csv = db_session.query(Archivo).filter_by(nombre="lista.csv").one()

    r = client.get(f"/api/directorio/archivos/{pdf.id}/descarga", headers=usuario)
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    r = client.get(f"/api/directorio/archivos/{pdf.id}/descarga", params={"descargar": True}, headers=usuario)
    assert r.headers["content-disposition"].startswith("attachment")
    r = client.get(f"/api/directorio/archivos/{csv.id}/descarga", headers=usuario)
    assert r.headers["content-disposition"].startswith("attachment")


# ----------------------------------------------------------------------
# Versiones
# ----------------------------------------------------------------------

def _version(client, archivo_id, nombre, contenido):
    return client.put(f"/api/directorio/archivos/{archivo_id}/contenido",
                      files={"archivo": (nombre, contenido, "application/pdf")}, headers=cab(client))


def test_version_nueva_y_su_historial(client, db_session):
    c = carpeta(client)
    a = subir(client, c["id"], ("manual.pdf", PDF)).json()["subidos"][0]
    assert _version(client, a["id"], "manual.pdf", PDF).status_code == 409   # idéntico
    assert _version(client, a["id"], "manual.docx", docx()).status_code == 422  # otro tipo
    r = _version(client, a["id"], "manual-v2.pdf", PDF + b"% v2\n")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and r.json()["nombre"] == "manual.pdf"
    historial = client.get(f"/api/directorio/archivos/{a['id']}/versiones", headers=cab(client)).json()
    assert [(v["version"], v["vigente"]) for v in historial] == [(2, True), (1, False)]
    vieja = client.get(f"/api/directorio/archivos/{a['id']}/versiones/1", headers=cab(client))
    assert vieja.content == PDF
    assert "manual%20%28v1%29.pdf" in vieja.headers["content-disposition"]


def test_se_guardan_diez_versiones(client, db_session):
    c = carpeta(client)
    a = subir(client, c["id"], ("manual.pdf", PDF)).json()["subidos"][0]
    primera = db_session.get(Archivo, a["id"]).nombre_guardado
    for n in range(2, 13):
        assert _version(client, a["id"], "manual.pdf", PDF + f"% v{n}\n".encode()).status_code == 200
    db_session.expire_all()
    archivo = db_session.get(Archivo, a["id"])
    assert archivo.version == 12
    versiones = sorted(v.version for v in db_session.query(ArchivoVersion).filter_by(archivo_id=a["id"]))
    assert versiones == list(range(3, 12))          # nueve anteriores + la vigente = diez
    assert not en_disco(primera).exists()


# ----------------------------------------------------------------------
# Mover
# ----------------------------------------------------------------------

def test_mover_reescribe_la_ruta_del_subarbol(client, db_session):
    a = carpeta(client, "A", visibilidad="todos")
    b = carpeta(client, "B", visibilidad="ti")
    a1 = carpeta(client, "A1", padre_id=a["id"])
    a11 = carpeta(client, "A11", padre_id=a1["id"])
    r = client.patch(f"/api/directorio/carpetas/{a1['id']}", json={"padre_id": b["id"]}, headers=cab(client))
    assert r.status_code == 200, r.text
    db_session.expire_all()
    nieta = db_session.get(Carpeta, a11["id"])
    assert nieta.ruta == f"/{b['id']}/{a1['id']}/{a11['id']}/"
    assert nieta.profundidad == 3
    # Ahora hereda «solo TI»: la planta ya no la ve.
    assert client.get(f"/api/directorio/carpetas/{a11['id']}",
                      headers=cab(client, "user@test.com")).status_code == 404
    accion = db_session.query(Auditoria).filter_by(accion="carpeta.movida").one()
    assert accion.entidad_id == a1["id"]


def test_mover_al_primer_nivel_la_deja_solo_para_ti(client, db_session):
    a = carpeta(client, "A", visibilidad="todos")
    hija = carpeta(client, "Hija", padre_id=a["id"])
    r = client.patch(f"/api/directorio/carpetas/{hija['id']}", json={"padre_id": None}, headers=cab(client))
    assert r.status_code == 200, r.text
    assert r.json()["visibilidad"] == "ti" and r.json()["profundidad"] == 1


def test_no_se_mueve_dentro_de_si_misma(client):
    a = carpeta(client, "A")
    a1 = carpeta(client, "A1", padre_id=a["id"])
    for destino in (a["id"], a1["id"]):
        r = client.patch(f"/api/directorio/carpetas/{a['id']}", json={"padre_id": destino}, headers=cab(client))
        assert r.status_code == 409, destino


def test_ocho_niveles_como_mucho(client):
    padre = carpeta(client, "N1")
    for n in range(2, 9):
        padre = carpeta(client, f"N{n}", padre_id=padre["id"])
    r = client.post("/api/directorio/carpetas", json={"nombre": "N9", "padre_id": padre["id"]},
                    headers=cab(client))
    assert r.status_code == 422


def test_renombrar_conserva_la_extension(client):
    c = carpeta(client)
    a = subir(client, c["id"], ("notas.txt", b"hola")).json()["subidos"][0]
    r = client.patch(f"/api/directorio/archivos/{a['id']}", json={"nombre": "notas.html"}, headers=cab(client))
    assert r.status_code == 422
    r = client.patch(f"/api/directorio/archivos/{a['id']}", json={"nombre": "apuntes.txt"}, headers=cab(client))
    assert r.status_code == 200 and r.json()["nombre"] == "apuntes.txt"


# ----------------------------------------------------------------------
# Papelera
# ----------------------------------------------------------------------

def test_papelera_esconde_el_subarbol_y_lo_devuelve(client, db_session):
    raiz = carpeta(client, "Raíz", visibilidad="todos")
    hija = carpeta(client, "Hija", padre_id=raiz["id"])
    a = subir(client, hija["id"], ("manual.pdf", PDF)).json()["subidos"][0]
    assert client.delete(f"/api/directorio/carpetas/{raiz['id']}", headers=cab(client)).status_code == 200

    for quien in ("admin@test.com", "user@test.com"):
        assert client.get(f"/api/directorio/carpetas/{hija['id']}", headers=cab(client, quien)).status_code == 404
        assert client.get(f"/api/directorio/archivos/{a['id']}/descarga",
                          headers=cab(client, quien)).status_code == 404
    # El nombre queda libre mientras tanto.
    carpeta(client, "Raíz")
    papelera = client.get("/api/directorio/papelera", headers=cab(client)).json()
    assert [(p["tipo"], p["nombre"]) for p in papelera] == [("carpeta", "Raíz")]
    # Para restaurarla hace falta que el nombre vuelva a estar libre.
    r = client.post(f"/api/directorio/papelera/carpeta/{raiz['id']}/restaurar", headers=cab(client))
    assert r.status_code == 409


def test_restaurar(client):
    raiz = carpeta(client, "Raíz", visibilidad="todos")
    a = subir(client, raiz["id"], ("manual.pdf", PDF)).json()["subidos"][0]
    client.delete(f"/api/directorio/archivos/{a['id']}", headers=cab(client))
    client.delete(f"/api/directorio/carpetas/{raiz['id']}", headers=cab(client))
    # El archivo está dentro de una carpeta que también está en la papelera.
    r = client.post(f"/api/directorio/papelera/archivo/{a['id']}/restaurar", headers=cab(client))
    assert r.status_code == 409 and "Raíz" in r.json()["detail"]
    assert client.post(f"/api/directorio/papelera/carpeta/{raiz['id']}/restaurar",
                       headers=cab(client)).status_code == 200
    assert client.post(f"/api/directorio/papelera/archivo/{a['id']}/restaurar",
                       headers=cab(client)).status_code == 200
    r = client.get(f"/api/directorio/archivos/{a['id']}/descarga", headers=cab(client, "user@test.com"))
    assert r.status_code == 200


def test_la_purga_borra_de_verdad_a_los_treinta_dias(client, db_session):
    raiz = carpeta(client, "Raíz")
    hija = carpeta(client, "Hija", padre_id=raiz["id"])
    a = subir(client, hija["id"], ("manual.pdf", PDF)).json()["subidos"][0]
    _version(client, a["id"], "manual.pdf", PDF + b"% v2\n")
    suelto = subir(client, raiz["id"], ("suelto.pdf", PDF)).json()["subidos"][0]
    binarios = [r.nombre_guardado for r in db_session.query(Archivo)] + \
               [v.nombre_guardado for v in db_session.query(ArchivoVersion)]
    assert len(binarios) == 3 and all(en_disco(b).exists() for b in binarios)
    client.delete(f"/api/directorio/archivos/{suelto['id']}", headers=cab(client))
    client.delete(f"/api/directorio/carpetas/{raiz['id']}", headers=cab(client))

    assert srv.purgar(db_session, datetime.utcnow() + timedelta(days=29)) == 0
    assert db_session.query(Carpeta).count() == 2
    assert srv.purgar(db_session, datetime.utcnow() + timedelta(days=31)) == 2
    assert db_session.query(Carpeta).count() == 0
    assert db_session.query(Archivo).count() == 0
    assert db_session.query(ArchivoVersion).count() == 0
    assert not any(en_disco(b).exists() for b in binarios)


# ----------------------------------------------------------------------
# Bitácora
# ----------------------------------------------------------------------

def test_queda_en_la_bitacora(client, db_session):
    c = carpeta(client)
    a = subir(client, c["id"], ("manual.pdf", PDF)).json()["subidos"][0]
    _version(client, a["id"], "manual.pdf", PDF + b"% v2\n")
    client.delete(f"/api/directorio/archivos/{a['id']}", headers=cab(client))
    acciones = {x.accion for x in db_session.query(Auditoria)}
    assert {"carpeta.creada", "archivo.subido", "archivo.reemplazado", "archivo.eliminado"} <= acciones
