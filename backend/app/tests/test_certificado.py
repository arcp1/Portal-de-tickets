"""Vigilancia del certificado TLS.

Un certificado vencido no degrada nada: el navegador simplemente **no deja
entrar**. Y vence en silencio, un martes cualquiera, sin que nadie se entere
hasta que 300 personas no pueden trabajar.

Por eso se vigila desde la pantalla de Estado y no desde la memoria de alguien.
"""

import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.api.estado import _estado_certificado
from app.core.config import settings


def certificado(dias: int, ruta):
    """Escribe un certificado que vence en `dias` días."""
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "portal.cgr.local"),
    ])
    emisor = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "CGR Queretaro - Autoridad interna"),
    ])
    ahora = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(emisor)
        .public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        # Para un certificado ya vencido, el inicio tiene que ser todavia
        # mas viejo que el fin.
        .not_valid_before(ahora + datetime.timedelta(days=dias - 30))
        .not_valid_after(ahora + datetime.timedelta(days=dias))
        .sign(llave, hashes.SHA256())
    )
    ruta.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return ruta


def test_sin_certificado_se_dice_que_va_por_http(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "RUTA_CERTIFICADO", str(tmp_path / "no-existe.crt"))

    estado = _estado_certificado()

    assert estado["estado"] == "apagado"
    assert "claro" in estado["degradacion"]


def test_un_certificado_con_meses_por_delante_esta_bien(monkeypatch, tmp_path):
    ruta = certificado(200, tmp_path / "portal.crt")
    monkeypatch.setattr(settings, "RUTA_CERTIFICADO", str(ruta))

    estado = _estado_certificado()

    assert estado["estado"] == "arriba"
    assert estado["dias_restantes"] > 190
    assert "Autoridad interna" in estado["detalle"]


def test_avisa_antes_de_que_venza(monkeypatch, tmp_path):
    """El aviso llega con margen para renovarlo, no el día que deja de servir."""
    ruta = certificado(10, tmp_path / "portal.crt")
    monkeypatch.setattr(settings, "RUTA_CERTIFICADO", str(ruta))

    estado = _estado_certificado()

    assert estado["estado"] == "en_espera"
    assert estado["dias_restantes"] <= settings.CERTIFICADO_AVISO_DIAS


def test_un_certificado_vencido_sale_en_rojo(monkeypatch, tmp_path):
    ruta = certificado(-5, tmp_path / "portal.crt")
    monkeypatch.setattr(settings, "RUTA_CERTIFICADO", str(ruta))

    estado = _estado_certificado()

    assert estado["estado"] == "abajo"
    assert estado["dias_restantes"] < 0


def test_un_archivo_corrupto_no_tumba_la_pantalla(monkeypatch, tmp_path):
    """La pantalla de Estado no puede caerse justo cuando se la necesita."""
    ruta = tmp_path / "portal.crt"
    ruta.write_bytes(b"esto no es un certificado")
    monkeypatch.setattr(settings, "RUTA_CERTIFICADO", str(ruta))

    estado = _estado_certificado()

    assert estado["estado"] == "abajo"
    assert "No se pudo leer" in estado["detalle"]


def test_el_certificado_no_cuenta_como_critico(monkeypatch, tmp_path):
    """`critico` marca lo que impide atender. Sin TLS el portal atiende igual,
    solo que sin cifrar; el aviso va aparte."""
    ruta = certificado(200, tmp_path / "portal.crt")
    monkeypatch.setattr(settings, "RUTA_CERTIFICADO", str(ruta))

    assert _estado_certificado()["critico"] is False
