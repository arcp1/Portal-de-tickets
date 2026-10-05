"""Los Términos y Condiciones vigentes. Una sola fuente: `recursos/terminos.md`.

**Por qué un archivo y no texto en el frontend.** Lo que la persona acepta
tiene que ser exactamente lo que el servidor registra. Si el texto viviera en
la pantalla y la versión en el backend, bastaría con cambiar uno y olvidar el
otro para que alguien aceptara la versión 1.0 de un texto que ya no es el de la
1.0. Aquí el servidor sirve el texto (`GET /api/terminos`), la pantalla lo
pinta tal cual y, al aceptar, devuelve la versión **y la huella** de lo que
mostró; si no coinciden con las vigentes, no se registra nada.

**La huella** es el SHA-256 del archivo (con saltos de línea normalizados, para
que no cambie según cómo lo haya guardado git). Queda en la bitácora con cada
aceptación: con ella se puede demostrar qué texto exacto vio cada persona,
aunque el archivo cambie después.

**Formato del archivo:** una cabecera entre dos líneas `---` con `version`,
`vigente_desde` y `titulo`; después, cada cláusula empieza con `## ` y sus
párrafos van separados por una línea en blanco. Para publicar una versión nueva
se cambia el texto **y** el número de versión: a partir de ese momento el
portal le vuelve a pedir la aceptación a todo el mundo.

Solo biblioteca estándar, a propósito: scripts/vista-previa.py lo importa en el
host, donde no están las dependencias del backend.
"""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Tuple

ARCHIVO = Path(__file__).resolve().parent.parent / "recursos" / "terminos.md"


@dataclass(frozen=True)
class Seccion:
    titulo: str
    parrafos: Tuple[str, ...]


@dataclass(frozen=True)
class Documento:
    version: str
    vigente_desde: str
    titulo: str
    secciones: Tuple[Seccion, ...]
    huella: str

    def a_dict(self) -> dict:
        return {
            "version": self.version,
            "vigente_desde": self.vigente_desde,
            "titulo": self.titulo,
            "huella": self.huella,
            "secciones": [{"titulo": s.titulo, "parrafos": list(s.parrafos)} for s in self.secciones],
        }


def leer(texto: str) -> Documento:
    """El documento a partir del texto del archivo. ValueError si está mal formado."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    huella = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    lineas = texto.split("\n")
    if not lineas or lineas[0].strip() != "---":
        raise ValueError("terminos.md: falta la cabecera entre líneas ---")
    try:
        fin = lineas.index("---", 1)
    except ValueError:
        raise ValueError("terminos.md: la cabecera no se cierra con ---") from None
    cabecera = {}
    for linea in lineas[1:fin]:
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            cabecera[clave.strip()] = valor.strip()
    faltan = [c for c in ("version", "vigente_desde", "titulo") if not cabecera.get(c)]
    if faltan:
        raise ValueError(f"terminos.md: faltan en la cabecera: {', '.join(faltan)}")

    secciones, titulo, parrafos, parrafo = [], None, [], []

    def cerrar_parrafo():
        if parrafo:
            parrafos.append(" ".join(parrafo))
            parrafo.clear()

    def cerrar_seccion():
        cerrar_parrafo()
        if titulo is not None:
            if not parrafos:
                raise ValueError(f"terminos.md: la cláusula «{titulo}» no tiene texto")
            secciones.append(Seccion(titulo, tuple(parrafos)))

    for linea in lineas[fin + 1:]:
        if linea.startswith("## "):
            cerrar_seccion()
            titulo, parrafos = linea[3:].strip(), []
        elif not linea.strip():
            cerrar_parrafo()
        elif titulo is None:
            raise ValueError("terminos.md: hay texto antes de la primera cláusula (##)")
        else:
            parrafo.append(linea.strip())
    cerrar_seccion()
    if not secciones:
        raise ValueError("terminos.md: no tiene cláusulas")

    return Documento(cabecera["version"], cabecera["vigente_desde"], cabecera["titulo"],
                     tuple(secciones), huella)


@lru_cache(maxsize=1)
def documento() -> Documento:
    """El vigente, leído una vez. Cambiarlo es desplegar: reiniciar el backend."""
    return leer(ARCHIVO.read_text(encoding="utf-8"))


def version_vigente() -> str:
    return documento().version
