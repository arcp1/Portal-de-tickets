"""Gastos de TI: las cuentas, el CFDI, el expediente, el presupuesto y la
bitácora. Cada prueba de cuentas lleva el caso con el que fallaba el original
(«Gastos TI», Node): coma flotante, IVA fijo, retenciones ignoradas, dólares
sumados como pesos, la misma factura dos veces, el presupuesto entre doce.
"""

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from PIL import Image

from app.core.config import settings
from app.models import Auditoria, Equipo, Gasto, GastoComprobante, Ticket, Usuario
from app.services import gastos_service as srv
from app.services.directorio_service import ArchivoRechazado

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
UUID = "6F3E2C1A-1B2C-4D5E-8F90-ABCDEF123456"


def cfdi(uuid=UUID, moneda="MXN", tipo_cambio=None, subtotal="10000.00", iva="1600.00",
         retenido_isr="1000.00", retenido_iva="1066.67", total="9533.33", tipo="I",
         rfc="ABC010203XY1", extra=""):
    cambio = f' TipoCambio="{tipo_cambio}"' if tipo_cambio else ""
    retenciones = ""
    if retenido_isr or retenido_iva:
        suma = Decimal(retenido_isr or 0) + Decimal(retenido_iva or 0)
        retenciones = (f' TotalImpuestosRetenidos="{suma}"', (
            f'<cfdi:Retenciones><cfdi:Retencion Impuesto="001" Importe="{retenido_isr}"/>'
            f'<cfdi:Retencion Impuesto="002" Importe="{retenido_iva}"/></cfdi:Retenciones>'))
    else:
        retenciones = ("", "")
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>{extra}'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
        'xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" Version="4.0" Serie="A" Folio="1234" '
        f'Fecha="2026-03-10T10:20:30" SubTotal="{subtotal}" Moneda="{moneda}"{cambio} Total="{total}" '
        f'TipoDeComprobante="{tipo}">'
        f'<cfdi:Emisor Rfc="{rfc}" Nombre="Consultores de Redes SA de CV" RegimenFiscal="601"/>'
        '<cfdi:Receptor Rfc="CGR990101AB1" Nombre="CGR" UsoCFDI="G03"/>'
        '<cfdi:Conceptos><cfdi:Concepto Descripcion="Configuración de firewall" Importe="10000.00"/>'
        '<cfdi:Concepto Descripcion="Soporte remoto" Importe="0.00"/></cfdi:Conceptos>'
        f'<cfdi:Impuestos TotalImpuestosTrasladados="{iva}"{retenciones[0]}>{retenciones[1]}'
        f'<cfdi:Traslados><cfdi:Traslado Base="{subtotal}" Impuesto="002" TipoFactor="Tasa" '
        f'TasaOCuota="0.160000" Importe="{iva}"/></cfdi:Traslados></cfdi:Impuestos>'
        f'<cfdi:Complemento><tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}"/></cfdi:Complemento>'
        '</cfdi:Comprobante>'
    ).encode("utf-8")


def cab(client, quien="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": quien, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def catalogos(client):
    return client.get("/api/gastos/catalogos", headers=cab(client)).json()


def categoria(client, nombre="Licencias y software"):
    return next(c["id"] for c in catalogos(client)["categorias"] if c["nombre"] == nombre)


def nuevo(client, **datos):
    cuerpo = {"fecha": "2026-03-10", "concepto": "Licencias de antivirus", "categoria_id": categoria(client),
              "total": "1160.00", "tasa_iva": "0.16", **datos}
    r = client.post("/api/gastos", json=cuerpo, headers=cab(client))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def categorias_sembradas(db_session):
    """La migración siembra las ocho categorías; la suite crea las tablas con
    `create_all`, así que se siembran aquí igual."""
    from app.models import GastoCategoria
    for n in ("Arrendamiento de equipo", "Telefonía y líneas", "Internet y enlaces", "Licencias y software",
              "Hardware y refacciones", "Mantenimiento del site", "Servicios profesionales", "Otros"):
        db_session.add(GastoCategoria(nombre=n))
    db_session.commit()


pytestmark = pytest.mark.usefixtures("categorias_sembradas")


# ----------------------------------------------------------------------
# Las cuentas
# ----------------------------------------------------------------------

def test_con_el_total_iva_incluido_la_suma_da_exacto_el_total():
    # 86.21 + 13.79 en coma flotante es 100.00000000000001.
    r = srv.calcular_importes(subtotal=None, total=Decimal("100"), tasa_iva=Decimal("0.16"))
    assert r == {"subtotal": Decimal("86.21"), "iva": Decimal("13.79"), "retenciones": Decimal("0.00"),
                 "total": Decimal("100.00")}
    assert r["subtotal"] + r["iva"] == r["total"]


def test_iva_de_frontera_y_exento():
    assert srv.calcular_importes(subtotal=Decimal("1000"), total=None, tasa_iva=Decimal("0.08"))["total"] == Decimal("1080.00")
    assert srv.calcular_importes(subtotal=Decimal("1000"), total=None, tasa_iva=Decimal("0"))["iva"] == Decimal("0.00")


def test_el_redondeo_es_la_mitad_hacia_arriba():
    # 0.125 × 0.16 = 0.02 exacto; 10.03 × 0.16 = 1.6048 → 1.60; 10.05 × 0.16 = 1.608 → 1.61
    assert srv.calcular_importes(subtotal=Decimal("10.05"), total=None, tasa_iva=Decimal("0.16"))["iva"] == Decimal("1.61")
    assert srv.centavos(Decimal("2.675")) == Decimal("2.68")  # en float, round(2.675, 2) es 2.67


def test_las_retenciones_cuadran_el_total():
    r = srv.calcular_importes(subtotal=Decimal("10000"), total=None, tasa_iva=Decimal("0.16"),
                              retenciones=Decimal("2066.67"))
    assert r["total"] == Decimal("9533.33")
    # Y desde el total pagado, con las mismas retenciones, se vuelve al mismo subtotal.
    r2 = srv.calcular_importes(subtotal=None, total=Decimal("9533.33"), tasa_iva=Decimal("0.16"),
                               retenciones=Decimal("2066.67"))
    assert r2["subtotal"] == Decimal("10000.00") and r2["iva"] == Decimal("1600.00")


def test_retenciones_mayores_que_el_importe_no_pasan():
    with pytest.raises(srv.ImporteInvalido):
        srv.calcular_importes(subtotal=Decimal("100"), total=None, tasa_iva=Decimal("0"), retenciones=Decimal("200"))


def test_el_presupuesto_se_prorratea_por_dias():
    assert srv.fraccion_del_anio(2026, date(2026, 12, 31)) == 1
    assert srv.fraccion_del_anio(2025, date(2026, 1, 5)) == 1
    assert srv.fraccion_del_anio(2027, date(2026, 6, 1)) == 0
    assert abs(float(srv.fraccion_del_anio(2026, date(2026, 7, 2))) - 183 / 365) < 1e-9


# ----------------------------------------------------------------------
# CFDI
# ----------------------------------------------------------------------

def test_lee_un_cfdi_con_retenciones_exacto():
    d = srv.leer_cfdi(cfdi())
    assert d["uuid"] == UUID and d["folio"] == "A-1234" and d["fecha"] == "2026-03-10"
    assert d["emisor_rfc"] == "ABC010203XY1" and d["concepto"] == "Configuración de firewall (+1)"
    assert (d["subtotal"], d["iva"], d["retenciones"], d["total"]) == (
        Decimal("10000.00"), Decimal("1600.00"), Decimal("2066.67"), Decimal("9533.33"))
    assert d["tasa_iva"] == Decimal("0.16") and d["avisos"] == []


def test_un_cfdi_en_dolares_trae_su_tipo_de_cambio():
    d = srv.leer_cfdi(cfdi(moneda="USD", tipo_cambio="18.50", subtotal="100.00", iva="16.00",
                           retenido_isr="", retenido_iva="", total="116.00"))
    assert d["moneda"] == "USD" and d["tipo_cambio"] == Decimal("18.50") and d["total"] == Decimal("116.00")


def test_nota_de_credito_y_complemento_de_pago_avisan():
    assert "nota_de_credito" in srv.leer_cfdi(cfdi(tipo="E"))["avisos"]
    assert "complemento_de_pago" in srv.leer_cfdi(cfdi(tipo="P"))["avisos"]


@pytest.mark.parametrize("contenido", [
    cfdi(extra='<!DOCTYPE x [<!ENTITY a "aaaaaaaa">]>'),
    b"<?xml version='1.0'?><factura/>",
    b"no es xml",
    b"\x00\x01binario",
])
def test_lo_que_no_es_un_cfdi_limpio_se_rechaza(contenido):
    with pytest.raises(ArchivoRechazado):
        srv.leer_cfdi(contenido)


def test_analizar_un_cfdi_llena_el_formulario_y_avisa_si_ya_esta(client, db_session):
    r = client.post("/api/gastos/cfdi/analizar", files={"archivo": ("factura.xml", cfdi(), "text/xml")},
                    headers=cab(client))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 9533.33 and d["retenciones"] == 2066.67 and d["duplicado"] is None
    assert d["proveedor_id"] is None and d["proveedor_nombre"] == "Consultores de Redes SA de CV"

    g = nuevo(client, proveedor_nombre=d["proveedor_nombre"], proveedor_rfc=d["emisor_rfc"],
              categoria_id=categoria(client, "Servicios profesionales"),
              subtotal="10000.00", iva="1600.00", retenciones="2066.67", total=None)
    sube = client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "factura"},
                       files={"archivo": ("factura.xml", cfdi(), "text/xml")}, headers=cab(client))
    assert sube.status_code == 201, sube.text
    d = client.post("/api/gastos/cfdi/analizar", files={"archivo": ("factura.xml", cfdi(), "text/xml")},
                    headers=cab(client)).json()
    assert d["duplicado"]["gasto_id"] == g["id"]
    # El proveedor ya existe y se propone su categoría de siempre.
    assert d["proveedor_id"] == g["proveedor"]["id"]
    assert d["categoria_id"] == categoria(client, "Servicios profesionales")


def test_analizar_solo_acepta_xml(client):
    r = client.post("/api/gastos/cfdi/analizar", files={"archivo": ("factura.pdf", PDF, "application/pdf")},
                    headers=cab(client))
    assert r.status_code == 422


# ----------------------------------------------------------------------
# Registro
# ----------------------------------------------------------------------

def test_solo_ti_entra_al_modulo(client):
    usuario = cab(client, "user@test.com")
    assert client.get("/api/gastos", headers=usuario).status_code == 403
    assert client.get("/api/gastos/resumen", headers=usuario).status_code == 403
    assert client.get("/api/gastos/catalogos", headers=usuario).status_code == 403


def test_alta_calcula_importes_y_deja_constancia(client, db_session):
    g = nuevo(client)
    assert (g["subtotal"], g["iva"], g["total"], g["total_mxn"]) == (1000.0, 160.0, 1160.0, 1160.0)
    assert g["estado"] == "pendiente" and g["fecha_pago"] is None
    assert g["expediente"] == {"hechas": 0, "total": 4, "completo": False,
                               "faltan": ["cotizacion", "orden_compra", "factura", "albaran"], "pago": False}
    fila = db_session.query(Auditoria).filter(Auditoria.accion == "gasto.creado").one()
    assert fila.entidad == "gasto" and fila.entidad_id == g["id"] and fila.detalle["total"] == "1160.00"


def test_un_gasto_en_dolares_se_suma_en_pesos(client):
    g = nuevo(client, moneda="USD", tipo_cambio="18.5", total="116.00")
    assert g["total"] == 116.0 and g["total_mxn"] == 2146.0
    lista = client.get("/api/gastos", params={"anio": 2026}, headers=cab(client)).json()
    assert lista["suma_mxn"] == 2146.0


def test_en_dolares_sin_tipo_de_cambio_no_pasa(client):
    r = client.post("/api/gastos", json={"fecha": "2026-03-10", "concepto": "x", "categoria_id": categoria(client),
                                         "total": "10", "moneda": "USD"}, headers=cab(client))
    assert r.status_code == 422


@pytest.mark.parametrize("cambio", [{"tasa_iva": "0.15"}, {"total": "10.001"}, {"total": "-5"},
                                    {"fecha": "1999-12-31"}, {"subtotal": None, "total": None}])
def test_datos_imposibles_se_rechazan(client, cambio):
    cuerpo = {"fecha": "2026-03-10", "concepto": "x", "categoria_id": categoria(client), "total": "10", **cambio}
    assert client.post("/api/gastos", json=cuerpo, headers=cab(client)).status_code == 422


def test_pagado_sin_fecha_toma_la_del_gasto(client):
    g = nuevo(client, estado="pagado")
    assert g["estado"] == "pagado" and g["fecha_pago"] == "2026-03-10"


def test_se_vincula_a_planta_activo_ticket_y_responsable(client, db_session):
    planta = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one().sitio_id
    equipo = Equipo(sitio_id=planta, tipo="activo", categoria="laptop", marca="Dell", modelo="Latitude 5440",
                    numero_serie="SN-123")
    db_session.add(equipo)
    db_session.commit()
    admin = db_session.query(Usuario).filter(Usuario.email == "admin@test.com").one()
    g = nuevo(client, equipo_id=equipo.id, responsable_id=admin.id,
              categoria_id=categoria(client, "Hardware y refacciones"))
    # Sin planta, la del activo.
    assert g["planta"]["id"] == planta and g["equipo"]["etiqueta"] == "Dell Latitude 5440 · SN-123"
    assert g["responsable"]["nombre"] == "Admin Test"
    hallados = client.get("/api/gastos/vinculos", params={"tipo": "equipo", "q": "SN-1"}, headers=cab(client)).json()
    assert [h["id"] for h in hallados] == [equipo.id]
    por_activo = client.get("/api/gastos", params={"equipo_id": equipo.id}, headers=cab(client)).json()
    assert por_activo["total"] == 1


def test_el_responsable_tiene_que_ser_de_ti(client, db_session):
    usuario = db_session.query(Usuario).filter(Usuario.email == "user@test.com").one()
    r = client.post("/api/gastos", json={"fecha": "2026-03-10", "concepto": "x", "categoria_id": categoria(client),
                                         "total": "10", "responsable_id": usuario.id}, headers=cab(client))
    assert r.status_code == 422


def test_editar_anota_lo_que_cambio_y_pagar_tambien(client, db_session):
    g = nuevo(client)
    cuerpo = {"fecha": "2026-03-10", "concepto": "Licencias de antivirus (renovación)",
              "categoria_id": g["categoria"]["id"], "total": "1500.00", "tasa_iva": "0.16"}
    r = client.put(f"/api/gastos/{g['id']}", json=cuerpo, headers=cab(client))
    assert r.status_code == 200 and r.json()["total"] == 1500.0
    fila = db_session.query(Auditoria).filter(Auditoria.accion == "gasto.editado").one()
    assert fila.detalle["cambios"]["total"] == {"antes": "1160.00", "despues": "1500.00"}
    assert "concepto" in fila.detalle["cambios"]
    r = client.post(f"/api/gastos/{g['id']}/pagar", json={"fecha_pago": "2026-04-01"}, headers=cab(client))
    assert r.json()["estado"] == "pagado" and r.json()["fecha_pago"] == "2026-04-01"
    historial = client.get(f"/api/gastos/{g['id']}", headers=cab(client)).json()["historial"]
    assert [h["accion"] for h in historial] == ["gasto.pagado", "gasto.editado", "gasto.creado"]


def test_proveedores_sin_duplicados_por_mayusculas_y_con_rfc_valido(client):
    a = nuevo(client, proveedor_nombre="Telcel")
    b = nuevo(client, proveedor_nombre="TELCEL")
    assert a["proveedor"]["id"] == b["proveedor"]["id"]
    assert client.post("/api/gastos/proveedores", json={"nombre": "telcel"}, headers=cab(client)).status_code == 409
    assert client.post("/api/gastos/proveedores", json={"nombre": "Otro", "rfc": "123"},
                       headers=cab(client)).status_code == 422
    # Con gastos no se borra.
    assert client.delete(f"/api/gastos/proveedores/{a['proveedor']['id']}", headers=cab(client)).status_code == 409


def test_buscar_encuentra_por_proveedor_y_por_folio(client):
    g = nuevo(client, proveedor_nombre="Papelería Central")
    nuevo(client, concepto="Toner")
    client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "cotizacion", "folio": "COT-77"},
                files={"archivo": ("cot.pdf", PDF, "application/pdf")}, headers=cab(client))
    assert client.get("/api/gastos", params={"q": "papeler"}, headers=cab(client)).json()["total"] == 1
    assert client.get("/api/gastos", params={"q": "COT-77"}, headers=cab(client)).json()["total"] == 1
    assert client.get("/api/gastos", params={"mes": 4}, headers=cab(client)).json()["total"] == 0


# ----------------------------------------------------------------------
# Comprobantes
# ----------------------------------------------------------------------

def test_el_expediente_avanza_y_el_xml_sale_como_descarga(client, db_session):
    g = nuevo(client, subtotal="10000.00", iva="1600.00", retenciones="2066.67", total=None)
    for tipo in ("cotizacion", "orden_compra", "albaran"):
        r = client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": tipo},
                        files={"archivo": (f"{tipo}.pdf", PDF, "application/pdf")}, headers=cab(client))
        assert r.status_code == 201, r.text
    r = client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "factura"},
                    files={"archivo": ("factura.xml", cfdi(), "application/xml")}, headers=cab(client))
    assert r.status_code == 201, r.text
    c = r.json()["comprobante"]
    assert c["cfdi_uuid"] == UUID and c["folio"] == "A-1234" and c["fecha"] == "2026-03-10"
    assert r.json()["gasto"]["expediente"]["completo"] is True and r.json()["avisos"] == []
    # El binario vive en documentos/gastos con un nombre que no es el suyo.
    fila = db_session.get(GastoComprobante, c["id"])
    assert (srv.carpeta_en_disco() / fila.nombre_guardado).exists()
    baja = client.get(f"/api/gastos/comprobantes/{c['id']}/descarga", headers=cab(client))
    assert baja.status_code == 200 and baja.headers["content-disposition"].startswith("attachment")
    assert baja.headers["x-content-type-options"] == "nosniff"
    pdf = db_session.query(GastoComprobante).filter(GastoComprobante.tipo == "cotizacion").one()
    en_linea = client.get(f"/api/gastos/comprobantes/{pdf.id}/descarga", headers=cab(client))
    assert en_linea.headers["content-disposition"].startswith("inline")


def test_la_misma_factura_no_entra_dos_veces(client):
    a, b = nuevo(client), nuevo(client)
    ok = client.post(f"/api/gastos/{a['id']}/comprobantes", data={"tipo": "factura"},
                     files={"archivo": ("f.xml", cfdi(), "application/xml")}, headers=cab(client))
    assert ok.status_code == 201
    otra = client.post(f"/api/gastos/{b['id']}/comprobantes", data={"tipo": "factura"},
                       files={"archivo": ("f.xml", cfdi(), "application/xml")}, headers=cab(client))
    assert otra.status_code == 409 and f"#{a['id']}" in otra.json()["detail"]
    # Y no deja el archivo rechazado en el disco.
    assert len(list(srv.carpeta_en_disco().iterdir())) == 1


def test_una_factura_que_no_cuadra_con_el_gasto_avisa(client):
    g = nuevo(client, total="500.00")
    r = client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "factura"},
                    files={"archivo": ("f.xml", cfdi(), "application/xml")}, headers=cab(client))
    assert r.status_code == 201 and "total_distinto" in r.json()["avisos"]


@pytest.mark.parametrize("nombre,contenido", [
    ("factura.pdf", b"<html><script>alert(1)</script></html>"),
    ("foto.jpg", PDF),
    ("programa.exe", b"MZ\x90\x00"),
    ("pagina.html", b"<html></html>"),
    ("falso.xml", b"<?xml version='1.0'?><html/>"),
])
def test_lo_que_no_es_lo_que_dice_no_entra(client, nombre, contenido):
    g = nuevo(client)
    r = client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "factura"},
                    files={"archivo": (nombre, contenido, "application/pdf")}, headers=cab(client))
    assert r.status_code == 422, r.text
    assert list(srv.carpeta_en_disco().iterdir()) == []


def test_la_foto_de_un_recibo_se_guarda_sin_gps(client, db_session):
    exif = Image.Exif()
    exif[0x010F] = "CamaraSecreta"
    exif[0x8825] = {1: "N", 2: (20.0, 35.0, 12.0), 3: "W", 4: (100.0, 23.0, 1.0)}
    salida = io.BytesIO()
    Image.new("RGB", (16, 12), (200, 30, 30)).save(salida, "JPEG", exif=exif.tobytes())
    g = nuevo(client)
    r = client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "pago"},
                    files={"archivo": ("recibo.jpg", salida.getvalue(), "image/jpeg")}, headers=cab(client))
    assert r.status_code == 201, r.text
    fila = db_session.get(GastoComprobante, r.json()["comprobante"]["id"])
    with Image.open(srv.carpeta_en_disco() / fila.nombre_guardado) as im:
        assert 0x8825 not in im.getexif() and 0x010F not in im.getexif()
    # Un comprobante de pago marca el gasto como pagado.
    assert r.json()["gasto"]["estado"] == "pagado"


def test_el_tope_de_tamano_se_respeta(client, monkeypatch):
    monkeypatch.setattr(settings, "GASTOS_MAX_MB", 0)
    g = nuevo(client)
    r = client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "factura"},
                    files={"archivo": ("f.pdf", PDF, "application/pdf")}, headers=cab(client))
    assert r.status_code == 413


def test_borrar_el_gasto_borra_sus_archivos_pero_no_su_historia(client, db_session):
    g = nuevo(client)
    client.post(f"/api/gastos/{g['id']}/comprobantes", data={"tipo": "factura"},
                files={"archivo": ("f.xml", cfdi(), "application/xml")}, headers=cab(client))
    assert list(srv.carpeta_en_disco().iterdir())
    assert client.delete(f"/api/gastos/{g['id']}", headers=cab(client)).status_code == 200
    assert list(srv.carpeta_en_disco().iterdir()) == []
    assert db_session.query(Gasto).count() == 0
    acciones = [a.accion for a in db_session.query(Auditoria).filter(
        Auditoria.entidad == "gasto", Auditoria.entidad_id == g["id"]).order_by(Auditoria.id)]
    assert acciones == ["gasto.creado", "gasto.comprobante_subido", "gasto.borrado"]
    borrado = db_session.query(Auditoria).filter(Auditoria.accion == "gasto.borrado").one()
    assert borrado.detalle["comprobantes"][0]["uuid"] == UUID
    # La factura queda libre para otro gasto.
    otro = nuevo(client)
    assert client.post(f"/api/gastos/{otro['id']}/comprobantes", data={"tipo": "factura"},
                       files={"archivo": ("f.xml", cfdi(), "application/xml")},
                       headers=cab(client)).status_code == 201


# ----------------------------------------------------------------------
# Presupuesto, resumen y exportación
# ----------------------------------------------------------------------

def test_presupuesto_resumen_y_mes_mas_caro(client, db_session, monkeypatch):
    monkeypatch.setattr(srv, "hoy_local", lambda: date(2026, 7, 2))
    lic, hw = categoria(client), categoria(client, "Hardware y refacciones")
    r = client.put("/api/gastos/presupuesto/2026", json={"categorias": [
        {"categoria_id": lic, "monto": "120000"}, {"categoria_id": hw, "monto": "60000"}]}, headers=cab(client))
    assert r.status_code == 200 and r.json()["total"] == 180000.0
    assert db_session.query(Auditoria).filter(Auditoria.accion == "gasto_presupuesto.editado").count() == 1

    # Una licencia anual en enero: con «anual entre doce» salía como sobregiro.
    nuevo(client, fecha="2026-01-15", total="90000.00", proveedor_nombre="Microsoft")
    nuevo(client, fecha="2026-03-05", total="10000.00", categoria_id=hw, proveedor_nombre="Dell", estado="pagado")
    nuevo(client, fecha="2026-03-20", total="5000.00", categoria_id=hw, proveedor_nombre="Dell")
    nuevo(client, fecha="2025-01-10", total="50000.00")

    d = client.get("/api/gastos/resumen", params={"anio": 2026}, headers=cab(client)).json()
    t = d["totales"]
    assert t["gastado"] == 105000.0 and t["presupuesto"] == 180000.0 and t["disponible"] == 75000.0
    assert t["pendiente"] == 95000.0 and t["pagado"] == 10000.0
    assert t["prorrateado"] == round(180000 * 183 / 365, 2)
    assert t["anio_anterior"] == 50000.0
    assert d["mes_mas_caro"]["mes"] == 1 and d["mes_mas_caro"]["categoria"]["id"] == lic
    assert d["mes_mas_caro"]["mayor_gasto"]["total_mxn"] == 90000.0
    lic_fila = next(c for c in d["por_categoria"] if c["categoria_id"] == lic)
    assert lic_fila["consumo"] == 0.75
    marzo = d["meses"][2]
    assert marzo["total"] == 15000.0 and marzo["n"] == 2
    assert d["expediente"]["total"] == 3 and d["expediente"]["completos"] == 0

    # Con una planta elegida no se compara contra el presupuesto de toda TI.
    por_planta = client.get("/api/gastos/resumen", params={"anio": 2026, "sitio_id": 0}, headers=cab(client)).json()
    assert por_planta["con_presupuesto"] is False and por_planta["totales"]["presupuesto"] is None


def test_exportar_csv_sin_formulas_y_excel_de_verdad(client):
    nuevo(client, concepto="=HYPERLINK(\"http://malo\")", proveedor_nombre="+Proveedor")
    csv_ = client.get("/api/gastos/exportar", params={"anio": 2026, "formato": "csv"}, headers=cab(client))
    assert csv_.status_code == 200 and csv_.content.startswith("﻿".encode())
    texto = csv_.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in texto and "'+Proveedor" in texto and texto.splitlines()[0].startswith("ID,Fecha")
    assert csv_.headers["content-disposition"] == 'attachment; filename="gastos-ti-2026.csv"'

    xlsx = client.get("/api/gastos/exportar", params={"anio": 2026, "formato": "xlsx", "idioma": "en"},
                      headers=cab(client))
    assert xlsx.status_code == 200
    with zipfile.ZipFile(io.BytesIO(xlsx.content)) as z:
        hoja = z.read("xl/worksheets/sheet1.xml").decode()
        assert "[Content_Types].xml" in z.namelist()
    assert "Purchase type" in hoja and "<v>1160.00</v>" in hoja


def test_categorias_se_retiran_y_no_se_ofrecen(client):
    cid = categoria(client, "Otros")
    r = client.patch(f"/api/gastos/categorias/{cid}", json={"activa": False}, headers=cab(client))
    assert r.status_code == 200 and r.json()["activa"] is False
    r = client.post("/api/gastos", json={"fecha": "2026-03-10", "concepto": "x", "categoria_id": cid,
                                         "total": "10"}, headers=cab(client))
    assert r.status_code == 422
    # Darla de alta otra vez la devuelve, con su historia.
    r = client.post("/api/gastos/categorias", json={"nombre": "otros"}, headers=cab(client))
    assert r.status_code == 201 and r.json()["id"] == cid and r.json()["activa"] is True
