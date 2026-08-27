"""Generación del PDF del resguardo.

El PDF es lo que se imprime, se firma a mano cuando hace falta y se archiva.
Se genera al vuelo desde los datos actuales: no se guarda en disco porque
siempre se puede reconstruir, y guardarlo obligaría a mantener sincronizadas
dos versiones del mismo documento.

Si el resguardo ya está firmado en el portal, el PDF lo hace constar con el
nombre, la fecha y la IP. Si no, lleva línea para firma de puño y letra.
"""

import io
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.services.horario_service import a_hora_local

AZUL = colors.HexColor("#0A3D62")
GRIS = colors.HexColor("#6B7280")
GRIS_CLARO = colors.HexColor("#F3F4F6")


def _estilos():
    hojas = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "titulo", parent=hojas["Title"], fontSize=16, textColor=AZUL,
            spaceAfter=2, alignment=TA_CENTER,
        ),
        "subtitulo": ParagraphStyle(
            "subtitulo", parent=hojas["Normal"], fontSize=9.5, textColor=GRIS,
            alignment=TA_CENTER, spaceAfter=10,
        ),
        "seccion": ParagraphStyle(
            "seccion", parent=hojas["Heading2"], fontSize=10.5, textColor=AZUL,
            spaceBefore=9, spaceAfter=5,
        ),
        "normal": ParagraphStyle(
            "normal", parent=hojas["Normal"], fontSize=9, leading=13,
        ),
        "condicion": ParagraphStyle(
            "condicion", parent=hojas["Normal"], fontSize=7.8, leading=10.5,
            alignment=TA_JUSTIFY, spaceAfter=3.5,
        ),
        "pie": ParagraphStyle(
            "pie", parent=hojas["Normal"], fontSize=7.5, textColor=GRIS,
            alignment=TA_CENTER,
        ),
    }


def _fecha(valor: Optional[datetime]) -> str:
    """Fecha en hora de la planta, legible para quien firma."""
    if not valor:
        return "—"
    local = a_hora_local(valor)
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    return f"{local.day} de {meses[local.month - 1]} de {local.year}, {local.strftime('%H:%M')} h"


def _tabla_datos(filas):
    tabla = Table(filas, colWidths=[42 * mm, 128 * mm])
    tabla.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), GRIS),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#E5E7EB")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
    ]))
    return tabla


def generar_pdf_resguardo(resguardo, equipo, usuario, sitio, emisor) -> bytes:
    """Devuelve el PDF del resguardo como bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=13 * mm, bottomMargin=13 * mm,
        title=f"Resguardo {resguardo.folio}",
        author="Portal de Tickets TI — CGR de México",
    )
    e = _estilos()
    partes = []

    # --- Encabezado ---
    partes.append(Paragraph("RESGUARDO DE EQUIPO", e["titulo"]))
    partes.append(Paragraph(
        f"CGR de México · {sitio.nombre if sitio else 'Planta'} · Folio <b>{resguardo.folio}</b>",
        e["subtitulo"]))

    # --- Resguardante ---
    partes.append(Paragraph("DATOS DEL RESGUARDANTE", e["seccion"]))
    partes.append(_tabla_datos([
        ["Nombre", usuario.nombre],
        ["Correo", usuario.email],
        ["Área", usuario.area or "—"],
        ["Sitio", sitio.nombre if sitio else "—"],
    ]))

    # --- Equipo ---
    partes.append(Paragraph("DATOS DEL EQUIPO", e["seccion"]))
    partes.append(_tabla_datos([
        ["Tipo", f"{equipo.tipo.capitalize()} · {equipo.categoria}"],
        ["Marca y modelo", f"{equipo.marca} {equipo.modelo}"],
        ["Número de serie", equipo.numero_serie or "No especificado"],
        ["Ubicación", equipo.ubicacion or "—"],
        ["Accesorios", resguardo.accesorios or "Ninguno declarado"],
        ["Fecha de entrega", _fecha(resguardo.entregado_en)],
    ]))

    if resguardo.observaciones_entrega:
        partes.append(Paragraph("OBSERVACIONES DE ENTREGA", e["seccion"]))
        partes.append(Paragraph(resguardo.observaciones_entrega, e["normal"]))

    # --- Condiciones ---
    partes.append(Paragraph("CONDICIONES DEL RESGUARDO", e["seccion"]))
    for parrafo in (resguardo.condiciones or "").split("\n\n"):
        limpio = " ".join(parrafo.split())
        if limpio:
            partes.append(Paragraph(limpio, e["condicion"]))

    # --- Firma ---
    partes.append(Spacer(1, 6 * mm))

    if resguardo.estado == "firmado" and resguardo.firmado_en:
        # Aceptado en el portal: se hace constar el rastro.
        constancia = Table([[Paragraph(
            "<b>ACEPTADO ELECTRÓNICAMENTE EN EL PORTAL</b><br/><br/>"
            f"Nombre capturado: <b>{resguardo.firma_nombre}</b><br/>"
            f"Fecha y hora: {_fecha(resguardo.firmado_en)}<br/>"
            f"Dirección IP de origen: {resguardo.firma_ip or 'no registrada'}<br/>"
            f"Cuenta: {usuario.email}",
            e["normal"])]], colWidths=[170 * mm])
        constancia.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GRIS_CLARO),
            ("BOX", (0, 0), (-1, -1), 0.6, AZUL),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        partes.append(KeepTogether(constancia))
    else:
        # Aún sin firmar: líneas para hacerlo a mano.
        firmas = Table([
            ["_" * 38, "_" * 38],
            [usuario.nombre, emisor.nombre if emisor else "Área de TI"],
            ["Recibe de conformidad", "Entrega por parte de TI"],
        ], colWidths=[85 * mm, 85 * mm])
        firmas.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 2), (-1, 2), GRIS),
            ("TOPPADDING", (0, 1), (-1, 1), 4),
        ]))
        partes.append(KeepTogether(firmas))

    # --- Devolución ---
    if resguardo.estado == "devuelto":
        partes.append(Spacer(1, 8 * mm))
        partes.append(Paragraph("CONSTANCIA DE DEVOLUCIÓN", e["seccion"]))
        partes.append(_tabla_datos([
            ["Fecha de devolución", _fecha(resguardo.devuelto_en)],
            ["Observaciones", resguardo.observaciones_devolucion or "Sin observaciones"],
        ]))

    # --- Pie ---
    partes.append(Spacer(1, 8 * mm))
    generado = a_hora_local(datetime.utcnow()).strftime("%d/%m/%Y %H:%M")
    partes.append(Paragraph(
        f"Documento generado por el Portal de Tickets TI el {generado} h · "
        f"Folio {resguardo.folio} · Estado: {resguardo.estado.replace('_', ' ')}",
        e["pie"]))

    doc.build(partes)
    return buffer.getvalue()


def generar_carta_no_adeudo(usuario, sitio, emisor, resguardos_abiertos, tickets_abiertos,
                            equipos_a_cargo) -> bytes:
    """Constancia de qué tiene (o ya no tiene) una persona a su cargo.

    Se genera al dar de baja a alguien. Tiene dos caras según el estado real:

      - **Sin pendientes**: es una carta de no adeudo. Se firma y se archiva.
      - **Con pendientes**: NO se emite como "no adeudo" —eso sería falso—; se
        emite como relación de pendientes, que es lo que hay que resolver antes
        de que la persona salga.

    Mentir aquí es peor que no tener el documento: se firmaría una constancia de
    que no debe nada alguien que sí tiene una laptop sin devolver.
    """
    buffer = io.BytesIO()
    hay_pendientes = bool(resguardos_abiertos or tickets_abiertos or equipos_a_cargo)

    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=("Relación de pendientes" if hay_pendientes else "Carta de no adeudo"),
        author="Portal de Tickets TI — CGR de México",
    )
    e = _estilos()
    partes = []

    partes.append(Paragraph(
        "RELACIÓN DE PENDIENTES" if hay_pendientes else "CARTA DE NO ADEUDO",
        e["titulo"]))
    partes.append(Paragraph(
        f"Área de TI · CGR de México · {sitio.nombre if sitio else 'Planta'}",
        e["subtitulo"]))

    partes.append(Paragraph("DATOS DE LA PERSONA", e["seccion"]))
    partes.append(_tabla_datos([
        ["Nombre", usuario.nombre],
        ["Correo", usuario.email],
        ["Área", usuario.area or "—"],
        ["Fecha de emisión", _fecha(datetime.utcnow())],
    ]))

    if not hay_pendientes:
        partes.append(Spacer(1, 6 * mm))
        partes.append(Paragraph(
            "El área de Tecnologías de la Información hace constar que a la fecha de "
            "emisión de este documento, la persona señalada <b>no tiene equipos de "
            "cómputo, telefonía ni accesorios bajo su resguardo</b>, no mantiene "
            "resguardos abiertos y no tiene incidencias pendientes de atención en el "
            "Portal de Tickets.",
            e["normal"]))
        partes.append(Spacer(1, 4 * mm))
        partes.append(Paragraph(
            "Se extiende la presente para los fines administrativos que convengan al "
            "interesado.", e["normal"]))
    else:
        partes.append(Spacer(1, 5 * mm))
        partes.append(Paragraph(
            "<b>Este documento NO constituye una carta de no adeudo.</b> A la fecha de "
            "emisión, la persona señalada mantiene los siguientes pendientes con el "
            "área de TI, que deben resolverse antes de expedir la constancia "
            "correspondiente:", e["normal"]))

        if equipos_a_cargo:
            partes.append(Paragraph("EQUIPOS BAJO SU RESGUARDO", e["seccion"]))
            filas = [["Equipo", "Serie / Ubicación"]]
            for eq in equipos_a_cargo:
                filas.append([
                    f"{eq.marca} {eq.modelo}",
                    f"{eq.numero_serie or 'sin serie'} · {eq.ubicacion or 'sin ubicación'}",
                ])
            partes.append(_tabla_datos(filas[1:]) if len(filas) > 1 else Spacer(1, 1))

        if resguardos_abiertos:
            partes.append(Paragraph("RESGUARDOS SIN CERRAR", e["seccion"]))
            partes.append(_tabla_datos([
                [r.folio, f"{r.estado.replace('_', ' ')} · desde {_fecha(r.entregado_en)}"]
                for r in resguardos_abiertos
            ]))

        if tickets_abiertos:
            partes.append(Paragraph("INCIDENCIAS ABIERTAS", e["seccion"]))
            partes.append(_tabla_datos([
                [t.folio, f"{t.categoria} · {t.estado.replace('_', ' ')}"]
                for t in tickets_abiertos
            ]))

    partes.append(Spacer(1, 12 * mm))
    firmas = Table([
        ["_" * 36, "_" * 36],
        [usuario.nombre, emisor.nombre if emisor else "Área de TI"],
        ["Enterado", "Por el área de TI"],
    ], colWidths=[80 * mm, 80 * mm])
    firmas.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 2), (-1, 2), GRIS),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
    ]))
    partes.append(KeepTogether(firmas))

    partes.append(Spacer(1, 8 * mm))
    generado = a_hora_local(datetime.utcnow()).strftime("%d/%m/%Y %H:%M")
    partes.append(Paragraph(
        f"Documento generado por el Portal de Tickets TI el {generado} h. "
        "Su validez depende de la información registrada en el portal a esa fecha.",
        e["pie"]))

    doc.build(partes)
    return buffer.getvalue()
