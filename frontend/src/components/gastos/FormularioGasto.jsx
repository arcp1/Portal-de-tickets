import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, X, FileCode2, Laptop, Ticket, Search, AlertTriangle, Store, ShoppingCart } from 'lucide-react';
import api, { ESPERA_SUBIDA } from '../../api/client';
import lista from '../../lib/lista';
import { avisar, mensajeDeError } from '../../lib/avisos';
import { dinero, dineroTexto } from '../../lib/cifras';
import CapaModal from '../CapaModal';
import Formulario from '../Formulario';
import Selector from '../Selector';
import Aviso from '../Aviso';
import { hoyIso } from './comun';

/**
 * Alta y edición de un gasto.
 *
 * **El importe se teclea como viene en el papel**: con el IVA incluido (lo
 * que se pagó), más IVA (el precio de una cotización) o sin IVA. El servidor
 * hace la cuenta con decimales exactos; aquí solo se enseña cómo va a quedar.
 * Lo que dice la vista previa y lo que se guarda salen de la misma regla
 * (`calcular_importes` en el backend).
 *
 * **Con el XML del CFDI se llena solo**: fecha, proveedor y RFC, concepto,
 * subtotal, IVA exacto, retenciones, moneda y tipo de cambio. Al guardar, ese
 * XML entra al expediente como la factura. Si ya está en otro gasto, se avisa
 * antes de guardar nada.
 */

const NUEVO = '__nuevo__';

function redondear(v) {
  return Math.round((Number(v) || 0) * 100) / 100;
}

/** La misma cuenta que el backend, para enseñarla mientras se teclea. */
function vistaPrevia({ modo, monto, tasa, iva, retenciones }) {
  const m = Number(monto) || 0;
  const r = Number(retenciones) || 0;
  const tasaN = modo === 'sin' ? 0 : Number(tasa);
  if (modo === 'incluido') {
    const bruto = m + r;
    const subtotal = redondear(bruto / (1 + tasaN));
    return { subtotal, iva: redondear(bruto - subtotal), retenciones: r, total: redondear(m) };
  }
  const subtotal = redondear(m);
  const ivaN = iva !== null && iva !== undefined && modo === 'mas' ? Number(iva) : redondear(subtotal * tasaN);
  return { subtotal, iva: ivaN, retenciones: r, total: redondear(subtotal + ivaN - r) };
}

function inicial(gasto) {
  if (!gasto) {
    return {
      concepto: '', fecha: hoyIso(), cantidad: '1', porUnidad: false, monto: '', modo: 'incluido', tasa: '0.16',
      iva: null, retenciones: '', moneda: 'MXN', tipoCambio: '', proveedor: '', proveedorNombre: '', rfc: '',
      categoria: '', tipoCompra: 'proveedor', referencia: '', pagado: false, fechaPago: '', planta: '',
      equipo: null, ticket: null, responsable: '', centroCosto: '', notas: '',
    };
  }
  const tasa = String(gasto.tasa_iva);
  return {
    concepto: gasto.concepto, fecha: gasto.fecha, cantidad: String(gasto.cantidad), porUnidad: false,
    monto: String(gasto.subtotal), modo: gasto.iva > 0 ? 'mas' : 'sin',
    tasa: tasa === '0.08' ? '0.08' : '0.16', iva: gasto.iva > 0 ? gasto.iva : null,
    retenciones: gasto.retenciones ? String(gasto.retenciones) : '', moneda: gasto.moneda,
    tipoCambio: gasto.moneda === 'USD' ? String(gasto.tipo_cambio) : '',
    proveedor: gasto.proveedor ? String(gasto.proveedor.id) : '', proveedorNombre: '', rfc: '',
    categoria: String(gasto.categoria.id), tipoCompra: gasto.tipo_compra, referencia: gasto.referencia || '',
    pagado: gasto.estado === 'pagado', fechaPago: gasto.fecha_pago || '',
    planta: gasto.planta ? String(gasto.planta.id) : '', equipo: gasto.equipo, ticket: gasto.ticket
      ? { id: gasto.ticket.id, etiqueta: gasto.ticket.folio } : null,
    responsable: gasto.responsable ? String(gasto.responsable.id) : '',
    centroCosto: gasto.centro_costo || '', notas: gasto.notas || '',
  };
}

export default function FormularioGasto({ gasto, catalogos, plantas, onCerrar, onGuardado }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [f, setF] = useState(() => inicial(gasto));
  const [aviso, setAviso] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [cfdi, setCfdi] = useState(null);       // { archivo, datos }
  const [leyendo, setLeyendo] = useState(false);
  const archivoRef = useRef(null);
  const poner = (cambios) => setF((actual) => ({ ...actual, ...cambios }));
  // Cambiar el importe o la tasa invalida el IVA exacto del CFDI.
  const ponerImporte = (cambios) => setF((actual) => ({ ...actual, ...cambios, iva: null }));

  const categorias = lista(catalogos.categorias).filter((c) => c.activa || String(c.id) === f.categoria);
  const proveedores = lista(catalogos.proveedores);
  const montoBase = f.porUnidad ? (Number(f.monto) || 0) * (Number(f.cantidad) || 1) : Number(f.monto) || 0;
  const previa = useMemo(() => vistaPrevia({ modo: f.modo, monto: montoBase, tasa: f.tasa, iva: f.iva,
    retenciones: f.retenciones }), [f.modo, montoBase, f.tasa, f.iva, f.retenciones]);

  // Al elegir un proveedor conocido se propone su categoría de siempre.
  const elegirProveedor = (valor) => {
    const p = proveedores.find((x) => String(x.id) === valor);
    poner({ proveedor: valor, ...(p?.categoria_habitual && !f.categoria ? { categoria: String(p.categoria_habitual.id) } : {}) });
  };

  const leerCfdi = async (archivo) => {
    if (!archivo) return;
    setLeyendo(true);
    setAviso('');
    try {
      const datos = new FormData();
      datos.append('archivo', archivo);
      const res = await api.post('/gastos/cfdi/analizar', datos, {
        headers: { 'Content-Type': 'multipart/form-data' }, timeout: ESPERA_SUBIDA });
      const d = res.data || {};
      setCfdi({ archivo, datos: d });
      const conocido = d.proveedor_id ? String(d.proveedor_id) : '';
      setF((actual) => ({
        ...actual,
        concepto: actual.concepto || d.concepto || '',
        fecha: d.fecha || actual.fecha,
        monto: String(d.subtotal ?? ''),
        modo: d.iva > 0 ? 'mas' : 'sin',
        tasa: String(d.tasa_iva) === '0.08' ? '0.08' : '0.16',
        iva: d.iva > 0 ? d.iva : null,
        retenciones: d.retenciones ? String(d.retenciones) : '',
        moneda: d.moneda || 'MXN',
        tipoCambio: d.moneda === 'USD' ? String(d.tipo_cambio || '') : '',
        porUnidad: false,
        proveedor: conocido || (d.proveedor_nombre ? NUEVO : actual.proveedor),
        proveedorNombre: conocido ? '' : (d.proveedor_nombre || ''),
        rfc: d.emisor_rfc || '',
        categoria: actual.categoria || (d.categoria_id ? String(d.categoria_id) : ''),
      }));
    } catch (err) {
      setCfdi(null);
      setAviso(mensajeDeError(err, t('gastos.error_cfdi')));
    } finally {
      setLeyendo(false);
      if (archivoRef.current) archivoRef.current.value = '';
    }
  };

  const guardar = async (e) => {
    e.preventDefault();
    if (!f.categoria) { setAviso(t('gastos.falta_categoria')); return; }
    setEnviando(true);
    setAviso('');
    const cuerpo = {
      fecha: f.fecha,
      concepto: f.concepto.trim(),
      categoria_id: Number(f.categoria),
      tipo_compra: f.tipoCompra,
      referencia: f.referencia.trim() || null,
      cantidad: (Number(f.cantidad) || 1).toFixed(2),
      moneda: f.moneda,
      tipo_cambio: f.moneda === 'USD' ? Number(f.tipoCambio).toFixed(6) : null,
      tasa_iva: f.modo === 'sin' ? '0' : f.tasa,
      retenciones: redondear(f.retenciones).toFixed(2),
      estado: f.pagado ? 'pagado' : 'pendiente',
      fecha_pago: f.pagado && f.fechaPago ? f.fechaPago : null,
      centro_costo: f.centroCosto.trim() || null,
      notas: f.notas.trim() || null,
      sitio_id: f.planta ? Number(f.planta) : null,
      equipo_id: f.equipo?.id || null,
      ticket_id: f.ticket?.id || null,
      responsable_id: f.responsable ? Number(f.responsable) : null,
    };
    if (f.modo === 'incluido') cuerpo.total = redondear(montoBase).toFixed(2);
    else cuerpo.subtotal = redondear(montoBase).toFixed(2);
    if (f.modo === 'mas' && f.iva !== null) cuerpo.iva = redondear(f.iva).toFixed(2);
    if (f.proveedor === NUEVO) {
      cuerpo.proveedor_nombre = f.proveedorNombre.trim() || null;
      cuerpo.proveedor_rfc = f.rfc.trim() || null;
    } else if (f.proveedor) {
      cuerpo.proveedor_id = Number(f.proveedor);
      if (f.rfc) cuerpo.proveedor_rfc = f.rfc;
    }
    try {
      const res = gasto
        ? await api.put(`/gastos/${gasto.id}`, cuerpo)
        : await api.post('/gastos', cuerpo);
      const guardado = res.data;
      // El XML que llenó el formulario entra al expediente como la factura.
      if (cfdi?.archivo && !cfdi.datos?.duplicado) {
        try {
          const datos = new FormData();
          datos.append('archivo', cfdi.archivo);
          datos.append('tipo', cfdi.datos?.tipo_comprobante === 'P' ? 'pago' : 'factura');
          const sube = await api.post(`/gastos/${guardado.id}/comprobantes`, datos, {
            headers: { 'Content-Type': 'multipart/form-data' }, timeout: ESPERA_SUBIDA });
          (sube.data?.avisos || []).forEach((a) => avisar(t(`gastos.aviso_${a}`), { tono: 'atencion' }));
        } catch (err) {
          avisar(mensajeDeError(err, t('gastos.error_subir')), { tono: 'atencion' });
        }
      }
      avisar(t(gasto ? 'gastos.guardado' : 'gastos.registrado'), { tono: 'exito' });
      onGuardado(guardado);
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
      setEnviando(false);
    }
  };

  const titulo = gasto ? t('gastos.editar') : t('gastos.nuevo');

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={titulo}>
      <Formulario onSubmit={guardar} className="apple-card animate-scale-in gasto-formulario"
        onClick={(e) => e.stopPropagation()}>
        <div className="gasto-formulario-cabeza">
          <h2>{titulo}</h2>
          <button type="button" className="boton-mini" onClick={onCerrar} aria-label={t('gastos.cerrar')}><X size={16} /></button>
        </div>

        <div className="gasto-cfdi">
          <label className="btn-secondary metricas-boton gasto-cfdi-boton">
            <FileCode2 size={15} />
            {leyendo ? t('gastos.leyendo_cfdi') : t('gastos.cargar_cfdi')}
            <input ref={archivoRef} type="file" accept=".xml,application/xml,text/xml" hidden
              onChange={(e) => leerCfdi(e.target.files?.[0])} disabled={leyendo} />
          </label>
          <span className="nota-suave">
            {cfdi ? t('gastos.cfdi_leido', { nombre: cfdi.archivo.name }) : t('gastos.cargar_cfdi_ayuda')}
          </span>
        </div>
        {cfdi?.datos?.duplicado && (
          <Aviso tono="peligro" texto={t('gastos.cfdi_duplicado', { id: cfdi.datos.duplicado.gasto_id,
            concepto: cfdi.datos.duplicado.concepto })} />
        )}
        {(cfdi?.datos?.avisos || []).map((a) => <Aviso key={a} texto={t(`gastos.aviso_${a}`)} />)}

        <div className="gasto-campos">
          <div className="form-group gasto-campo--ancho">
            <label htmlFor="g-concepto">{t('gastos.concepto')}</label>
            <input id="g-concepto" className="form-input" required maxLength={200} value={f.concepto}
              onChange={(e) => poner({ concepto: e.target.value })} placeholder={t('gastos.concepto_ejemplo')} />
          </div>

          <div className="form-group">
            <label>{t('gastos.tipo_compra')}</label>
            <div className="gasto-segmentos" role="group" aria-label={t('gastos.tipo_compra')}>
              {[['proveedor', <Store size={14} key="i" />], ['linea', <ShoppingCart size={14} key="i" />]].map(([v, icono]) => (
                <button key={v} type="button" aria-pressed={f.tipoCompra === v}
                  className={`gasto-segmento${f.tipoCompra === v ? ' gasto-segmento--activo' : ''}`}
                  onClick={() => poner({ tipoCompra: v })}>
                  {icono}{t(v === 'linea' ? 'gastos.compra_linea' : 'gastos.compra_proveedor')}
                </button>
              ))}
            </div>
          </div>
          <div className="form-group">
            <label htmlFor="g-fecha">{t('gastos.fecha')}</label>
            <input id="g-fecha" type="date" className="form-input" required value={f.fecha}
              min="2000-01-01" max="2100-12-31" onChange={(e) => poner({ fecha: e.target.value })} />
          </div>

          <div className="form-group">
            <label htmlFor="g-proveedor">{t('gastos.proveedor')}</label>
            <Selector id="g-proveedor" className="form-select" value={f.proveedor} onChange={(e) => elegirProveedor(e.target.value)}>
              <option value="">{t('gastos.sin_proveedor')}</option>
              {proveedores.map((p) => <option key={p.id} value={String(p.id)}>{p.rfc ? `${p.nombre} · ${p.rfc}` : p.nombre}</option>)}
              <option value={NUEVO}>{t('gastos.proveedor_nuevo')}</option>
            </Selector>
          </div>
          <div className="form-group">
            <label htmlFor="g-categoria">{t('gastos.categoria')}</label>
            <Selector id="g-categoria" className="form-select" value={f.categoria} onChange={(e) => poner({ categoria: e.target.value })}>
              <option value="" disabled>{t('gastos.elegir_categoria')}</option>
              {categorias.map((c) => <option key={c.id} value={String(c.id)}>{c.nombre}</option>)}
            </Selector>
          </div>
          {f.proveedor === NUEVO && (
            <>
              <div className="form-group">
                <label htmlFor="g-prov-nombre">{t('gastos.proveedor_nombre')}</label>
                <input id="g-prov-nombre" className="form-input" required maxLength={150} value={f.proveedorNombre}
                  onChange={(e) => poner({ proveedorNombre: e.target.value })} />
              </div>
              <div className="form-group">
                <label htmlFor="g-prov-rfc">{t('gastos.rfc')}</label>
                <input id="g-prov-rfc" className="form-input" maxLength={13} value={f.rfc} autoCapitalize="characters"
                  onChange={(e) => poner({ rfc: e.target.value.toUpperCase() })} placeholder="ABC010203XY1" />
              </div>
            </>
          )}

          <fieldset className="gasto-importe gasto-campo--ancho">
            <legend>{t('gastos.importe')}</legend>
            <div className="gasto-importe-fila">
              <div className="form-group">
                <label htmlFor="g-monto">{f.porUnidad ? t('gastos.precio_unitario') : t('gastos.monto')}</label>
                <input id="g-monto" className="form-input" type="number" inputMode="decimal" min="0" step="0.01" required
                  value={f.monto} onChange={(e) => ponerImporte({ monto: e.target.value })} placeholder="0.00" />
              </div>
              <div className="form-group">
                <label htmlFor="g-modo">{t('gastos.como_viene')}</label>
                <Selector id="g-modo" className="form-select" value={f.modo} onChange={(e) => ponerImporte({ modo: e.target.value })}>
                  <option value="incluido">{t('gastos.iva_incluido')}</option>
                  <option value="mas">{t('gastos.mas_iva')}</option>
                  <option value="sin">{t('gastos.sin_iva')}</option>
                </Selector>
              </div>
              {f.modo !== 'sin' && (
                <div className="form-group">
                  <label htmlFor="g-tasa">{t('gastos.tasa_iva')}</label>
                  <Selector id="g-tasa" className="form-select" value={f.tasa} onChange={(e) => ponerImporte({ tasa: e.target.value })}>
                    <option value="0.16">16 %</option>
                    <option value="0.08">{t('gastos.tasa_frontera')}</option>
                  </Selector>
                </div>
              )}
              <div className="form-group">
                <label htmlFor="g-cantidad">{t('gastos.cantidad')}</label>
                <input id="g-cantidad" className="form-input" type="number" inputMode="decimal" min="0.01" step="0.01"
                  required value={f.cantidad} onChange={(e) => poner({ cantidad: e.target.value })} />
              </div>
              <div className="form-group">
                <label htmlFor="g-retenciones">{t('gastos.retenciones')}</label>
                <input id="g-retenciones" className="form-input" type="number" inputMode="decimal" min="0" step="0.01"
                  value={f.retenciones} onChange={(e) => poner({ retenciones: e.target.value })} placeholder="0.00" />
              </div>
              <div className="form-group">
                <label htmlFor="g-moneda">{t('gastos.moneda')}</label>
                <Selector id="g-moneda" className="form-select" value={f.moneda} onChange={(e) => poner({ moneda: e.target.value })}>
                  <option value="MXN">MXN</option>
                  <option value="USD">USD</option>
                </Selector>
              </div>
              {f.moneda === 'USD' && (
                <div className="form-group">
                  <label htmlFor="g-tc">{t('gastos.tipo_cambio')}</label>
                  <input id="g-tc" className="form-input" type="number" inputMode="decimal" min="0.0001" step="0.0001"
                    required value={f.tipoCambio} onChange={(e) => poner({ tipoCambio: e.target.value })} placeholder="18.5000" />
                </div>
              )}
            </div>
            <label className="interruptor gasto-por-unidad">
              <input type="checkbox" checked={f.porUnidad} onChange={(e) => poner({ porUnidad: e.target.checked })} />
              {t('gastos.por_unidad')}
            </label>
            <div className="gasto-previa" aria-live="polite">
              <span>{t('gastos.subtotal')} <b>{dineroTexto(previa.subtotal, idioma, { moneda: f.moneda })}</b></span>
              <span>{t('gastos.iva')} <b>{dineroTexto(previa.iva, idioma, { moneda: f.moneda })}</b></span>
              {previa.retenciones > 0 && (
                <span>{t('gastos.retenciones')} <b>−{dineroTexto(previa.retenciones, idioma, { moneda: f.moneda })}</b></span>
              )}
              <span className="gasto-previa-total">{t('gastos.total')} <b>{dinero(previa.total, idioma, { moneda: f.moneda })}</b></span>
              {f.moneda === 'USD' && Number(f.tipoCambio) > 0 && (
                <span>≈ {dineroTexto(previa.total * Number(f.tipoCambio), idioma)}</span>
              )}
            </div>
            {f.iva !== null && f.modo === 'mas' && (
              <p className="nota-suave">{t('gastos.iva_del_cfdi')}</p>
            )}
            {previa.total < 0 && <p className="gasto-error-campo"><AlertTriangle size={14} /> {t('gastos.retenciones_mayores')}</p>}
          </fieldset>

          <div className="form-group">
            <label htmlFor="g-referencia">{t(f.tipoCompra === 'linea' ? 'gastos.numero_pedido' : 'gastos.referencia')}</label>
            <input id="g-referencia" className="form-input" maxLength={60} value={f.referencia}
              onChange={(e) => poner({ referencia: e.target.value })} />
          </div>
          <div className="form-group">
            <label className="interruptor">
              <input type="checkbox" checked={f.pagado} onChange={(e) => poner({ pagado: e.target.checked })} />
              {t('gastos.ya_pagado')}
            </label>
            {f.pagado && (
              <input type="date" className="form-input" value={f.fechaPago} aria-label={t('gastos.fecha_pago')}
                min="2000-01-01" max="2100-12-31" onChange={(e) => poner({ fechaPago: e.target.value })} />
            )}
            {f.pagado && !f.fechaPago && <p className="nota-suave">{t('gastos.fecha_pago_ayuda')}</p>}
          </div>

          <fieldset className="gasto-vinculos gasto-campo--ancho">
            <legend>{t('gastos.vinculos')}</legend>
            <p className="nota-suave">{t('gastos.vinculos_ayuda')}</p>
            <div className="gasto-importe-fila">
              <div className="form-group">
                <label htmlFor="g-planta">{t('plantas.planta')}</label>
                <Selector id="g-planta" className="form-select" value={f.planta} onChange={(e) => poner({ planta: e.target.value })}>
                  <option value="">{t('gastos.sin_planta')}</option>
                  {plantas.map((p) => <option key={p.id} value={String(p.id)}>{`${p.clave} · ${p.nombre}`}</option>)}
                </Selector>
              </div>
              <div className="form-group">
                <label htmlFor="g-responsable">{t('gastos.responsable')}</label>
                <Selector id="g-responsable" className="form-select" value={f.responsable} onChange={(e) => poner({ responsable: e.target.value })}>
                  <option value="">{t('gastos.sin_responsable')}</option>
                  {lista(catalogos.responsables).map((r) => <option key={r.id} value={String(r.id)}>{r.nombre}</option>)}
                </Selector>
              </div>
              <BuscadorVinculo tipo="equipo" etiqueta={t('gastos.activo')} icono={<Laptop size={14} />}
                valor={f.equipo} onCambio={(v) => poner({ equipo: v })} />
              <BuscadorVinculo tipo="ticket" etiqueta={t('gastos.ticket')} icono={<Ticket size={14} />}
                valor={f.ticket} onCambio={(v) => poner({ ticket: v })} />
            </div>
          </fieldset>

          <div className="form-group">
            <label htmlFor="g-cc">{t('gastos.centro_costo')}</label>
            <input id="g-cc" className="form-input" maxLength={60} value={f.centroCosto}
              onChange={(e) => poner({ centroCosto: e.target.value })} />
          </div>
          <div className="form-group gasto-campo--ancho">
            <label htmlFor="g-notas">{t('gastos.notas')}</label>
            <textarea id="g-notas" className="form-textarea" rows={2} maxLength={2000} value={f.notas}
              onChange={(e) => poner({ notas: e.target.value })} />
          </div>
        </div>

        <Aviso texto={aviso} tono="peligro" />
        <div className="gasto-formulario-pie">
          <button type="button" onClick={onCerrar} className="btn-secondary"><X size={15} /> {t('temas.cancelar')}</button>
          <button type="submit" className="btn-acento" disabled={enviando || leyendo || previa.total < 0}>
            <Check size={15} /> {enviando ? t('temas.guardando') : t('temas.guardar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
}

/** Busca un activo o un ticket por texto y deja elegir uno. */
function BuscadorVinculo({ tipo, etiqueta, icono, valor, onCambio }) {
  const { t } = useTranslation();
  const [texto, setTexto] = useState('');
  const [hallados, setHallados] = useState([]);
  const id = `g-vinculo-${tipo}`;

  useEffect(() => {
    const q = texto.trim();
    if (q.length < 2) { setHallados([]); return undefined; }
    let vivo = true;
    const espera = setTimeout(() => {
      api.get('/gastos/vinculos', { params: { tipo, q } })
        .then((res) => vivo && setHallados(lista(res.data, 'los vínculos')))
        .catch(() => vivo && setHallados([]));
    }, 250);
    return () => { vivo = false; clearTimeout(espera); };
  }, [texto, tipo]);

  if (valor) {
    return (
      <div className="form-group">
        <span className="gasto-vinculo-rotulo">{etiqueta}</span>
        <span className="gasto-vinculo-elegido">
          {icono}<span>{valor.etiqueta}</span>
          <button type="button" className="boton-mini" onClick={() => onCambio(null)}
            aria-label={t('gastos.quitar_vinculo', { que: etiqueta })}><X size={13} /></button>
        </span>
      </div>
    );
  }
  return (
    <div className="form-group gasto-vinculo">
      <label htmlFor={id}>{etiqueta}</label>
      <div className="gasto-buscar-vinculo">
        <Search size={14} aria-hidden="true" />
        <input id={id} className="form-input" value={texto} onChange={(e) => setTexto(e.target.value)}
          placeholder={t(tipo === 'equipo' ? 'gastos.buscar_activo' : 'gastos.buscar_ticket')} maxLength={60}
          autoComplete="off" />
      </div>
      {hallados.length > 0 && (
        <ul className="gasto-vinculo-lista" role="listbox" aria-label={etiqueta}>
          {hallados.map((h) => (
            <li key={h.id}>
              <button type="button" role="option" aria-selected="false"
                onClick={() => { onCambio({ id: h.id, etiqueta: h.etiqueta }); setTexto(''); setHallados([]); }}>
                <strong>{h.etiqueta}</strong>
                {h.detalle && <span>{h.detalle}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {texto.trim().length >= 2 && hallados.length === 0 && (
        <p className="nota-suave">{t('gastos.sin_resultados')}</p>
      )}
    </div>
  );
}
