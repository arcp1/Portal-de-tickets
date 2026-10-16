import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  X, Pencil, Trash2, CheckCheck, Upload, Eye, Download, FileText, FileCode2, Image as ImagenIcono,
  Circle, CheckCircle2, History, Paperclip,
} from 'lucide-react';
import api, { ESPERA_SUBIDA } from '../../api/client';
import forma from '../../lib/forma';
import lista from '../../lib/lista';
import { avisar, mensajeDeError } from '../../lib/avisos';
import { dinero, dineroTexto, entero } from '../../lib/cifras';
import CapaModal from '../CapaModal';
import Confirmacion from '../Confirmacion';
import Selector from '../Selector';
import Aviso from '../Aviso';
import { EsqueletoLista } from '../Cargando';
import {
  ChipEstado, ETAPAS, TIPOS_COMPROBANTE, fechaCorta, momento, tamanoLegible, traer,
} from './comun';

/**
 * Un gasto entero: sus datos, su expediente y su historia.
 *
 * **El expediente** son las etapas del tipo de compra —por proveedor:
 * cotización, orden de compra, factura, albarán; en línea: pedido, factura,
 * entrega— más el comprobante de pago, que es opcional y marca el gasto como
 * pagado. Cada etapa puede tener varios documentos (el PDF y el XML de la
 * factura, por ejemplo).
 *
 * **La historia sale de la bitácora** del portal, no de una tabla propia:
 * es la misma que ve TI en Sistema → Bitácora, y sobrevive al borrado.
 */

const ICONOS = { 'application/pdf': FileText, 'application/xml': FileCode2 };

export default function DetalleGasto({ id, version, onCerrar, onEditar, onCambio }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [g, setG] = useState(null);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [preguntar, setPreguntar] = useState(null);   // { tipo: 'gasto' | 'comprobante', item }
  const [propia, setPropia] = useState(0);

  useEffect(() => {
    let vivo = true;
    api.get(`/gastos/${id}`)
      .then((res) => {
        if (!vivo) return;
        if (forma(res.data, ['id', 'concepto', 'comprobantes', 'historial'], 'el gasto')) setG(res.data);
        else setError(t('gastos.error_cargar'));
      })
      .catch((err) => vivo && setError(mensajeDeError(err, t('gastos.no_encontrado'))));
    return () => { vivo = false; };
  }, [id, version, propia, t]);

  const recargar = () => { setPropia((v) => v + 1); onCambio(); };

  const pagar = async () => {
    try {
      await api.post(`/gastos/${g.id}/pagar`, {});
      avisar(t('gastos.marcado_pagado', { concepto: g.concepto }), { tono: 'exito' });
      recargar();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
    }
  };

  const borrar = async () => {
    const que = preguntar;
    setPreguntar(null);
    try {
      if (que.tipo === 'gasto') {
        await api.delete(`/gastos/${g.id}`);
        avisar(t('gastos.borrado', { concepto: g.concepto }), { tono: 'exito' });
        onCambio();
        onCerrar();
      } else {
        await api.delete(`/gastos/comprobantes/${que.item.id}`);
        recargar();
      }
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_borrar')));
    }
  };

  // Con la confirmación abierta, el detalle no se cierra ni con Escape ni con
  // el velo: los clics de un portal de React suben por el árbol de React, y
  // cancelar la pregunta cerraba también el gasto.
  return (
    <>
    <CapaModal onCerrar={preguntar ? undefined : onCerrar} etiqueta={g?.concepto || t('gastos.detalle')}>
      <div className="apple-card animate-scale-in gasto-detalle" onClick={(e) => e.stopPropagation()}>
        <div className="gasto-formulario-cabeza">
          <h2>{g ? g.concepto : t('gastos.detalle')}</h2>
          <button type="button" className="boton-mini" onClick={onCerrar} aria-label={t('gastos.cerrar')}><X size={16} /></button>
        </div>
        {error && <Aviso texto={error} tono="peligro" />}
        {!g && !error && <EsqueletoLista filas={3} />}
        {g && (
          <>
            <div className="gasto-detalle-cabeza">
              <div className="gasto-detalle-total">
                <span>{dinero(g.total, idioma, { moneda: g.moneda })}</span>
                {g.moneda !== 'MXN' && <span className="gasto-fila-mxn">≈ {dineroTexto(g.total_mxn, idioma)}</span>}
              </div>
              <ChipEstado estado={g.estado} fechaPago={g.fecha_pago} idioma={idioma} />
              <div className="gasto-detalle-acciones">
                {g.estado === 'pendiente' && (
                  <button type="button" className="btn-secondary metricas-boton" onClick={pagar}>
                    <CheckCheck size={15} /> {t('gastos.marcar_pagado')}
                  </button>
                )}
                <button type="button" className="btn-secondary metricas-boton" onClick={() => onEditar(g)}>
                  <Pencil size={15} /> {t('gastos.editar')}
                </button>
                <button type="button" className="btn-secondary metricas-boton gasto-boton-peligro"
                  onClick={() => setPreguntar({ tipo: 'gasto' })}>
                  <Trash2 size={15} /> {t('gastos.borrar')}
                </button>
              </div>
            </div>
            <Aviso texto={aviso} tono="peligro" />

            <dl className="gasto-datos">
              <Dato titulo={t('gastos.fecha')}>{fechaCorta(g.fecha, idioma)}</Dato>
              <Dato titulo={t('gastos.tipo_compra')}>{t(g.tipo_compra === 'linea' ? 'gastos.compra_linea' : 'gastos.compra_proveedor')}</Dato>
              <Dato titulo={t('gastos.proveedor')}>
                {g.proveedor ? <>{g.proveedor.nombre}{g.proveedor.rfc && <span className="gasto-rfc">{g.proveedor.rfc}</span>}</> : '—'}
              </Dato>
              <Dato titulo={t('gastos.categoria')}>{g.categoria.nombre}</Dato>
              <Dato titulo={t('gastos.cantidad')}>{entero(g.cantidad, idioma)}</Dato>
              {g.referencia && <Dato titulo={t('gastos.referencia')}>{g.referencia}</Dato>}
              <Dato titulo={t('gastos.subtotal')}>{dineroTexto(g.subtotal, idioma, { moneda: g.moneda })}</Dato>
              <Dato titulo={`${t('gastos.iva')} (${Math.round(g.tasa_iva * 100)} %)`}>{dineroTexto(g.iva, idioma, { moneda: g.moneda })}</Dato>
              {g.retenciones > 0 && <Dato titulo={t('gastos.retenciones')}>−{dineroTexto(g.retenciones, idioma, { moneda: g.moneda })}</Dato>}
              {g.moneda !== 'MXN' && <Dato titulo={t('gastos.tipo_cambio')}>{g.tipo_cambio}</Dato>}
              {g.fecha_pago && <Dato titulo={t('gastos.fecha_pago')}>{fechaCorta(g.fecha_pago, idioma)}</Dato>}
              <Dato titulo={t('plantas.planta')}>{g.planta ? `${g.planta.clave} · ${g.planta.nombre}` : '—'}</Dato>
              <Dato titulo={t('gastos.activo')}>{g.equipo ? g.equipo.etiqueta : '—'}</Dato>
              <Dato titulo={t('gastos.ticket')}>
                {g.ticket ? <Link to={`/tickets/${g.ticket.id}`} onClick={onCerrar}>{g.ticket.folio}</Link> : '—'}
              </Dato>
              <Dato titulo={t('gastos.responsable')}>{g.responsable ? g.responsable.nombre : '—'}</Dato>
              {g.centro_costo && <Dato titulo={t('gastos.centro_costo')}>{g.centro_costo}</Dato>}
              {g.notas && <Dato titulo={t('gastos.notas')} ancho>{g.notas}</Dato>}
            </dl>

            <Expediente g={g} idioma={idioma} onCambio={recargar}
              onBorrar={(c) => setPreguntar({ tipo: 'comprobante', item: c })} />

            <section className="gasto-historial">
              <h3><History size={16} /> {t('gastos.historial')}</h3>
              <ol>
                {lista(g.historial, 'el historial').map((h, i) => (
                  <li key={i}>
                    <span className="gasto-historial-que">{textoHistorial(h, t)}</span>
                    <span className="gasto-historial-quien">{h.usuario || '—'} · {momento(h.creado_en, idioma)}</span>
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </div>
    </CapaModal>
      {preguntar && (
        <Confirmacion
          titulo={preguntar.tipo === 'gasto' ? t('gastos.borrar_titulo') : t('gastos.borrar_comprobante')}
          mensaje={preguntar.tipo === 'gasto'
            ? t('gastos.borrar_mensaje', { concepto: g.concepto, count: g.comprobantes.length })
            : t('gastos.borrar_comprobante_mensaje', { nombre: preguntar.item.nombre })}
          textoConfirmar={t('gastos.borrar')}
          tono="peligro"
          onConfirmar={borrar}
          onCancelar={() => setPreguntar(null)}
        />
      )}
    </>
  );
}

function Dato({ titulo, children, ancho = false }) {
  return (
    <div className={`gasto-dato-par${ancho ? ' gasto-dato-par--ancho' : ''}`}>
      <dt>{titulo}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function textoHistorial(h, t) {
  const d = h.detalle || {};
  switch (h.accion) {
    case 'gasto.creado': return t('gastos.historial_creado');
    case 'gasto.pagado': return t('gastos.historial_pagado', { fecha: d.fecha_pago || (d.cambios?.fecha_pago?.despues) || '' });
    case 'gasto.editado': {
      const campos = Object.keys(d.cambios || {}).map((c) => t(`gastos.campo_${c}`, { defaultValue: c }));
      return t('gastos.historial_editado', { campos: campos.join(', ') });
    }
    case 'gasto.comprobante_subido':
      return t('gastos.historial_subido', { tipo: t(`gastos.tipo_${d.tipo}`), nombre: d.nombre || '' });
    case 'gasto.comprobante_borrado':
      return t('gastos.historial_quitado', { tipo: t(`gastos.tipo_${d.tipo}`), nombre: d.nombre || '' });
    default: return h.accion;
  }
}

function Expediente({ g, idioma, onCambio, onBorrar }) {
  const { t } = useTranslation();
  const etapas = ETAPAS[g.tipo_compra] || ETAPAS.proveedor;
  const comprobantes = lista(g.comprobantes, 'los comprobantes');
  const primeraQueFalta = etapas.find((e) => !comprobantes.some((c) => c.tipo === e)) || 'pago';
  const [tipo, setTipo] = useState(primeraQueFalta);
  const [folio, setFolio] = useState('');
  const [fecha, setFecha] = useState('');
  const [subiendo, setSubiendo] = useState(false);
  const [aviso, setAviso] = useState('');
  const archivo = useRef(null);

  useEffect(() => { setTipo(primeraQueFalta); }, [primeraQueFalta]);

  const subir = async (e) => {
    const elegido = e.target.files?.[0];
    if (!elegido) return;
    setSubiendo(true);
    setAviso('');
    try {
      const datos = new FormData();
      datos.append('archivo', elegido);
      datos.append('tipo', tipo);
      if (folio.trim()) datos.append('folio', folio.trim());
      if (fecha) datos.append('fecha', fecha);
      const res = await api.post(`/gastos/${g.id}/comprobantes`, datos, {
        headers: { 'Content-Type': 'multipart/form-data' }, timeout: ESPERA_SUBIDA });
      (res.data?.avisos || []).forEach((a) => avisar(t(`gastos.aviso_${a}`), { tono: 'atencion' }));
      setFolio('');
      setFecha('');
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_subir')));
    } finally {
      setSubiendo(false);
      if (archivo.current) archivo.current.value = '';
    }
  };

  const ver = (c, descargar) => traer(`/gastos/comprobantes/${c.id}/descarga`, c.nombre, { ver: !descargar })
    .catch(() => setAviso(t('gastos.error_descargar')));

  const filas = [...etapas, ...(etapas.includes('pago') ? [] : ['pago'])];

  return (
    <section className="gasto-expediente">
      <h3><Paperclip size={16} /> {t('gastos.expediente')}</h3>
      <ol className="gasto-etapas-lista">
        {filas.map((etapa) => {
          const docs = comprobantes.filter((c) => c.tipo === etapa);
          const opcional = etapa === 'pago' || !etapas.includes(etapa);
          return (
            <li key={etapa} className={`gasto-etapa-fila${docs.length ? ' gasto-etapa-fila--hecha' : ''}`}>
              <div className="gasto-etapa-nombre">
                {docs.length ? <CheckCircle2 size={16} aria-hidden="true" /> : <Circle size={16} aria-hidden="true" />}
                <span>{t(`gastos.tipo_${etapa}`)}</span>
                {!docs.length && <span className="gasto-etapa-estado">{t(opcional ? 'gastos.opcional' : 'gastos.falta')}</span>}
              </div>
              {docs.map((c) => {
                const Icono = ICONOS[c.tipo_mime] || ImagenIcono;
                const enLinea = c.tipo_mime !== 'application/xml';
                return (
                  <div key={c.id} className="gasto-comprobante">
                    <Icono size={15} aria-hidden="true" />
                    <span className="gasto-comprobante-nombre" title={c.nombre}>{c.nombre}</span>
                    <span className="gasto-comprobante-meta">
                      {[c.folio, c.fecha && fechaCorta(c.fecha, idioma), tamanoLegible(c.tamano_bytes, idioma)]
                        .filter(Boolean).join(' · ')}
                      {c.cfdi_uuid && <span className="gasto-rfc" title={t('gastos.uuid')}>{c.cfdi_uuid}</span>}
                    </span>
                    <span className="gasto-comprobante-acciones">
                      {enLinea && (
                        <button type="button" className="boton-mini" onClick={() => ver(c, false)}
                          title={t('gastos.ver')} aria-label={`${t('gastos.ver')}: ${c.nombre}`}><Eye size={14} /></button>
                      )}
                      <button type="button" className="boton-mini" onClick={() => ver(c, true)}
                        title={t('gastos.descargar')} aria-label={`${t('gastos.descargar')}: ${c.nombre}`}><Download size={14} /></button>
                      <button type="button" className="boton-mini" onClick={() => onBorrar(c)}
                        title={t('gastos.borrar')} aria-label={`${t('gastos.borrar')}: ${c.nombre}`}><Trash2 size={14} /></button>
                    </span>
                  </div>
                );
              })}
            </li>
          );
        })}
      </ol>

      <div className="gasto-subir">
        <Selector className="form-select" value={tipo} onChange={(e) => setTipo(e.target.value)} aria-label={t('gastos.tipo_documento')}>
          {TIPOS_COMPROBANTE.map((c) => <option key={c} value={c}>{t(`gastos.tipo_${c}`)}</option>)}
        </Selector>
        <input className="form-input" value={folio} onChange={(e) => setFolio(e.target.value)} maxLength={60}
          placeholder={t('gastos.folio')} aria-label={t('gastos.folio')} />
        <input className="form-input" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)}
          aria-label={t('gastos.fecha_documento')} min="2000-01-01" max="2100-12-31" />
        <label className={`btn-acento metricas-boton gasto-subir-boton${subiendo ? ' gasto-subir-boton--ocupado' : ''}`}>
          <Upload size={15} /> {subiendo ? t('gastos.subiendo') : t('gastos.subir')}
          <input ref={archivo} type="file" hidden disabled={subiendo}
            accept=".pdf,.xml,.jpg,.jpeg,.png,.webp,application/pdf,application/xml,text/xml,image/jpeg,image/png,image/webp"
            onChange={subir} />
        </label>
      </div>
      <p className="nota-suave">{t('gastos.subir_ayuda')}</p>
      <Aviso texto={aviso} tono="peligro" />
    </section>
  );
}
