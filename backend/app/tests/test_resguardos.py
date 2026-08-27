"""Resguardos de equipo, movimientos y expediente.

Un resguardo es el documento que se pide en una auditoría de inventario, así
que tiene reglas más estrictas que un ticket: no se borra, las condiciones se
congelan al firmar, y nadie firma por otro.
"""

import io

import pytest

from app.models import Equipo, MovimientoEquipo, Resguardo


def token(client, email="admin@test.com", password="Secret123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


def cab(client, email="admin@test.com"):
    return {"Authorization": f"Bearer {token(client, email=email)}"}


@pytest.fixture
def equipo(db_session):
    eq = Equipo(sitio_id=1, tipo="activo", categoria="laptop", marca="HP",
                modelo="ProBook 440 G8", numero_serie="HP-TEST-001",
                ubicacion="Oficina TI", estado="disponible")
    db_session.add(eq)
    db_session.commit()
    db_session.refresh(eq)
    return eq


@pytest.fixture
def usuario(client):
    return client.get("/api/auth/me", headers=cab(client, "user@test.com")).json()


def emitir(client, equipo_id, usuario_id, **extra):
    payload = {"equipo_id": equipo_id, "usuario_id": usuario_id,
               "accesorios": "Cargador, funda y mouse"}
    payload.update(extra)
    return client.post("/api/resguardos", json=payload, headers=cab(client))


# ----------------------------------------------------------------------
# Emisión
# ----------------------------------------------------------------------
def test_emitir_un_resguardo(client, equipo, usuario):
    r = emitir(client, equipo.id, usuario["id"])

    assert r.status_code == 201
    datos = r.json()
    assert datos["folio"].startswith("RES-QRO-")
    assert datos["estado"] == "pendiente_firma"
    assert datos["accesorios"] == "Cargador, funda y mouse"
    # Las condiciones se copian al emitir, no se referencian.
    assert len(datos["condiciones"]) > 100


def test_emitir_deja_el_equipo_asignado(client, equipo, usuario, db_session):
    emitir(client, equipo.id, usuario["id"])

    db_session.refresh(equipo)
    assert equipo.asignado_a == usuario["id"]
    assert equipo.estado == "asignado"
    assert equipo.fecha_asignacion is not None


def test_emitir_registra_el_movimiento(client, equipo, usuario, db_session):
    emitir(client, equipo.id, usuario["id"])

    mov = db_session.query(MovimientoEquipo).filter(
        MovimientoEquipo.equipo_id == equipo.id,
        MovimientoEquipo.tipo == "asignacion",
    ).first()
    assert mov is not None
    assert mov.usuario_id == usuario["id"]
    assert mov.estado_nuevo == "asignado"


def test_un_equipo_no_puede_tener_dos_resguardos(client, equipo, usuario):
    """Un activo no puede estar bajo la responsabilidad de dos personas."""
    assert emitir(client, equipo.id, usuario["id"]).status_code == 201

    admin = client.get("/api/auth/me", headers=cab(client)).json()
    segundo = emitir(client, equipo.id, admin["id"])

    assert segundo.status_code == 409
    assert "vigente" in segundo.json()["detail"]


def test_no_se_resguarda_un_equipo_dado_de_baja(client, equipo, usuario, db_session):
    equipo.estado = "baja"
    db_session.commit()

    assert emitir(client, equipo.id, usuario["id"]).status_code == 422


def test_solo_ti_emite_resguardos(client, equipo, usuario):
    r = client.post("/api/resguardos",
                    json={"equipo_id": equipo.id, "usuario_id": usuario["id"]},
                    headers=cab(client, "user@test.com"))
    assert r.status_code == 403


# ----------------------------------------------------------------------
# Firma
# ----------------------------------------------------------------------
def test_el_resguardante_firma_lo_suyo(client, equipo, usuario):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    r = client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                    json={"nombre_completo": "Juan Pérez", "acepto": True},
                    headers=cab(client, "user@test.com"))

    assert r.status_code == 200
    assert r.json()["estado"] == "firmado"
    assert r.json()["firma_nombre"] == "Juan Pérez"
    assert r.json()["firmado_en"] is not None


def test_nadie_firma_por_otro(client, equipo, usuario):
    """Ni siquiera un admin: si pudiera, el documento no valdría nada."""
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    r = client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                    json={"nombre_completo": "Admin Test", "acepto": True},
                    headers=cab(client))

    assert r.status_code == 403


def test_hay_que_aceptar_las_condiciones(client, equipo, usuario):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    r = client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                    json={"nombre_completo": "Juan Pérez", "acepto": False},
                    headers=cab(client, "user@test.com"))
    assert r.status_code == 422


def test_no_se_firma_dos_veces(client, equipo, usuario):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()
    firma = {"nombre_completo": "Juan Pérez", "acepto": True}
    cabeceras = cab(client, "user@test.com")

    assert client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                       json=firma, headers=cabeceras).status_code == 200
    assert client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                       json=firma, headers=cabeceras).status_code == 422


def test_la_firma_deja_constancia_de_la_ip(client, equipo, usuario, db_session):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()
    client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                json={"nombre_completo": "Juan Pérez", "acepto": True},
                headers=cab(client, "user@test.com"))

    fila = db_session.query(Resguardo).filter(Resguardo.id == resguardo["id"]).first()
    assert fila.firma_ip is not None


# ----------------------------------------------------------------------
# Devolución
# ----------------------------------------------------------------------
def test_devolver_libera_el_equipo(client, equipo, usuario, db_session):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    r = client.post(f"/api/resguardos/{resguardo['id']}/devolver",
                    json={"observaciones": "Devuelto completo y en buen estado"},
                    headers=cab(client))

    assert r.status_code == 200
    assert r.json()["estado"] == "devuelto"
    db_session.refresh(equipo)
    assert equipo.asignado_a is None
    assert equipo.estado == "disponible"


def test_el_equipo_puede_volver_a_mantenimiento(client, equipo, usuario, db_session):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    client.post(f"/api/resguardos/{resguardo['id']}/devolver",
                json={"observaciones": "Llega con la pantalla estrellada",
                      "estado_equipo": "mantenimiento"},
                headers=cab(client))

    db_session.refresh(equipo)
    assert equipo.estado == "mantenimiento"


def test_devolver_no_borra_el_resguardo(client, equipo, usuario, db_session):
    """El historial de quién respondió por qué activo es el punto entero."""
    resguardo = emitir(client, equipo.id, usuario["id"]).json()
    client.post(f"/api/resguardos/{resguardo['id']}/devolver", json={}, headers=cab(client))

    fila = db_session.query(Resguardo).filter(Resguardo.id == resguardo["id"]).first()
    assert fila is not None
    assert fila.estado == "devuelto"
    assert fila.devuelto_en is not None


def test_tras_devolver_se_puede_resguardar_de_nuevo(client, equipo, usuario):
    primero = emitir(client, equipo.id, usuario["id"]).json()
    client.post(f"/api/resguardos/{primero['id']}/devolver", json={}, headers=cab(client))

    admin = client.get("/api/auth/me", headers=cab(client)).json()
    segundo = emitir(client, equipo.id, admin["id"])

    assert segundo.status_code == 201
    assert segundo.json()["folio"] != primero["folio"]


def test_solo_ti_registra_devoluciones(client, equipo, usuario):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    r = client.post(f"/api/resguardos/{resguardo['id']}/devolver",
                    json={}, headers=cab(client, "user@test.com"))
    assert r.status_code == 403


# ----------------------------------------------------------------------
# Cancelación
# ----------------------------------------------------------------------
def test_cancelar_un_resguardo_sin_firmar(client, equipo, usuario, db_session):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    r = client.post(f"/api/resguardos/{resguardo['id']}/cancelar",
                    json={"motivo": "Se emitió al usuario equivocado"},
                    headers=cab(client))

    assert r.status_code == 200
    assert r.json()["estado"] == "cancelado"
    db_session.refresh(equipo)
    assert equipo.estado == "disponible"


def test_no_se_cancela_uno_ya_firmado(client, equipo, usuario):
    """Uno firmado se cierra con devolución, que deja constancia."""
    resguardo = emitir(client, equipo.id, usuario["id"]).json()
    client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                json={"nombre_completo": "Juan Pérez", "acepto": True},
                headers=cab(client, "user@test.com"))

    r = client.post(f"/api/resguardos/{resguardo['id']}/cancelar",
                    json={"motivo": "Ya no lo quiero"}, headers=cab(client))
    assert r.status_code == 422


# ----------------------------------------------------------------------
# Visibilidad
# ----------------------------------------------------------------------
def test_un_usuario_solo_ve_los_suyos(client, equipo, usuario, db_session):
    admin = client.get("/api/auth/me", headers=cab(client)).json()
    emitir(client, equipo.id, admin["id"])

    otro = Equipo(sitio_id=1, tipo="activo", categoria="celular", marca="Samsung",
                  modelo="A54", numero_serie="SM-002", estado="disponible")
    db_session.add(otro)
    db_session.commit()
    db_session.refresh(otro)
    emitir(client, otro.id, usuario["id"])

    mios = client.get("/api/resguardos", headers=cab(client, "user@test.com")).json()

    assert len(mios) == 1
    assert mios[0]["usuario_id"] == usuario["id"]


def test_no_se_ve_el_resguardo_de_otro(client, equipo, usuario):
    admin = client.get("/api/auth/me", headers=cab(client)).json()
    resguardo = emitir(client, equipo.id, admin["id"]).json()

    r = client.get(f"/api/resguardos/{resguardo['id']}", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


def test_los_pendientes_de_firma_del_usuario(client, equipo, usuario):
    emitir(client, equipo.id, usuario["id"])

    pendientes = client.get("/api/resguardos/mis-pendientes",
                            headers=cab(client, "user@test.com")).json()
    assert len(pendientes) == 1
    assert pendientes[0]["estado"] == "pendiente_firma"


# ----------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------
def test_el_pdf_se_genera(client, equipo, usuario):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()

    r = client.get(f"/api/resguardos/{resguardo['id']}/pdf", headers=cab(client))

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert len(r.content) > 1000


def test_el_pdf_firmado_hace_constar_la_firma(client, equipo, usuario):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()
    client.post(f"/api/resguardos/{resguardo['id']}/firmar",
                json={"nombre_completo": "Juan Pérez", "acepto": True},
                headers=cab(client, "user@test.com"))

    r = client.get(f"/api/resguardos/{resguardo['id']}/pdf",
                   headers=cab(client, "user@test.com"))
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_no_se_descarga_el_pdf_de_otro(client, equipo, usuario):
    admin = client.get("/api/auth/me", headers=cab(client)).json()
    resguardo = emitir(client, equipo.id, admin["id"]).json()

    r = client.get(f"/api/resguardos/{resguardo['id']}/pdf", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


# ----------------------------------------------------------------------
# Expediente
# ----------------------------------------------------------------------
def test_mi_expediente_reune_lo_mio(client, equipo, usuario):
    emitir(client, equipo.id, usuario["id"])

    exp = client.get("/api/expediente/mio", headers=cab(client, "user@test.com")).json()

    assert exp["usuario"]["id"] == usuario["id"]
    assert len(exp["equipos_a_cargo"]) == 1
    assert len(exp["resguardos"]) == 1
    assert exp["resguardos_pendientes_firma"] == 1


def test_el_admin_ve_el_expediente_de_otro(client, equipo, usuario):
    emitir(client, equipo.id, usuario["id"])

    exp = client.get(f"/api/expediente/{usuario['id']}", headers=cab(client)).json()
    assert exp["usuario"]["id"] == usuario["id"]


def test_un_usuario_no_ve_el_expediente_ajeno(client, usuario):
    admin = client.get("/api/auth/me", headers=cab(client)).json()

    r = client.get(f"/api/expediente/{admin['id']}", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


# ----------------------------------------------------------------------
# Movimientos del activo
# ----------------------------------------------------------------------
def test_el_activo_acumula_su_historial(client, equipo, usuario):
    resguardo = emitir(client, equipo.id, usuario["id"]).json()
    client.post(f"/api/resguardos/{resguardo['id']}/devolver", json={}, headers=cab(client))

    movs = client.get(f"/api/resguardos/equipo/{equipo.id}/movimientos",
                      headers=cab(client)).json()

    tipos = [m["tipo"] for m in movs]
    assert "asignacion" in tipos
    assert "devolucion" in tipos


# ----------------------------------------------------------------------
# Documentos del expediente
# ----------------------------------------------------------------------
PDF = b"%PDF-1.4\n1 0 obj\n<</Type/Catalog>>\nendobj\ntrailer\n<</Root 1 0 R>>\n%%EOF"


def subir_documento(client, usuario_id, cabeceras, tipo="responsiva", **extra):
    datos = {"usuario_id": str(usuario_id), "tipo": tipo,
             "titulo": "Carta responsiva de equipo de cómputo"}
    datos.update({k: str(v) for k, v in extra.items()})
    return client.post(
        "/api/documentos",
        data=datos,
        files={"archivo": ("responsiva.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=cabeceras,
    )


def test_ti_sube_un_documento_al_expediente(client, usuario, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "DOCUMENTOS_RUTA", str(tmp_path))

    r = subir_documento(client, usuario["id"], cab(client))

    assert r.status_code == 201
    assert r.json()["tipo"] == "responsiva"
    assert r.json()["vencido"] is False


def test_el_usuario_ve_sus_documentos_pero_no_los_sube(client, usuario, tmp_path, monkeypatch):
    """Su expediente lo administra TI: si él pudiera quitar una responsiva
    firmada, el expediente no serviría de nada."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "DOCUMENTOS_RUTA", str(tmp_path))
    subir_documento(client, usuario["id"], cab(client))

    cabeceras = cab(client, "user@test.com")
    assert client.get(f"/api/documentos/usuario/{usuario['id']}",
                      headers=cabeceras).status_code == 200
    assert subir_documento(client, usuario["id"], cabeceras).status_code == 403


def test_no_se_ve_el_expediente_documental_ajeno(client, usuario, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "DOCUMENTOS_RUTA", str(tmp_path))
    admin = client.get("/api/auth/me", headers=cab(client)).json()

    r = client.get(f"/api/documentos/usuario/{admin['id']}", headers=cab(client, "user@test.com"))
    assert r.status_code == 403


def test_un_tipo_de_documento_inventado_se_rechaza(client, usuario, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "DOCUMENTOS_RUTA", str(tmp_path))

    assert subir_documento(client, usuario["id"], cab(client), tipo="cualquiera").status_code == 422


def test_solo_ti_borra_documentos(client, usuario, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "DOCUMENTOS_RUTA", str(tmp_path))
    doc = subir_documento(client, usuario["id"], cab(client)).json()

    assert client.delete(f"/api/documentos/{doc['id']}",
                         headers=cab(client, "user@test.com")).status_code == 403
    assert client.delete(f"/api/documentos/{doc['id']}", headers=cab(client)).status_code == 204
