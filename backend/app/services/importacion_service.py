"""Importación masiva de personal desde CSV.

**El problema real no es crear 300 cuentas, es repartir 300 códigos.** Crear las
cuentas es una consulta; entregarle a cada persona un papelito con su código es
trabajo de campo para semanas.

Por eso la importación soporta dos modos de activación, y la elección es del
admin según lo que tenga a la mano:

  - **Con código** (`codigo`): se genera uno por persona y se exportan a CSV
    para imprimir y repartir. Es lo más seguro y lo razonable para altas de
    pocas personas.

  - **Con dato de verificación** (`verificacion`): la persona activa con su
    número de empleado + su fecha de ingreso. No hay nada que repartir. Es lo
    que hace viable una carga inicial de 300.

El segundo modo apoya la identidad en un dato que la persona sabe y que no está
a la vista de sus compañeros. No es tan fuerte como un código entregado en mano
—alguien de RH podría conocer ambas cosas— así que se acota con una ventana de
activación: pasada esa fecha, las cuentas que sigan sin activar requieren código.

El archivo se procesa **entero antes de escribir nada**: o entra todo o no entra
nada. Una importación a medias de 300 filas es peor que un error.
"""

import csv
import io
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import get_password_hash
from app.models import Usuario
from app.services.cuentas_service import (
    PENDIENTE, dominio_valido, generar_codigo, normalizar_codigo,
)

# Encabezados que se aceptan para cada campo. Las listas de RH nunca vienen
# con los nombres que uno quisiera, así que se reconocen variantes comunes.
COLUMNAS = {
    "numero_empleado": ("numero_empleado", "numero de empleado", "num_empleado", "no_empleado",
                        "numero", "num", "empleado", "no. empleado", "clave", "id_empleado"),
    "nombre": ("nombre", "nombre completo", "nombre_completo", "colaborador", "empleado_nombre"),
    "email": ("email", "correo", "correo electronico", "correo electrónico", "e-mail", "mail"),
    "area": ("area", "área", "departamento", "depto", "adscripcion", "adscripción", "puesto_area"),
    "fecha_ingreso": ("fecha_ingreso", "fecha de ingreso", "ingreso", "fecha_alta", "alta"),
    "rol": ("rol", "perfil", "tipo"),
}

FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")


class FilaImportacion:
    """Una fila del archivo, ya interpretada y con su veredicto."""

    def __init__(self, numero: int):
        self.numero = numero
        self.numero_empleado: Optional[str] = None
        self.nombre: Optional[str] = None
        self.email: Optional[str] = None
        self.area: Optional[str] = None
        self.fecha_ingreso: Optional[datetime] = None
        self.rol: str = "usuario"
        self.error: Optional[str] = None
        self.aviso: Optional[str] = None
        self.codigo: Optional[str] = None

    def a_dict(self) -> dict:
        return {
            "fila": self.numero,
            "numero_empleado": self.numero_empleado,
            "nombre": self.nombre,
            "email": self.email,
            "area": self.area,
            "fecha_ingreso": self.fecha_ingreso.date().isoformat() if self.fecha_ingreso else None,
            "rol": self.rol,
            "error": self.error,
            "aviso": self.aviso,
            "codigo": self.codigo,
        }


def _normalizar_encabezado(texto: str) -> str:
    return " ".join((texto or "").strip().lower().replace("_", " ").split())


def _mapear_columnas(encabezados: List[str]) -> dict:
    """Encuentra qué columna del archivo corresponde a cada campo."""
    mapa = {}
    normalizados = [_normalizar_encabezado(h) for h in encabezados]
    for campo, alias in COLUMNAS.items():
        for i, encabezado in enumerate(normalizados):
            if encabezado in [_normalizar_encabezado(a) for a in alias]:
                mapa[campo] = i
                break
    return mapa


def _leer_fecha(texto: str) -> Optional[datetime]:
    texto = (texto or "").strip()
    if not texto:
        return None
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


def _decodificar(contenido: bytes) -> str:
    """Excel en Windows exporta en cp1252, no en UTF-8."""
    for codificacion in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("utf-8", errors="replace")


class ImportacionService:

    @staticmethod
    def analizar(db: Session, contenido: bytes, sitio_id: int) -> dict:
        """Interpreta el archivo y dice qué pasaría, sin escribir nada.

        Siempre se ejecuta antes de importar: nadie debería cargar 300 filas
        a ciegas.
        """
        texto = _decodificar(contenido)

        # El separador varía: Excel en español exporta con punto y coma.
        try:
            dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
        except csv.Error:
            dialecto = csv.excel

        lector = csv.reader(io.StringIO(texto), dialecto)
        try:
            encabezados = next(lector)
        except StopIteration:
            return {"ok": False, "error": "El archivo está vacío.", "filas": []}

        mapa = _mapear_columnas(encabezados)
        faltantes = [c for c in ("numero_empleado", "nombre") if c not in mapa]
        if faltantes:
            return {
                "ok": False,
                "error": ("No se encontraron las columnas obligatorias: "
                          + ", ".join(faltantes)
                          + ". Encabezados detectados: " + ", ".join(encabezados)),
                "filas": [],
            }

        # Lo que ya existe, para no chocar.
        existentes_num = {
            n for (n,) in db.query(Usuario.numero_empleado)
            .filter(Usuario.numero_empleado.isnot(None)).all()
        }
        existentes_email = {
            e.lower() for (e,) in db.query(Usuario.email).filter(Usuario.email.isnot(None)).all()
        }

        vistos_num, vistos_email = set(), set()
        filas: List[FilaImportacion] = []

        for indice, columnas in enumerate(lector, start=2):
            if not any((c or "").strip() for c in columnas):
                continue  # línea en blanco

            fila = FilaImportacion(indice)

            def valor(campo):
                i = mapa.get(campo)
                return (columnas[i].strip() if i is not None and i < len(columnas) else "")

            fila.numero_empleado = valor("numero_empleado")
            fila.nombre = valor("nombre")
            fila.email = valor("email").lower() or None
            fila.area = valor("area") or None
            fila.fecha_ingreso = _leer_fecha(valor("fecha_ingreso"))
            rol = valor("rol").lower()
            fila.rol = rol if rol in ("admin", "usuario") else "usuario"

            # --- Validaciones ---
            if not fila.numero_empleado:
                fila.error = "Sin número de empleado."
            elif len(fila.numero_empleado) > 20:
                fila.error = "El número de empleado excede 20 caracteres."
            elif not fila.nombre or len(fila.nombre) < 3:
                fila.error = "Nombre vacío o demasiado corto."
            elif fila.numero_empleado in existentes_num:
                fila.error = f"Ya existe una cuenta con el número {fila.numero_empleado}."
            elif fila.numero_empleado in vistos_num:
                fila.error = "El número de empleado se repite dentro del archivo."
            elif fila.email and fila.email in existentes_email:
                fila.error = f"El correo {fila.email} ya está en uso."
            elif fila.email and fila.email in vistos_email:
                fila.error = "El correo se repite dentro del archivo."
            elif fila.email and not dominio_valido(fila.email):
                fila.error = f"El correo {fila.email} no es de un dominio de la empresa."

            if not fila.error:
                vistos_num.add(fila.numero_empleado)
                if fila.email:
                    vistos_email.add(fila.email)
                if not fila.email:
                    fila.aviso = "Sin correo: no recibirá avisos."
                if not fila.fecha_ingreso:
                    fila.aviso = ((fila.aviso + " ") if fila.aviso else "") + \
                        "Sin fecha de ingreso: no podrá activar por verificación."

            filas.append(fila)

        validas = [f for f in filas if not f.error]
        return {
            "ok": bool(validas),
            "error": None if validas else "Ninguna fila del archivo se puede importar.",
            "total": len(filas),
            "validas": len(validas),
            "con_error": len(filas) - len(validas),
            "sin_correo": sum(1 for f in validas if not f.email),
            "sin_fecha_ingreso": sum(1 for f in validas if not f.fecha_ingreso),
            "columnas_detectadas": {k: encabezados[v] for k, v in mapa.items()},
            "filas": [f.a_dict() for f in filas],
        }

    @staticmethod
    def importar(
        db: Session,
        contenido: bytes,
        sitio_id: int,
        modo_activacion: str = "codigo",
        dias_ventana: Optional[int] = None,
    ) -> dict:
        """Crea las cuentas. O entran todas las filas válidas, o ninguna.

        `modo_activacion`:
          - "codigo": se genera uno por persona, para imprimir y repartir.
          - "verificacion": la persona activa con su número + fecha de ingreso.
        """
        analisis = ImportacionService.analizar(db, contenido, sitio_id)
        if not analisis["ok"]:
            return {**analisis, "importadas": 0}

        validas = [f for f in analisis["filas"] if not f["error"]]

        if modo_activacion == "verificacion":
            sin_fecha = [f for f in validas if not f["fecha_ingreso"]]
            if sin_fecha:
                return {
                    **analisis, "importadas": 0,
                    "error": (f"{len(sin_fecha)} fila(s) no traen fecha de ingreso y el modo de "
                              "verificación la necesita. Complete la columna o use el modo con código."),
                }

        ahora = datetime.utcnow()
        vence = ahora + timedelta(
            hours=(dias_ventana * 24) if dias_ventana else settings.CODIGO_ACTIVACION_HORAS
        )

        creadas = []
        try:
            for f in validas:
                codigo = generar_codigo() if modo_activacion == "codigo" else None
                usuario = Usuario(
                    sitio_id=sitio_id,
                    numero_empleado=f["numero_empleado"],
                    nombre=f["nombre"],
                    email=f["email"],
                    area=f["area"],
                    rol=f["rol"],
                    fecha_ingreso=(datetime.fromisoformat(f["fecha_ingreso"])
                                   if f["fecha_ingreso"] else None),
                    activo=True,
                    password_hash=None,
                    estado_cuenta=PENDIENTE,
                    codigo_activacion_hash=(get_password_hash(normalizar_codigo(codigo))
                                            if codigo else None),
                    codigo_expira=vence,
                    creado_en=ahora,
                )
                db.add(usuario)
                creadas.append({**f, "codigo": codigo})

            # Todo o nada: una importación a medias de 300 filas es peor que un error.
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Falló la importación masiva; no se creó ninguna cuenta",
                         extra={"error": str(exc)})
            return {**analisis, "importadas": 0,
                    "error": f"No se importó nada por un error en la base: {exc}"}

        logger.info("Importación masiva completada",
                    extra={"creadas": len(creadas), "modo": modo_activacion})

        return {
            **analisis,
            "importadas": len(creadas),
            "modo_activacion": modo_activacion,
            "vence": vence.isoformat(),
            "filas": creadas,
        }

    @staticmethod
    def csv_de_codigos(filas: List[dict]) -> str:
        """CSV con los códigos, para imprimir y repartir por área."""
        salida = io.StringIO()
        escritor = csv.writer(salida)
        escritor.writerow(["numero_empleado", "nombre", "area", "codigo_activacion"])
        for f in filas:
            if f.get("codigo"):
                escritor.writerow([f["numero_empleado"], f["nombre"],
                                   f.get("area") or "", f["codigo"]])
        return salida.getvalue()

    @staticmethod
    def plantilla_csv() -> str:
        """Ejemplo con los encabezados que el importador reconoce."""
        salida = io.StringIO()
        escritor = csv.writer(salida)
        escritor.writerow(["numero_empleado", "nombre", "area", "email", "fecha_ingreso", "rol"])
        escritor.writerow(["10234", "Juan Pérez Martínez", "Producción",
                           "juan.perez@cgr.mx", "2021-03-15", "usuario"])
        escritor.writerow(["10235", "María López Sánchez", "Calidad", "", "2019-11-02", "usuario"])
        escritor.writerow(["10236", "Pedro Ramírez Cruz", "Almacén", "", "15/07/2022", "usuario"])
        return salida.getvalue()
