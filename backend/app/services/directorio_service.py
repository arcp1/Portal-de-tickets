"""El directorio de documentos: qué se acepta, quién ve qué y la papelera.

Las rutas viven en `api/directorio.py`; aquí están las tres decisiones que no
dependen de HTTP y que conviene poder probar sueltas.

**Qué se acepta.** PDF, Office (el de ahora y el de antes, y OpenDocument),
imágenes, CSV, TXT y ZIP. **Nunca** ejecutables, scripts ni HTML (tampoco
SVG, que es HTML con otro nombre: lleva `<script>`). El tipo lo decide la
extensión y lo confirman los primeros bytes; lo que declara el navegador no
cuenta —lo escribe quien sube—. Y como un documento de Office puede llevar
macros y un ZIP puede llevar cualquier cosa, se mira dentro:

  * Office con macros (`vbaProject.bin`, la carpeta `Basic/` de
    OpenDocument, el `_VBA_PROJECT` de un .doc o .xls de antes): fuera. Un
    formato con macros ya tiene su propia extensión (.docm, .xlsm) y esa
    tampoco entra.
  * Un ZIP con un ejecutable, un script, una página o **otro comprimido**
    dentro: fuera. Lo de otro comprimido es para que no se pueda esconder un
    .exe un nivel más abajo, donde ya no se mira.

**Quién ve qué.** TI ve todo. La planta ve las carpetas cuya raíz dice
`todos`, o `plantas` con alguna de las suyas; nada de lo que dice `ti`. Lo
que no se alcanza no existe: 404, nunca 403.

**La papelera.** Borrar marca `eliminado_en` en lo que se borró, no en todo
su subárbol: lo de debajo desaparece porque un antepasado está en la
papelera, y restaurar la carpeta devuelve todo tal como estaba. A los
`DIRECTORIO_PAPELERA_DIAS` el worker lo borra de verdad, con sus binarios.
"""

import hashlib
import io
import re
import unicodedata
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import Archivo, ArchivoVersion, Carpeta, Usuario, carpeta_plantas

#: extensión → (tipo MIME con que se sirve, familia para comprobar el contenido)
TIPOS: Dict[str, tuple] = {
    ".pdf": ("application/pdf", "pdf"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "ooxml"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "ooxml"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "ooxml"),
    ".doc": ("application/msword", "ole"),
    ".xls": ("application/vnd.ms-excel", "ole"),
    ".ppt": ("application/vnd.ms-powerpoint", "ole"),
    ".odt": ("application/vnd.oasis.opendocument.text", "odf"),
    ".ods": ("application/vnd.oasis.opendocument.spreadsheet", "odf"),
    ".odp": ("application/vnd.oasis.opendocument.presentation", "odf"),
    ".jpg": ("image/jpeg", "jpeg"),
    ".jpeg": ("image/jpeg", "jpeg"),
    ".png": ("image/png", "png"),
    ".webp": ("image/webp", "webp"),
    ".gif": ("image/gif", "gif"),
    ".csv": ("text/csv", "texto"),
    ".txt": ("text/plain", "texto"),
    ".zip": ("application/zip", "zip"),
}

#: Lo que se puede ver en el navegador sin descargarlo. El resto sale como
#: `attachment` siempre.
EN_LINEA = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"}

#: Lo que no puede venir dentro de un ZIP. Ejecutables y bibliotecas de
#: Windows, Mac y Linux; scripts de cualquier intérprete; páginas y lo que el
#: navegador ejecuta; accesos directos; y otros comprimidos (ver arriba).
PROHIBIDAS_EN_ZIP = {
    ".exe", ".dll", ".com", ".scr", ".msi", ".msp", ".msc", ".cpl", ".sys", ".drv", ".ocx",
    ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse", ".mjs", ".wsf",
    ".wsh", ".hta", ".jar", ".class", ".py", ".pyc", ".pyw", ".pl", ".rb", ".php", ".sh",
    ".bash", ".zsh", ".csh", ".ksh", ".command", ".app", ".dmg", ".pkg", ".deb", ".rpm",
    ".apk", ".appimage", ".elf", ".bin", ".run", ".so", ".dylib", ".lnk", ".url", ".reg",
    ".inf", ".scf", ".gadget", ".application", ".appx", ".msix", ".iso", ".img", ".vhd",
    ".html", ".htm", ".xhtml", ".shtml", ".mht", ".mhtml", ".svg", ".svgz", ".xsl", ".xslt",
    ".swf", ".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".pptm", ".potm", ".ppam", ".ppsm",
    ".sldm", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".cab", ".arj",
    ".lzh", ".z",
}

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# Un documento de Office dentro de un ZIP se abre para buscarle macros, en
# memoria. Más grande que esto no se revisa y no entra.
_OFFICE_EN_ZIP_MAX = 60 * 1024 * 1024
_MACROS = "El documento lleva macros. Guárdelo sin macros y vuelva a subirlo."
# Los nombres de los flujos de un archivo OLE van en UTF-16: así se escribe
# el proyecto de macros de un .doc, .xls o .ppt de antes.
_VBA_OLE = "_VBA_PROJECT".encode("utf-16-le")
_TROZO = 1024 * 1024
_PROHIBIDOS_EN_NOMBRE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


class ArchivoRechazado(ValueError):
    """El archivo no entra. El mensaje es para la persona que lo subió."""


# ----------------------------------------------------------------------
# Nombres
# ----------------------------------------------------------------------

def nombre_limpio(nombre: Optional[str], maximo: int) -> str:
    """Un nombre que se puede guardar y mostrar: sin rutas, sin caracteres de
    control ni de los que Windows no deja usar, sin espacios a los lados.

    Lanza `ArchivoRechazado` si no queda nada usable.
    """
    nombre = unicodedata.normalize("NFC", nombre or "")
    # Algunos navegadores viejos mandan la ruta completa del equipo.
    nombre = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    nombre = _PROHIBIDOS_EN_NOMBRE.sub("", nombre).strip().strip(".").strip()
    if not nombre:
        raise ArchivoRechazado("El nombre está vacío o no tiene caracteres válidos.")
    if len(nombre) > maximo:
        raise ArchivoRechazado(f"El nombre no puede pasar de {maximo} caracteres.")
    return nombre


def extension(nombre: str) -> str:
    """La última extensión, en minúsculas. `factura.pdf.exe` es `.exe`."""
    punto = nombre.rfind(".")
    return nombre[punto:].lower() if punto > 0 else ""


def tipo_de(nombre: str) -> tuple:
    """(tipo MIME, familia) según la extensión, o `ArchivoRechazado`."""
    ext = extension(nombre)
    if ext not in TIPOS:
        raise ArchivoRechazado(
            "Tipo de archivo no permitido. Se aceptan PDF, Office, imágenes, CSV, TXT y ZIP; "
            "nunca ejecutables, scripts ni páginas web.")
    return TIPOS[ext]


# ----------------------------------------------------------------------
# Contenido
# ----------------------------------------------------------------------

def _primeros(ruta: Path, n: int = 8192) -> bytes:
    with ruta.open("rb") as f:
        return f.read(n)


def _contiene(ruta: Path, aguja: bytes) -> bool:
    """Si la secuencia aparece en el archivo, leyéndolo por trozos y sin
    perderla si cae justo en el borde entre dos."""
    cola = b""
    with ruta.open("rb") as f:
        while True:
            trozo = f.read(_TROZO)
            if not trozo:
                return False
            if aguja in cola + trozo:
                return True
            cola = trozo[-(len(aguja) - 1):]


def _abrir_zip(ruta: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(ruta)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchivoRechazado("El archivo está dañado o no es lo que dice su extensión.") from exc


def comprobar(ruta: Path, familia: str) -> None:
    """Que el archivo guardado en `ruta` sea de verdad de su familia y no lleve
    nada ejecutable dentro. Lanza `ArchivoRechazado` si no."""
    cabeza = _primeros(ruta)
    if not cabeza:
        raise ArchivoRechazado("El archivo está vacío.")
    falso = ArchivoRechazado("El contenido del archivo no corresponde a su extensión.")

    if familia == "pdf":
        if b"%PDF-" not in cabeza[:1024]:
            raise falso
    elif familia == "jpeg":
        if not cabeza.startswith(b"\xff\xd8\xff"):
            raise falso
    elif familia == "png":
        if not cabeza.startswith(b"\x89PNG\r\n\x1a\n"):
            raise falso
    elif familia == "webp":
        if not (cabeza[:4] == b"RIFF" and cabeza[8:12] == b"WEBP"):
            raise falso
    elif familia == "gif":
        if cabeza[:6] not in (b"GIF87a", b"GIF89a"):
            raise falso
    elif familia == "texto":
        # Un binario casi siempre lleva bytes nulos; un texto, nunca. Se mira
        # entero, no solo el principio: un ejecutable con 8 KB de texto
        # delante no es un TXT.
        if _contiene(ruta, b"\x00"):
            raise falso
        # Una página con extensión .txt se serviría como texto, pero si
        # alguien la guarda y la abre, es una página.
        inicio = cabeza.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
        if inicio.startswith((b"<!doctype html", b"<html", b"<script", b"<svg", b"<?xml")):
            raise ArchivoRechazado("Las páginas web no se aceptan, tampoco con otra extensión.")
    elif familia == "ole":
        if not cabeza.startswith(_OLE):
            raise falso
        if _contiene(ruta, _VBA_OLE):
            raise ArchivoRechazado(_MACROS)
    elif familia in ("ooxml", "odf", "zip"):
        if not cabeza.startswith(b"PK\x03\x04"):
            raise falso
        with _abrir_zip(ruta) as z:
            nombres = z.namelist()
        bajos = [n.lower() for n in nombres]
        if familia == "ooxml":
            if "[content_types].xml" not in bajos:
                raise falso
            if any(n.endswith("vbaproject.bin") for n in bajos):
                raise ArchivoRechazado(_MACROS)
        elif familia == "odf":
            if "mimetype" not in bajos:
                raise falso
            if any(n.startswith(("basic/", "scripts/")) for n in bajos):
                raise ArchivoRechazado(_MACROS)
        else:
            with _abrir_zip(ruta) as z:
                for info in z.infolist():
                    n = info.filename
                    if n.endswith("/"):
                        continue
                    ext = extension(n.rsplit("/", 1)[-1])
                    if ext in PROHIBIDAS_EN_ZIP:
                        raise ArchivoRechazado(
                            f"El ZIP contiene «{n[-80:]}», que no se admite: ni ejecutables, ni "
                            "scripts, ni páginas web, ni otros comprimidos.")
                    if TIPOS.get(ext, (None, None))[1] in ("ole", "ooxml", "odf"):
                        _office_en_zip(z, info, TIPOS[ext][1])
    else:  # pragma: no cover - una familia nueva sin comprobación es un error de programación
        raise falso


def _office_en_zip(z: zipfile.ZipFile, info: zipfile.ZipInfo, familia: str) -> None:
    """Un .doc, .xlsx u .odt dentro de un ZIP: el mismo examen de macros que
    si se hubiera subido suelto. Sin esto, meterlo en un ZIP era la manera de
    saltarse la regla."""
    if info.file_size > _OFFICE_EN_ZIP_MAX:
        raise ArchivoRechazado(
            f"El ZIP contiene «{info.filename[-80:]}», demasiado grande para revisarlo. "
            "Súbalo por separado.")
    datos = z.read(info)
    nombre = info.filename[-80:]
    if familia == "ole":
        if datos.startswith(_OLE) and _VBA_OLE in datos:
            raise ArchivoRechazado(f"«{nombre}», dentro del ZIP, lleva macros.")
        return
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as interno:
            bajos = [n.lower() for n in interno.namelist()]
    except zipfile.BadZipFile:
        raise ArchivoRechazado(f"«{nombre}», dentro del ZIP, está dañado.")
    if familia == "ooxml" and any(n.endswith("vbaproject.bin") for n in bajos):
        raise ArchivoRechazado(f"«{nombre}», dentro del ZIP, lleva macros.")
    if familia == "odf" and any(n.startswith(("basic/", "scripts/")) for n in bajos):
        raise ArchivoRechazado(f"«{nombre}», dentro del ZIP, lleva macros.")


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for trozo in iter(lambda: f.read(_TROZO), b""):
            h.update(trozo)
    return h.hexdigest()


def carpeta_en_disco() -> Path:
    ruta = Path(settings.DOCUMENTOS_RUTA) / "directorio"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


# ----------------------------------------------------------------------
# Árbol y visibilidad
# ----------------------------------------------------------------------

def ids_de_ruta(ruta: str) -> List[int]:
    """`/1/7/12/` → [1, 7, 12]: la raíz primero, la carpeta al final."""
    return [int(x) for x in ruta.strip("/").split("/") if x]


def raices_visibles(db: Session, usuario: Usuario) -> Optional[Set[int]]:
    """Las carpetas de primer nivel que esta persona alcanza, o `None` si
    todas (TI)."""
    if usuario.rol == "admin":
        return None
    suyas = usuario.plantas_ids or set()
    visibles = set()
    raices = (db.query(Carpeta.id, Carpeta.visibilidad)
              .filter(Carpeta.padre_id.is_(None)).all())
    con_plantas = [i for i, v in raices if v == "plantas"]
    plantas_de: Dict[int, Set[int]] = {}
    if con_plantas and suyas:
        for cid, sid in (db.query(carpeta_plantas.c.carpeta_id, carpeta_plantas.c.sitio_id)
                         .filter(carpeta_plantas.c.carpeta_id.in_(con_plantas)).all()):
            plantas_de.setdefault(cid, set()).add(sid)
    for i, v in raices:
        if v == "todos" or (v == "plantas" and plantas_de.get(i, set()) & suyas):
            visibles.add(i)
    return visibles


def eliminadas(db: Session, ids: Iterable[int]) -> Set[int]:
    """De esos ids de carpeta, los que están en la papelera."""
    ids = list(ids)
    if not ids:
        return set()
    return {i for (i,) in db.query(Carpeta.id).filter(
        Carpeta.id.in_(ids), Carpeta.eliminado_en.isnot(None)).all()}


def alcanzable(db: Session, usuario: Usuario, carpeta: Optional[Carpeta],
               raices: Optional[Set[int]] = None, con_papelera: bool = False) -> bool:
    """Si la persona puede abrir esa carpeta: existe, ni ella ni nada por
    encima está en la papelera, y su raíz le es visible.

    `con_papelera` deja pasar la carpeta misma aunque esté en la papelera (no
    sus antepasados): es lo que se pide para restaurarla.
    """
    if carpeta is None:
        return False
    if carpeta.eliminado_en is not None and not con_papelera:
        return False
    cadena = ids_de_ruta(carpeta.ruta)
    if eliminadas(db, cadena[:-1]):
        return False
    if raices is None:
        raices = raices_visibles(db, usuario)
    return raices is None or cadena[0] in raices


def vivas_alcanzables(db: Session, usuario: Usuario) -> List[Carpeta]:
    """Todas las carpetas que la persona puede abrir. Para el árbol y la
    búsqueda: son pocas (cientos), y resolverlo en Python es más claro que
    una consulta recursiva."""
    raices = raices_visibles(db, usuario)
    todas = db.query(Carpeta).filter(Carpeta.eliminado_en.is_(None)).all()
    vivas = {c.id for c in todas}
    salida = []
    for c in todas:
        cadena = ids_de_ruta(c.ruta)
        if not all(i in vivas for i in cadena):
            continue
        if raices is not None and cadena[0] not in raices:
            continue
        salida.append(c)
    return salida


# ----------------------------------------------------------------------
# Versiones
# ----------------------------------------------------------------------

def recortar_versiones(db: Session, archivo: Archivo) -> List[str]:
    """Deja `DIRECTORIO_MAX_VERSIONES - 1` versiones anteriores (con la
    vigente, el máximo) y devuelve los binarios que sobran, para borrarlos
    después del commit."""
    anteriores = (db.query(ArchivoVersion).filter(ArchivoVersion.archivo_id == archivo.id)
                  .order_by(ArchivoVersion.version.desc()).all())
    sobran = anteriores[max(0, settings.DIRECTORIO_MAX_VERSIONES - 1):]
    for v in sobran:
        db.delete(v)
    return [v.nombre_guardado for v in sobran]


def borrar_binarios(nombres: Iterable[str]) -> None:
    """Después del commit, nunca antes: si el commit falla, un binario de más
    es un huérfano; uno de menos es un archivo roto."""
    base = carpeta_en_disco()
    for nombre in nombres:
        try:
            (base / nombre).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("No se pudo borrar un binario del directorio",
                           extra={"archivo": nombre, "error": str(exc)})


# ----------------------------------------------------------------------
# Papelera
# ----------------------------------------------------------------------

def purgar(db: Session, ahora: Optional[datetime] = None) -> int:
    """Borra de verdad lo que lleva más de `DIRECTORIO_PAPELERA_DIAS` en la
    papelera: archivos sueltos y carpetas con todo su subárbol. Devuelve
    cuántos archivos borró (contando los de dentro de las carpetas)."""
    limite = (ahora or datetime.utcnow()) - timedelta(days=settings.DIRECTORIO_PAPELERA_DIAS)
    binarios: List[str] = []
    archivos_borrados = 0

    def borrar_archivo(a: Archivo) -> None:
        nonlocal archivos_borrados
        binarios.append(a.nombre_guardado)
        binarios.extend(v.nombre_guardado for v in a.versiones)
        db.delete(a)
        archivos_borrados += 1

    for a in db.query(Archivo).filter(Archivo.eliminado_en.isnot(None),
                                      Archivo.eliminado_en < limite).all():
        borrar_archivo(a)
    db.flush()

    viejas = (db.query(Carpeta).filter(Carpeta.eliminado_en.isnot(None),
                                       Carpeta.eliminado_en < limite)
              .order_by(Carpeta.profundidad).all())
    hechas: Set[int] = set()
    for carpeta in viejas:
        if carpeta.id in hechas:
            continue  # ya cayó con una carpeta de más arriba
        subarbol = (db.query(Carpeta).filter(Carpeta.ruta.like(carpeta.ruta + "%"))
                    .order_by(Carpeta.profundidad.desc()).all())
        ids = [c.id for c in subarbol]
        for a in db.query(Archivo).filter(Archivo.carpeta_id.in_(ids)).all():
            borrar_archivo(a)
        db.flush()
        for c in subarbol:
            db.delete(c)
            db.flush()
            hechas.add(c.id)

    db.commit()
    borrar_binarios(binarios)
    return archivos_borrados
