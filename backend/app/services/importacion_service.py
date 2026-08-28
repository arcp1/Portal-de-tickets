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
    número de empleado + su fecha de nacimiento. No hay nada que repartir. Es lo
    que hace viable una carga inicial de 300.

El dato de verificación es la **fecha de nacimiento**, no la de ingreso. La de
ingreso parecía natural y en la práctica no sirve: buena parte de la plantilla
lleva años en la planta y no recuerda en qué mes entró. Del cumpleaños se acuerda
todo el mundo, y RH lo trae en la misma lista.

Ese modo apoya la identidad en un dato que la persona sabe y que no está a la
vista de sus compañeros. No es tan fuerte como un código entregado en mano
—alguien de RH podría conocer ambas cosas— así que se acota con una ventana de
activación: pasada esa fecha, las cuentas que sigan sin activar requieren código.
Para quien no active ni así, queda la activación asistida en mostrador.

El archivo se procesa **entero antes de escribir nada**: o entra todo o no entra
nada. Una importación a medias de 300 filas es peor que un error.
"""

import csv
import io
import unicodedata
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import get_password_hash
from app.models import Usuario
from app.services.cuentas_service import (
    PENDIENTE, dominio_valido, generar_codigo, normalizar_codigo, normalizar_epp,
)

# Encabezados que se aceptan para cada campo. Las listas de RH nunca vienen
# con los nombres que uno quisiera, así que se reconocen variantes comunes.
COLUMNAS = {
    "numero_empleado": ("numero_empleado", "numero de empleado", "num_empleado", "no_empleado",
                        "numero", "num", "empleado", "no. empleado", "clave", "id_empleado",
                        # Como se le llama en las listas de nómina de por acá.
                        "ficha", "matricula", "matrícula", "clave_trabajador",
                        "no. trabajador", "num_trabajador", "id", "codigo", "código"),
    "nombre": ("nombre", "nombre completo", "nombre_completo", "colaborador", "empleado_nombre",
               "trabajador", "nombre del trabajador", "apellidos y nombres",
               "nombre y apellidos", "full_name"),
    "email": ("email", "correo", "correo electronico", "correo electrónico", "e-mail", "mail"),
    "area": ("area", "área", "departamento", "depto", "adscripcion", "adscripción", "puesto_area",
             "linea", "línea", "planta", "seccion", "sección", "centro de costos", "dept"),
    "fecha_ingreso": ("fecha_ingreso", "fecha de ingreso", "ingreso", "fecha_alta", "alta",
                      "antiguedad", "antigüedad", "fecha contratacion", "fecha de contratacion"),
    "fecha_nacimiento": ("fecha_nacimiento", "fecha de nacimiento", "nacimiento", "fec nac",
                         "fec_nac", "f nacimiento", "cumpleanos", "cumpleaños", "fecha nac",
                         "nacimiento fecha", "birthdate", "dob", "fecha de nac",
                         "cumple", "f nac", "fecha nacimiento"),
    "numero_epp": ("numero_epp", "numero de epp", "epp", "no epp", "no. epp",
                   "num epp", "clave epp", "numero equipo", "vale epp",
                   "numero de seguridad", "epp numero", "clave de epp"),
    "rol": ("rol", "perfil", "tipo"),
}

# Los que el importador necesita sí o sí.
OBLIGATORIAS = ("numero_empleado", "nombre")

# Cómo se le explica cada campo a quien mapea las columnas a mano, y a Ollama
# cuando se le pide que proponga el mapeo.
DESCRIPCIONES = {
    "numero_empleado": "número o clave de empleado, la que trae el gafete",
    "nombre": "nombre completo de la persona",
    "email": "correo electrónico",
    "area": "área, departamento o adscripción",
    "numero_epp": "número de EPP, los cuatro dígitos para sacar equipo de protección",
    "fecha_nacimiento": "fecha de nacimiento",
    "fecha_ingreso": "fecha de ingreso o de alta en la empresa",
    "rol": "perfil o tipo de usuario",
}

FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")

# Cómo se nombra cada dato de verificación en los mensajes de error.
ETIQUETAS_VERIFICACION = {
    "numero_epp": "número de EPP",
    "fecha_nacimiento": "fecha de nacimiento",
    "fecha_ingreso": "fecha de ingreso",
}


class FilaImportacion:
    """Una fila del archivo, ya interpretada y con su veredicto."""

    def __init__(self, numero: int):
        self.numero = numero
        self.numero_empleado: Optional[str] = None
        self.nombre: Optional[str] = None
        self.email: Optional[str] = None
        self.area: Optional[str] = None
        self.fecha_ingreso: Optional[datetime] = None
        self.fecha_nacimiento: Optional[datetime] = None
        self.numero_epp: Optional[str] = None
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
            "fecha_nacimiento": (self.fecha_nacimiento.date().isoformat()
                                 if self.fecha_nacimiento else None),
            "numero_epp": self.numero_epp,
            "rol": self.rol,
            "error": self.error,
            "aviso": self.aviso,
            "codigo": self.codigo,
        }


def _normalizar_encabezado(texto: str) -> str:
    """Deja el encabezado comparable con los alias.

    Los archivos de RH escriben lo mismo de mil maneras: "No. Empleado",
    "NUM_EMPLEADO", "Núm empleado". Se quitan acentos y puntuación para que las
    tres caigan en el mismo cajón, en vez de multiplicar la tabla de alias.
    """
    limpio = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    limpio = "".join(c for c in limpio if not unicodedata.combining(c))
    limpio = "".join(c if c.isalnum() else " " for c in limpio)
    return " ".join(limpio.split())


def _mapear_columnas(encabezados: List[str], manual: Optional[dict] = None) -> dict:
    """Qué columna del archivo corresponde a cada campo.

    `manual` es la corrección que hizo el admin en pantalla y **manda sobre la
    detección automática**: las listas de RH traen encabezados que ningún
    diccionario de alias va a cubrir, y adivinar mal en silencio es peor que
    preguntar.
    """
    mapa = {}
    normalizados = [_normalizar_encabezado(h) for h in encabezados]

    for campo, alias in COLUMNAS.items():
        alias_norm = [_normalizar_encabezado(a) for a in alias]
        for i, encabezado in enumerate(normalizados):
            if encabezado in alias_norm:
                mapa[campo] = i
                break

    for campo, encabezado in (manual or {}).items():
        if campo not in COLUMNAS:
            continue
        if encabezado in (None, ""):
            mapa.pop(campo, None)      # el admin dijo "esta columna no está"
            continue
        # Se acepta el nombre del encabezado o su posición.
        if isinstance(encabezado, int) or str(encabezado).isdigit():
            indice = int(encabezado)
            if 0 <= indice < len(encabezados):
                mapa[campo] = indice
            continue
        objetivo = _normalizar_encabezado(str(encabezado))
        for i, h in enumerate(normalizados):
            if h == objetivo:
                mapa[campo] = i
                break

    return mapa


def _parecido(encabezado: str, alias: tuple) -> float:
    """Qué tanto se parece un encabezado a los alias de un campo.

    Compara palabras sueltas: "CLAVE_TRAB" comparte "clave" con los alias de
    numero_empleado, y "F_NAC" comparte "nac" con los de fecha_nacimiento. No es
    listo, pero es determinista y no necesita que Ollama esté encendido.
    """
    palabras = set(_normalizar_encabezado(encabezado).split())
    if not palabras:
        return 0.0

    mejor = 0.0
    for a in alias:
        objetivo = set(_normalizar_encabezado(a).split())
        if not objetivo:
            continue
        # Cuenta también las palabras que empiezan igual: "trab" con
        # "trabajador", "emple" con "empleado". Es como se abrevia en las listas
        # de nómina.
        #
        # El mínimo de 4 letras no es capricho: con 3 bastaba para que "COL_B"
        # se emparejara con "colaborador" y la pantalla llegara con una
        # sugerencia falsa ya marcada, que es peor que no sugerir nada.
        aciertos = sum(
            1 for p in palabras
            if any(p == o or (len(p) >= 4 and o.startswith(p)) or
                   (len(o) >= 4 and p.startswith(o)) for o in objetivo)
        )
        if aciertos:
            mejor = max(mejor, aciertos / max(len(palabras), len(objetivo)))
    return mejor


def _mapeo_aproximado(disponibles: List[str], faltantes: List[str]) -> dict:
    """Empareja por parecido lo que la tabla de alias no cubrió, sin modelo."""
    propuesta = {}
    usados = set()
    # Se resuelven primero los emparejamientos más claros, para que un
    # encabezado no se lo lleve un campo con el que encajaba peor.
    puntajes = sorted(
        ((_parecido(h, COLUMNAS[c]), c, h) for c in faltantes for h in disponibles),
        reverse=True,
    )
    for puntaje, campo, encabezado in puntajes:
        # Solo se propone lo que encaja claramente. Ante la duda no se propone:
        # una sugerencia equivocada se acepta sin mirar, y entonces el padrón
        # queda mal con la bendición de quien importó.
        if puntaje < 0.6 or campo in propuesta or encabezado in usados:
            continue
        propuesta[campo] = encabezado
        usados.add(encabezado)
    return propuesta


def sugerir_mapeo(encabezados: List[str], detectado: dict) -> Optional[dict]:
    """Propone qué columna es cuál cuando los encabezados no se reconocieron.

    Dos pasadas, en este orden:

      1. **Parecido de palabras**, determinista y sin depender de nada externo.
      2. **Ollama**, para lo que quedó suelto, que es donde un modelo aporta:
         "Matricula" o "Adscripción" no se parecen a ningún alias pero
         cualquiera entiende a qué se refieren.

    Es ayuda, no autoridad: la propuesta se le muestra al admin para que la
    confirme o la corrija, y todo lo que el modelo devuelva se comprueba contra
    los encabezados reales antes de mostrarlo. Si Ollama no está, queda lo de la
    primera pasada — **la importación nunca depende del modelo**.
    """
    faltantes = [c for c in COLUMNAS if c not in detectado]
    if not faltantes or not encabezados:
        return None

    ocupados = set(detectado.values())
    disponibles = [h for i, h in enumerate(encabezados) if i not in ocupados]
    if not disponibles:
        return None

    propuesta = _mapeo_aproximado(disponibles, faltantes)

    sueltos = [c for c in faltantes if c not in propuesta]
    libres = [h for h in disponibles if h not in propuesta.values()]
    if sueltos and libres:
        propuesta.update(_sugerencia_del_modelo(sueltos, libres))

    return propuesta or None


def _sugerencia_del_modelo(faltantes: List[str], disponibles: List[str]) -> dict:
    """Lo que Ollama proponga, ya filtrado. Devuelve {} si no está o falla."""
    from app.services.ollama_client import ollama

    campos = "\n".join(f'  "{c}": {DESCRIPCIONES.get(c, c)}' for c in faltantes)
    lista = "\n".join(f"- {h}" for h in disponibles)

    # Con un ejemplo resuelto acierta; sin él, un modelo de 3B se acobarda y
    # contesta {} aunque el emparejamiento sea evidente.
    instruccion = (
        "Empareja los encabezados de un archivo de personal con los campos de "
        "un sistema. Responde SOLO JSON.\n\n"
        "EJEMPLO\n"
        "Encabezados: NUM_EMP, NOMBRE COMPLETO, DEPTO, FEC_NAC, CORREO\n"
        'Respuesta: {"numero_empleado": "NUM_EMP", "nombre": "NOMBRE COMPLETO", '
        '"area": "DEPTO", "fecha_nacimiento": "FEC_NAC", "email": "CORREO"}\n\n'
        "CAMPOS DEL SISTEMA\n" + campos + "\n\n"
        "ENCABEZADOS DEL ARCHIVO\n" + lista + "\n\n"
        "Reglas: el valor debe ser uno de los encabezados de arriba, copiado tal "
        "cual. Omite el campo si ningún encabezado le corresponde. No inventes "
        "encabezados.\n"
        "Respuesta:"
    )

    crudo = ollama.responder_json(instruccion, num_predict=200)
    if not isinstance(crudo, dict):
        return {}

    # El modelo se inventa nombres de campo y a veces copia encabezados del
    # ejemplo. Solo pasa lo que existe de los dos lados.
    propuesta = {}
    usados = set()
    for campo, encabezado in crudo.items():
        if campo not in faltantes or not isinstance(encabezado, str):
            continue
        for h in disponibles:
            if h not in usados and _normalizar_encabezado(h) == _normalizar_encabezado(encabezado):
                propuesta[campo] = h
                usados.add(h)
                break
    return propuesta


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
    def analizar(db: Session, contenido: bytes, sitio_id: int,
                 mapeo: Optional[dict] = None) -> dict:
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

        mapa = _mapear_columnas(encabezados, mapeo)
        faltantes = [c for c in OBLIGATORIAS if c not in mapa]
        if faltantes:
            # No es un callejón sin salida: la pantalla ofrece mapear a mano, y
            # Ollama propone un emparejamiento si está disponible.
            return {
                "ok": False,
                "necesita_mapeo": True,
                "error": ("No se reconocieron las columnas obligatorias: "
                          + ", ".join(faltantes)
                          + ". Indique qué columna del archivo corresponde a cada una."),
                "encabezados": encabezados,
                "columnas_detectadas": {k: encabezados[v] for k, v in mapa.items()},
                "sugerencia": sugerir_mapeo(encabezados, mapa),
                "campos": {c: DESCRIPCIONES.get(c, c) for c in COLUMNAS},
                "obligatorias": list(OBLIGATORIAS),
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
            fila.fecha_nacimiento = _leer_fecha(valor("fecha_nacimiento"))
            fila.numero_epp = normalizar_epp(valor("numero_epp"))
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
                factores = sum(1 for v in (fila.numero_epp, fila.fecha_nacimiento,
                                           fila.fecha_ingreso) if v)
                if factores == 0:
                    fila.aviso = ((fila.aviso + " ") if fila.aviso else "") + \
                        "Sin datos de verificación: necesitará código o activación asistida."
                elif factores < settings.VERIFICACION_FACTORES:
                    fila.aviso = ((fila.aviso + " ") if fila.aviso else "") + \
                        "Solo un dato de verificación: se activará con uno, no con dos."

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
            "sin_fecha_nacimiento": sum(1 for f in validas if not f.fecha_nacimiento),
            "sin_numero_epp": sum(1 for f in validas if not f.numero_epp),
            # Cuánta gente quedaría con verificación de un solo factor, que es
            # más débil de lo que el portal pretende ofrecer.
            "con_un_solo_factor": sum(
                1 for f in validas
                if 0 < sum(1 for v in (f.numero_epp, f.fecha_nacimiento, f.fecha_ingreso) if v)
                < settings.VERIFICACION_FACTORES
            ),
            "necesita_mapeo": False,
            "encabezados": encabezados,
            "columnas_detectadas": {k: encabezados[v] for k, v in mapa.items()},
            "campos": {c: DESCRIPCIONES.get(c, c) for c in COLUMNAS},
            "obligatorias": list(OBLIGATORIAS),
            "filas": [f.a_dict() for f in filas],
        }

    @staticmethod
    def importar(
        db: Session,
        contenido: bytes,
        sitio_id: int,
        modo_activacion: str = "codigo",
        dias_ventana: Optional[int] = None,
        dato_verificacion: str = "fecha_nacimiento",
        mapeo: Optional[dict] = None,
    ) -> dict:
        """Crea las cuentas. O entran todas las filas válidas, o ninguna.

        `modo_activacion`:
          - "codigo": se genera uno por persona, para imprimir y repartir.
          - "verificacion": la persona activa con su número + `dato_verificacion`,
            que por omisión es la fecha de nacimiento, que sí recuerdan.
        """
        analisis = ImportacionService.analizar(db, contenido, sitio_id, mapeo)
        if not analisis["ok"]:
            return {**analisis, "importadas": 0}

        validas = [f for f in analisis["filas"] if not f["error"]]

        if modo_activacion == "verificacion":
            etiqueta = ETIQUETAS_VERIFICACION.get(dato_verificacion, dato_verificacion)
            sin_fecha = [f for f in validas if not f[dato_verificacion]]
            if sin_fecha:
                # Todo o nada: importar a medias dejaría gente sin poder entrar
                # y sin que nadie se dé cuenta hasta que reclame.
                return {
                    **analisis, "importadas": 0,
                    "error": (f"{len(sin_fecha)} fila(s) no traen {etiqueta} y el modo de "
                              "verificación la necesita. Complete la columna, elija el otro "
                              "dato de verificación o use el modo con código."),
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
                    fecha_nacimiento=(datetime.fromisoformat(f["fecha_nacimiento"])
                                      if f["fecha_nacimiento"] else None),
                    numero_epp=f["numero_epp"],
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
            "dato_verificacion": dato_verificacion if modo_activacion == "verificacion" else None,
            "vence": vence.isoformat(),
            "filas": creadas,
        }

    @staticmethod
    def csv_de_codigos(filas: List[dict], area: Optional[str] = None) -> str:
        """CSV con los códigos, para imprimir y repartir.

        Se puede filtrar por área: así TI no reparte 300 papelitos, sino que le
        pasa a cada supervisor los diez o veinte de su gente. El reparto se
        vuelve ~20 sobres en vez de 300 entregas.
        """
        salida = io.StringIO()
        escritor = csv.writer(salida)
        escritor.writerow(["numero_empleado", "nombre", "area", "codigo_activacion"])
        for f in filas:
            if not f.get("codigo"):
                continue
            if area and (f.get("area") or "").strip().lower() != area.strip().lower():
                continue
            escritor.writerow([f["numero_empleado"], f["nombre"],
                               f.get("area") or "", f["codigo"]])
        return salida.getvalue()

    @staticmethod
    def areas_de(filas: List[dict]) -> List[str]:
        """Las áreas presentes en el archivo, para repartir por supervisor."""
        vistas = []
        for f in filas:
            area = (f.get("area") or "").strip()
            if area and area not in vistas:
                vistas.append(area)
        return sorted(vistas)

    @staticmethod
    def plantilla_csv() -> str:
        """Ejemplo con los encabezados que el importador reconoce."""
        salida = io.StringIO()
        escritor = csv.writer(salida)
        escritor.writerow(["numero_empleado", "nombre", "area", "email",
                           "numero_epp", "fecha_nacimiento", "fecha_ingreso", "rol"])
        escritor.writerow(["10234", "Juan Pérez Martínez", "Producción",
                           "juan.perez@cgr.mx", "0421", "1978-04-23", "2021-03-15", "usuario"])
        escritor.writerow(["10235", "María López Sánchez", "Calidad", "",
                           "1187", "1985-12-09", "2019-11-02", "usuario"])
        escritor.writerow(["10236", "Pedro Ramírez Cruz", "Almacén", "",
                           "3390", "09/06/1966", "15/07/2022", "usuario"])
        return salida.getvalue()
