"""Gastos de TI: importes, CFDI, comprobantes, resumen y exportación.

Las rutas viven en `api/gastos.py`; aquí está lo que no depende de HTTP y
conviene poder probar suelto. Viene de la aplicación «Gastos TI» (Node y un
PostgreSQL embebido en una PC), corregida en lo que fallaba:

* **El dinero se calcula con `Decimal`** y se redondea al centavo una sola
  vez, con la regla de siempre (la mitad hacia arriba). El original lo pasaba
  a coma flotante y redondeaba con `Math.round(x * 100) / 100`.
* **IVA de 16, 8 o 0 %** —la región fronteriza paga 8— y **retenciones**. El
  original fijaba el 16 % y no conocía las retenciones, así que un CFDI de
  servicios profesionales se guardaba con un subtotal y un IVA que no sumaban
  el total.
* **La moneda cuenta.** Un CFDI en dólares se guarda en dólares con su tipo
  de cambio, y lo que se suma es `total_mxn`. El original lo detectaba y lo
  sumaba como si fueran pesos.
* **La misma factura no entra dos veces**: el folio fiscal (UUID) es único.
* **El presupuesto se compara contra lo que corresponde a la fecha**, por días
  transcurridos del año, y no contra «anual entre doce» mes a mes: con eso,
  una licencia anual pagada en enero salía como sobregiro de enero.
* **Los textos del resumen no se escriben aquí.** El original devolvía frases
  en castellano («Subió 12 % respecto a marzo»); ahora van los datos y la
  pantalla los dice en el idioma de cada quien.
"""

import csv
import io
import re
import uuid
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from app.core.config import settings
from app.services.directorio_service import ArchivoRechazado

CENTAVO = Decimal("0.01")
CERO = Decimal("0")
TASAS_IVA = (Decimal("0"), Decimal("0.08"), Decimal("0.16"))
MONEDAS = ("MXN", "USD")
TIPOS_COMPRA = ("proveedor", "linea")
TIPOS_COMPROBANTE = ("cotizacion", "orden_compra", "factura", "albaran", "pago", "pedido")
#: Las etapas del expediente de cada tipo de compra, en orden.
ETAPAS = {
    "proveedor": ("cotizacion", "orden_compra", "factura", "albaran"),
    "linea": ("pedido", "factura", "albaran"),
}
_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
_UUID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


def centavos(valor) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def decimal_de(texto, defecto: Optional[Decimal] = None) -> Optional[Decimal]:
    if texto is None or str(texto).strip() == "":
        return defecto
    try:
        return Decimal(str(texto).strip())
    except InvalidOperation:
        return defecto


class ImporteInvalido(ValueError):
    """Los importes no cuadran. El mensaje es para la persona."""


def calcular_importes(*, subtotal: Optional[Decimal], total: Optional[Decimal], tasa_iva: Decimal,
                      iva: Optional[Decimal] = None, retenciones: Decimal = CERO) -> Dict[str, Decimal]:
    """Subtotal, IVA, retenciones y total que cuadran al centavo.

    Se da el subtotal (antes de impuestos) **o** el total (lo que se paga).
    El IVA explícito —el que trae un CFDI, que se calcula concepto por
    concepto y puede diferir unos centavos de `subtotal × tasa`— gana sobre
    el calculado. Con el total, el subtotal sale de despejar
    `total = subtotal × (1 + tasa) − retenciones` y el IVA es lo que falta:
    así la suma da exactamente el total que se tecleó.
    """
    retenciones = centavos(retenciones or CERO)
    if retenciones < 0:
        raise ImporteInvalido("Las retenciones no pueden ser negativas.")
    if subtotal is not None:
        subtotal = centavos(subtotal)
        if subtotal < 0:
            raise ImporteInvalido("El subtotal no puede ser negativo.")
        iva = centavos(iva) if iva is not None else centavos(subtotal * tasa_iva)
        if iva < 0:
            raise ImporteInvalido("El IVA no puede ser negativo.")
        total = subtotal + iva - retenciones
    elif total is not None:
        total = centavos(total)
        if total < 0:
            raise ImporteInvalido("El total no puede ser negativo.")
        bruto = total + retenciones
        subtotal = centavos(bruto / (1 + tasa_iva))
        iva = bruto - subtotal
    else:
        raise ImporteInvalido("Capture el subtotal o el total pagado.")
    if total < 0:
        raise ImporteInvalido("Las retenciones son mayores que el subtotal más el IVA.")
    return {"subtotal": subtotal, "iva": iva, "retenciones": retenciones, "total": total}


def a_pesos(total: Decimal, moneda: str, tipo_cambio: Decimal) -> Decimal:
    return total if moneda == "MXN" else centavos(total * tipo_cambio)


def rfc_limpio(rfc: Optional[str]) -> Optional[str]:
    """El RFC en mayúsculas y sin espacios, o None. `ValueError` si no tiene
    forma de RFC: el original lo guardaba tal cual se tecleara."""
    valor = re.sub(r"[\s-]", "", (rfc or "")).upper()
    if not valor:
        return None
    if not _RFC.match(valor):
        raise ValueError("El RFC no tiene un formato válido (12 o 13 caracteres).")
    return valor


def etapas(tipo_compra: str, tipos: Iterable[str]) -> dict:
    """Cuántas etapas del expediente tiene un gasto y cuáles faltan."""
    presentes = set(tipos)
    requeridas = ETAPAS.get(tipo_compra, ETAPAS["proveedor"])
    hechas = [t for t in requeridas if t in presentes]
    return {"hechas": len(hechas), "total": len(requeridas), "completo": len(hechas) == len(requeridas),
            "faltan": [t for t in requeridas if t not in presentes],
            "pago": "pago" in presentes}


def hoy_local() -> date:
    from app.services.horario_service import a_hora_local
    return a_hora_local(datetime.utcnow()).date()


def rango_de(anio: int, mes: Optional[int] = None) -> Tuple[date, date]:
    """[desde, hasta) del año o del mes: un rango usa el índice de `fecha`."""
    if mes:
        desde = date(anio, mes, 1)
        hasta = date(anio + (mes == 12), mes % 12 + 1, 1)
        return desde, hasta
    return date(anio, 1, 1), date(anio + 1, 1, 1)


# ----------------------------------------------------------------------
# CFDI
# ----------------------------------------------------------------------

_DECLARACIONES = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def _local(etiqueta: str) -> str:
    return etiqueta.rsplit("}", 1)[-1]


def _hijo(nodo, nombre):
    if nodo is None:
        return None
    for h in nodo:
        if _local(h.tag) == nombre:
            return h
    return None


def _hijos(nodo, nombre):
    return [h for h in (nodo if nodo is not None else []) if _local(h.tag) == nombre]


def _primero(nodo, nombre):
    for x in nodo.iter():
        if _local(x.tag) == nombre:
            return x
    return None


def es_cfdi(contenido: bytes) -> bool:
    try:
        leer_cfdi(contenido)
        return True
    except ArchivoRechazado:
        return False


def leer_cfdi(contenido: bytes) -> dict:
    """Los datos de un CFDI 3.3 o 4.0, exactos. `ArchivoRechazado` si no lo es.

    **Sin DTD ni entidades**: un XML con `<!DOCTYPE` o `<!ENTITY` no se
    abre. Un CFDI timbrado no los lleva nunca, y son la puerta de las bombas
    de expansión y de la lectura de archivos del servidor.
    """
    if not contenido or b"\x00" in contenido[:8192]:
        raise ArchivoRechazado("El archivo no es un XML.")
    if _DECLARACIONES.search(contenido):
        raise ArchivoRechazado("El XML trae declaraciones (DOCTYPE o ENTITY) que no se aceptan.")
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError:
        raise ArchivoRechazado("El XML está dañado.")
    if _local(raiz.tag) != "Comprobante":
        raise ArchivoRechazado("El XML no es un CFDI: no tiene el nodo Comprobante.")
    a = raiz.attrib
    subtotal = decimal_de(a.get("SubTotal"), CERO)
    descuento = decimal_de(a.get("Descuento"), CERO)
    total = decimal_de(a.get("Total"), CERO)
    moneda = (a.get("Moneda") or "MXN").upper()
    tipo_cambio = decimal_de(a.get("TipoCambio"), Decimal("1"))

    # IVA trasladado (impuesto 002) y retenciones. El resumen del comprobante
    # es lo que vale; si falta, se suman los de cada concepto.
    impuestos = _hijo(raiz, "Impuestos")
    traslados = _hijos(_hijo(impuestos, "Traslados"), "Traslado") if impuestos is not None else []
    retenidos = _hijos(_hijo(impuestos, "Retenciones"), "Retencion") if impuestos is not None else []
    conceptos = _hijos(_hijo(raiz, "Conceptos"), "Concepto")
    if impuestos is None:
        for c in conceptos:
            ic = _hijo(c, "Impuestos")
            traslados += _hijos(_hijo(ic, "Traslados"), "Traslado")
            retenidos += _hijos(_hijo(ic, "Retenciones"), "Retencion")
    iva = sum((decimal_de(t.get("Importe"), CERO) for t in traslados if t.get("Impuesto") == "002"), CERO)
    tasas = {decimal_de(t.get("TasaOCuota")) for t in traslados if t.get("Impuesto") == "002"}
    tasas.discard(None)
    retenciones = sum((decimal_de(r.get("Importe"), CERO) for r in retenidos), CERO)
    if impuestos is not None and impuestos.get("TotalImpuestosRetenidos"):
        retenciones = decimal_de(impuestos.get("TotalImpuestosRetenidos"), retenciones)

    avisos = []
    base = centavos(subtotal - descuento)
    # Lo que no es IVA ni retención —IEPS, impuestos locales— no tiene
    # columna propia: se suma al subtotal para que el total cuadre, y se avisa.
    otros = centavos(total - (base + iva - retenciones))
    if abs(otros) >= CENTAVO:
        base = base + otros
        avisos.append("otros_impuestos")
    tipo = (a.get("TipoDeComprobante") or "I").upper()
    if tipo == "E":
        avisos.append("nota_de_credito")
    elif tipo == "P":
        avisos.append("complemento_de_pago")
    if moneda not in MONEDAS:
        avisos.append("moneda_no_soportada")

    descripciones = [str(c.get("Descripcion") or "").strip() for c in conceptos]
    descripciones = [d for d in descripciones if d]
    concepto = descripciones[0] if descripciones else ""
    if len(descripciones) > 1:
        concepto = f"{concepto} (+{len(descripciones) - 1})"

    emisor = _hijo(raiz, "Emisor")
    receptor = _hijo(raiz, "Receptor")
    timbre = _primero(raiz, "TimbreFiscalDigital")
    folio_fiscal = (timbre.get("UUID") if timbre is not None else "") or ""
    folio_fiscal = folio_fiscal.strip().upper()
    tasa = max(tasas) if tasas else (Decimal("0.16") if iva > 0 else CERO)
    fecha = (a.get("Fecha") or "")[:10]
    try:
        fecha = date.fromisoformat(fecha).isoformat()
    except ValueError:
        fecha = None
    return {
        "version": a.get("Version") or a.get("version"),
        "tipo_comprobante": tipo,
        "fecha": fecha,
        "folio": "-".join(x for x in (a.get("Serie"), a.get("Folio")) if x)[:60] or None,
        "uuid": folio_fiscal if _UUID.match(folio_fiscal) else None,
        "emisor_nombre": (emisor.get("Nombre") or "").strip()[:150] if emisor is not None else None,
        "emisor_rfc": (emisor.get("Rfc") or "").strip().upper() if emisor is not None else None,
        "receptor_rfc": (receptor.get("Rfc") or "").strip().upper() if receptor is not None else None,
        "concepto": concepto[:200] or None,
        "moneda": moneda if moneda in MONEDAS else "MXN",
        "tipo_cambio": tipo_cambio if moneda == "USD" else Decimal("1"),
        "subtotal": centavos(base),
        "tasa_iva": tasa if tasa in TASAS_IVA else Decimal("0.16"),
        "iva": centavos(iva),
        "retenciones": centavos(retenciones),
        "total": centavos(total),
        "avisos": avisos,
    }


# ----------------------------------------------------------------------
# Comprobantes en disco
# ----------------------------------------------------------------------

#: extensión → (tipo MIME con que se sirve, familia para comprobar el contenido)
TIPOS_ARCHIVO = {
    ".pdf": ("application/pdf", "pdf"),
    ".xml": ("application/xml", "xml"),
    ".jpg": ("image/jpeg", "jpeg"),
    ".jpeg": ("image/jpeg", "jpeg"),
    ".png": ("image/png", "png"),
    ".webp": ("image/webp", "webp"),
}
#: Se ven en el navegador. El XML sale siempre como descarga: un navegador
#: lo interpreta, y con una hoja XSLT o un espacio de nombres XHTML eso es
#: ejecutar algo ajeno en el origen del portal.
EN_LINEA = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


def tipo_de_archivo(nombre: str) -> Tuple[str, str]:
    from app.services.directorio_service import extension

    ext = extension(nombre)
    if ext not in TIPOS_ARCHIVO:
        raise ArchivoRechazado("Se aceptan PDF, el XML del CFDI y fotos (JPG, PNG o WEBP).")
    return TIPOS_ARCHIVO[ext]


def carpeta_en_disco() -> Path:
    ruta = Path(settings.DOCUMENTOS_RUTA) / "gastos"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def nuevo_nombre_guardado() -> str:
    return uuid.uuid4().hex


def borrar_binarios(nombres: Iterable[str]) -> None:
    from app.core.logging import logger

    base = carpeta_en_disco()
    for nombre in nombres:
        try:
            (base / nombre).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("No se pudo borrar un comprobante del disco",
                           extra={"archivo": nombre, "error": str(exc)})


# ----------------------------------------------------------------------
# Resumen del año
# ----------------------------------------------------------------------

def fraccion_del_anio(anio: int, hoy: date) -> Decimal:
    """Qué parte del año ha pasado, por días: 1 si ya terminó, 0 si no empezó."""
    if anio < hoy.year:
        return Decimal(1)
    if anio > hoy.year:
        return CERO
    dias = (date(anio + 1, 1, 1) - date(anio, 1, 1)).days
    return Decimal((hoy - date(anio, 1, 1)).days + 1) / Decimal(dias)


def mismo_dia_del_anio_anterior(hoy: date) -> date:
    try:
        return hoy.replace(year=hoy.year - 1)
    except ValueError:  # 29 de febrero
        return hoy.replace(year=hoy.year - 1, day=28)


def _pct(parte: Decimal, todo: Decimal) -> Optional[float]:
    return float(parte / todo) if todo else None


def resumir(filas: List[dict], categorias: Dict[int, dict], presupuestos: Dict[int, Decimal],
            proveedores: Dict[int, str], plantas: Dict[int, dict], tipos_por_gasto: Dict[int, set],
            anio: int, hoy: date, total_anio_anterior: Optional[Decimal],
            con_presupuesto: bool = True) -> dict:
    """El resumen del año a partir de sus gastos. Puro: sin base de datos,
    para poder probar las cuentas sueltas.

    `filas`: un dict por gasto con `id, fecha, concepto, categoria_id,
    proveedor_id, sitio_id, total_mxn, total, moneda, estado, tipo_compra`.
    """
    fraccion = fraccion_del_anio(anio, hoy)
    gastado = sum((f["total_mxn"] for f in filas), CERO)
    pendiente = sum((f["total_mxn"] for f in filas if f["estado"] == "pendiente"), CERO)
    presupuesto = sum(presupuestos.values(), CERO) if con_presupuesto else None
    prorrateado = centavos(presupuesto * fraccion) if presupuesto is not None else None
    proyeccion = centavos(gastado / fraccion) if fraccion > 0 else None
    ritmo_mensual = centavos(gastado / (fraccion * 12)) if fraccion > 0 else None
    mes_en_curso = hoy.month if anio == hoy.year else None

    meses = []
    for m in range(1, 13):
        del_mes = [f for f in filas if f["fecha"].month == m]
        por_cat = defaultdict(lambda: CERO)
        for f in del_mes:
            por_cat[f["categoria_id"]] += f["total_mxn"]
        meses.append({
            "mes": m,
            "total": sum((f["total_mxn"] for f in del_mes), CERO),
            "n": len(del_mes),
            "pendiente": sum((f["total_mxn"] for f in del_mes if f["estado"] == "pendiente"), CERO),
            "por_categoria": [{"categoria_id": c, "total": t}
                              for c, t in sorted(por_cat.items(), key=lambda x: -x[1])],
        })

    # El mes que más costó y lo que lo explica.
    mes_mas_caro = None
    con_gasto = [m for m in meses if m["total"] > 0]
    if con_gasto:
        top = max(con_gasto, key=lambda m: m["total"])
        del_mes = [f for f in filas if f["fecha"].month == top["mes"]]
        cat_id, cat_total = top["por_categoria"][0]["categoria_id"], top["por_categoria"][0]["total"]
        por_prov = defaultdict(lambda: [CERO, 0])
        for f in del_mes:
            por_prov[f["proveedor_id"]][0] += f["total_mxn"]
            por_prov[f["proveedor_id"]][1] += 1
        prov_id, (prov_total, prov_n) = max(por_prov.items(), key=lambda x: x[1][0])
        mayor = max(del_mes, key=lambda f: f["total_mxn"])
        anterior = meses[top["mes"] - 2]["total"] if top["mes"] > 1 else None
        promedio = (sum((m["total"] for m in con_gasto), CERO) / len(con_gasto)) if len(con_gasto) > 1 else None
        mes_mas_caro = {
            "mes": top["mes"],
            "total": top["total"],
            "n": top["n"],
            "categoria": {"id": cat_id, "nombre": categorias.get(cat_id, {}).get("nombre"),
                          "total": cat_total, "pct": _pct(cat_total, top["total"])},
            "proveedor": {"id": prov_id, "nombre": proveedores.get(prov_id) if prov_id else None,
                          "total": prov_total, "n": prov_n, "pct": _pct(prov_total, top["total"])},
            "mayor_gasto": {"id": mayor["id"], "concepto": mayor["concepto"],
                            "proveedor": proveedores.get(mayor["proveedor_id"]) if mayor["proveedor_id"] else None,
                            "total_mxn": mayor["total_mxn"], "pct": _pct(mayor["total_mxn"], top["total"])},
            "vs_mes_anterior": _pct(top["total"] - anterior, anterior) if anterior else None,
            "vs_promedio": _pct(top["total"] - promedio, promedio) if promedio else None,
            "promedio": centavos(promedio) if promedio else None,
        }

    por_categoria = []
    for cat_id, cat in categorias.items():
        total = sum((f["total_mxn"] for f in filas if f["categoria_id"] == cat_id), CERO)
        monto = presupuestos.get(cat_id, CERO) if con_presupuesto else None
        if not cat["activa"] and total == 0 and not monto:
            continue
        por_categoria.append({
            "categoria_id": cat_id, "nombre": cat["nombre"], "activa": cat["activa"],
            "total": total, "n": sum(1 for f in filas if f["categoria_id"] == cat_id),
            "presupuesto": monto,
            "consumo": _pct(total, monto) if monto else None,
            "prorrateado": centavos(monto * fraccion) if monto else None,
        })
    por_categoria.sort(key=lambda c: (-c["total"], c["nombre"].lower()))

    por_prov = defaultdict(lambda: [CERO, 0])
    for f in filas:
        por_prov[f["proveedor_id"]][0] += f["total_mxn"]
        por_prov[f["proveedor_id"]][1] += 1
    por_proveedor = [{"proveedor_id": p, "nombre": proveedores.get(p) if p else None, "total": t, "n": n}
                     for p, (t, n) in sorted(por_prov.items(), key=lambda x: -x[1][0])][:8]

    por_pl = defaultdict(lambda: [CERO, 0])
    for f in filas:
        por_pl[f["sitio_id"]][0] += f["total_mxn"]
        por_pl[f["sitio_id"]][1] += 1
    por_planta = [{"sitio_id": s, "clave": plantas.get(s, {}).get("clave") if s else None,
                   "nombre": plantas.get(s, {}).get("nombre") if s else None, "total": t, "n": n}
                  for s, (t, n) in sorted(por_pl.items(), key=lambda x: -x[1][0])]

    usd = [f for f in filas if f["moneda"] == "USD"]
    expediente = {"total": len(filas), "completos": 0, "sin_factura": 0, "sin_cotizacion": 0,
                  "sin_orden_compra": 0, "sin_pedido": 0, "sin_albaran": 0}
    for f in filas:
        tipos = tipos_por_gasto.get(f["id"], set())
        if etapas(f["tipo_compra"], tipos)["completo"]:
            expediente["completos"] += 1
        expediente["sin_factura"] += "factura" not in tipos
        expediente["sin_albaran"] += "albaran" not in tipos
        if f["tipo_compra"] == "proveedor":
            expediente["sin_cotizacion"] += "cotizacion" not in tipos
            expediente["sin_orden_compra"] += "orden_compra" not in tipos
        else:
            expediente["sin_pedido"] += "pedido" not in tipos

    return {
        "anio": anio,
        "hoy": hoy.isoformat(),
        "mes_en_curso": mes_en_curso,
        "fraccion_transcurrida": float(fraccion),
        "con_presupuesto": con_presupuesto,
        "totales": {
            "gastado": gastado,
            "n": len(filas),
            "pendiente": pendiente,
            "pagado": gastado - pendiente,
            "presupuesto": presupuesto,
            "disponible": (presupuesto - gastado) if presupuesto is not None else None,
            "prorrateado": prorrateado,
            # Positivo: se va por encima de lo que tocaba gastar a la fecha.
            "desviacion": (gastado - prorrateado) if prorrateado is not None else None,
            "consumo": _pct(gastado, presupuesto) if presupuesto else None,
            "proyeccion": proyeccion,
            "ritmo_mensual": ritmo_mensual,
            "anio_anterior": total_anio_anterior,
            "vs_anio_anterior": (_pct(gastado - total_anio_anterior, total_anio_anterior)
                                 if total_anio_anterior else None),
            "usd": {"n": len(usd), "total_usd": sum((f["total"] for f in usd), CERO),
                    "total_mxn": sum((f["total_mxn"] for f in usd), CERO)},
        },
        "meses": meses,
        "mes_mas_caro": mes_mas_caro,
        "por_categoria": por_categoria,
        "por_proveedor": por_proveedor,
        "por_planta": por_planta,
        "expediente": expediente,
    }


# ----------------------------------------------------------------------
# Exportación: CSV y Excel
# ----------------------------------------------------------------------

COLUMNAS = (
    ("id", "ID", "ID", "ID"),
    ("fecha", "Fecha", "Date", "Date"),
    ("tipo_compra", "Tipo de compra", "Purchase type", "Type d'achat"),
    ("concepto", "Concepto", "Description", "Libellé"),
    ("cantidad", "Cantidad", "Quantity", "Quantité"),
    ("proveedor", "Proveedor", "Supplier", "Fournisseur"),
    ("rfc", "RFC", "Tax ID (RFC)", "RFC"),
    ("categoria", "Categoría", "Category", "Catégorie"),
    ("planta", "Planta", "Plant", "Usine"),
    ("activo", "Activo", "Asset", "Équipement"),
    ("ticket", "Ticket", "Ticket", "Ticket"),
    ("responsable", "Responsable", "Owner", "Responsable"),
    ("moneda", "Moneda", "Currency", "Devise"),
    ("tipo_cambio", "Tipo de cambio", "Exchange rate", "Taux de change"),
    ("subtotal", "Subtotal", "Subtotal", "Sous-total"),
    ("iva", "IVA", "VAT", "TVA"),
    ("retenciones", "Retenciones", "Withholdings", "Retenues"),
    ("total", "Total", "Total", "Total"),
    ("total_mxn", "Total MXN", "Total MXN", "Total MXN"),
    ("estado", "Estado", "Status", "Statut"),
    ("fecha_pago", "Fecha de pago", "Payment date", "Date de paiement"),
    ("referencia", "Pedido / referencia", "Order / reference", "Commande / référence"),
    ("folios", "Folios de factura", "Invoice numbers", "Numéros de facture"),
    ("uuid", "UUID del CFDI", "CFDI UUID", "UUID du CFDI"),
    ("expediente", "Expediente", "File", "Dossier"),
    ("centro_costo", "Centro de costo", "Cost center", "Centre de coûts"),
    ("notas", "Notas", "Notes", "Notes"),
)
_IDIOMAS = {"es": 1, "en": 2, "fr": 3}
VALORES = {
    "proveedor": ("Por proveedor", "Supplier", "Fournisseur"),
    "linea": ("En línea", "Online", "En ligne"),
    "pendiente": ("Pendiente", "Pending", "En attente"),
    "pagado": ("Pagado", "Paid", "Payé"),
    "completo": ("Completo", "Complete", "Complet"),
}
NUMERICAS = {"cantidad", "tipo_cambio", "subtotal", "iva", "retenciones", "total", "total_mxn"}


def encabezados(idioma: str) -> List[str]:
    i = _IDIOMAS.get((idioma or "es")[:2], 1)
    return [c[i] for c in COLUMNAS]


def valor_traducido(clave: str, idioma: str) -> str:
    i = _IDIOMAS.get((idioma or "es")[:2], 1) - 1
    return VALORES[clave][i] if clave in VALORES else clave


def _sin_formula(texto: str) -> str:
    """Contra la inyección de fórmulas: una celda de texto que empieza con
    `=`, `+`, `-`, `@` o un tabulador la ejecutaría Excel al abrirla."""
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def a_csv(filas: List[dict], idioma: str) -> bytes:
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow(encabezados(idioma))
    for f in filas:
        escritor.writerow([
            ("" if f.get(c[0]) is None else
             (str(f[c[0]]) if c[0] in NUMERICAS or c[0] == "id" else _sin_formula(str(f[c[0]]))))
            for c in COLUMNAS])
    # Con BOM: Excel abre así el UTF-8 sin destrozar los acentos.
    return ("﻿" + salida.getvalue()).encode("utf-8")


_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _columna(n: int) -> str:
    letras = ""
    while n:
        n, r = divmod(n - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def a_xlsx(filas: List[dict], idioma: str, hoja: str = "Gastos") -> bytes:
    """Un .xlsx de verdad, escrito a mano: el backend no trae ninguna
    biblioteca de hojas de cálculo y no hace falta una para una tabla.

    Números como números (con dos decimales y separador de miles), el
    encabezado en negritas, la primera fila fija y el autofiltro puesto.
    """
    def celda_texto(ref, texto, estilo=0):
        texto = escape(_CONTROL.sub("", texto))
        s = f' s="{estilo}"' if estilo else ""
        return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{texto}</t></is></c>'

    filas_xml = []
    cab = "".join(celda_texto(f"{_columna(i + 1)}1", t, 1) for i, t in enumerate(encabezados(idioma)))
    filas_xml.append(f'<row r="1">{cab}</row>')
    for r, f in enumerate(filas, start=2):
        celdas = []
        for i, c in enumerate(COLUMNAS):
            ref = f"{_columna(i + 1)}{r}"
            valor = f.get(c[0])
            if valor is None or valor == "":
                continue
            if c[0] in NUMERICAS or c[0] == "id":
                estilo = 2 if c[0] in NUMERICAS - {"cantidad", "tipo_cambio"} else 0
                s = f' s="{estilo}"' if estilo else ""
                celdas.append(f'<c r="{ref}"{s}><v>{valor}</v></c>')
            else:
                celdas.append(celda_texto(ref, str(valor)))
        filas_xml.append(f'<row r="{r}">{"".join(celdas)}</row>')
    ultima = f"{_columna(len(COLUMNAS))}{max(1, len(filas) + 1)}"
    hoja_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<cols><col min="4" max="4" width="42" customWidth="1"/>'
        '<col min="6" max="6" width="28" customWidth="1"/></cols>'
        f'<sheetData>{"".join(filas_xml)}</sheetData>'
        f'<autoFilter ref="A1:{ultima}"/>'
        '</worksheet>'
    )
    estilos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
        '</styleSheet>'
    )
    libro = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(hoja[:31])}" sheetId="1" r:id="rId1"/></sheets>'
        f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
        f"'{escape(hoja[:31])}'!$A$1:${_columna(len(COLUMNAS))}${max(1, len(filas) + 1)}"
        '</definedName></definedNames></workbook>'
    )
    tipos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    rels_libro = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/styles" Target="styles.xml"/></Relationships>'
    )
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", libro)
        z.writestr("xl/_rels/workbook.xml.rels", rels_libro)
        z.writestr("xl/styles.xml", estilos)
        z.writestr("xl/worksheets/sheet1.xml", hoja_xml)
    return salida.getvalue()
