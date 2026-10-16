import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PiggyBank, Tags, Building2, Save, Copy, Plus, Pencil, Check, X, Trash2, Archive, ArchiveRestore } from 'lucide-react';
import api from '../../api/client';
import forma from '../../lib/forma';
import lista from '../../lib/lista';
import { avisar, mensajeDeError } from '../../lib/avisos';
import { dinero, dineroTexto, localeDe } from '../../lib/cifras';
import GlassCard from '../GlassCard';
import Aviso from '../Aviso';
import Confirmacion from '../Confirmacion';
import { EsqueletoLista } from '../Cargando';
import Formulario from '../Formulario';

/**
 * El presupuesto anual por categoría, y los catálogos que lo sostienen.
 *
 * El presupuesto es de toda el área de TI, en pesos, y se compara en el
 * resumen contra lo gastado **a la fecha** (prorrateado por días), no contra
 * «anual entre doce». Las categorías no se borran: se retiran, y sus gastos
 * de otros años las siguen nombrando. Un proveedor sí se puede quitar,
 * mientras no tenga gastos.
 */
export default function Presupuesto({ anio, catalogos, onCambio }) {
  const { t } = useTranslation();
  return (
    <>
      <MontosDelAnio anio={anio} onCambio={onCambio} />
      <div className="gastos-doble gastos-doble--parejo">
        <GlassCard relleno="24px" style={{ marginBottom: '20px' }}>
          <h2 className="titulo-bloque"><Tags size={20} color="var(--accent-primary)" />{t('gastos.categorias')}</h2>
          <Categorias categorias={lista(catalogos?.categorias)} onCambio={onCambio} />
        </GlassCard>
        <GlassCard relleno="24px" style={{ marginBottom: '20px' }}>
          <h2 className="titulo-bloque"><Building2 size={20} color="var(--accent-primary)" />{t('gastos.proveedores')}</h2>
          <Proveedores proveedores={lista(catalogos?.proveedores)} onCambio={onCambio} />
        </GlassCard>
      </div>
    </>
  );
}

function MontosDelAnio({ anio, onCambio }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [datos, setDatos] = useState(null);
  const [montos, setMontos] = useState({});
  const [aviso, setAviso] = useState('');
  const [guardando, setGuardando] = useState(false);

  const cargar = () => api.get(`/gastos/presupuesto/${anio}`)
    .then((res) => {
      if (!forma(res.data, ['categorias'], 'el presupuesto')) { setAviso(t('gastos.error_cargar')); return; }
      setDatos(res.data);
      setMontos(Object.fromEntries(lista(res.data.categorias).map((c) => [c.categoria_id, c.monto ? String(c.monto) : ''])));
      setAviso('');
    })
    .catch((err) => setAviso(mensajeDeError(err, t('gastos.error_cargar'))));

  useEffect(() => { setDatos(null); cargar(); }, [anio]);

  const copiarAnterior = async () => {
    try {
      const res = await api.get(`/gastos/presupuesto/${anio - 1}`);
      const previos = Object.fromEntries(lista(res.data?.categorias).map((c) => [c.categoria_id, c.monto]));
      setMontos((actual) => Object.fromEntries(Object.entries(actual).map(([id, v]) => [
        id, previos[id] ? String(previos[id]) : v])));
      avisar(t('gastos.copiado_anterior', { anio: anio - 1 }), { tono: 'exito' });
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_cargar')));
    }
  };

  const guardar = async (e) => {
    e.preventDefault();
    setGuardando(true);
    try {
      const categorias = Object.entries(montos).map(([id, v]) => ({
        categoria_id: Number(id), monto: (Math.round((Number(v) || 0) * 100) / 100).toFixed(2) }));
      const res = await api.put(`/gastos/presupuesto/${anio}`, { categorias });
      setDatos(res.data);
      avisar(t('gastos.presupuesto_guardado', { anio }), { tono: 'exito' });
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
    } finally {
      setGuardando(false);
    }
  };

  const total = Object.values(montos).reduce((s, v) => s + (Number(v) || 0), 0);

  return (
    <GlassCard relleno="24px" style={{ marginBottom: '20px' }}>
      <div className="titulo-bloque-fila">
        <h2 className="titulo-bloque"><PiggyBank size={20} color="var(--accent-primary)" />{t('gastos.presupuesto_de', { anio })}</h2>
        <button type="button" className="btn-secondary metricas-boton" onClick={copiarAnterior} disabled={!datos}>
          <Copy size={15} /> {t('gastos.copiar_anterior', { anio: anio - 1 })}
        </button>
      </div>
      <p className="metricas-nota gastos-ayuda-grafica">{t('gastos.presupuesto_ayuda')}</p>
      <Aviso texto={aviso} tono="peligro" />
      {!datos ? <EsqueletoLista filas={3} /> : (
        <Formulario onSubmit={guardar}>
          <div className="gasto-presupuesto">
            <div className="gasto-presupuesto-fila gasto-presupuesto-fila--cabeza" aria-hidden="true">
              <span>{t('gastos.categoria')}</span><span>{t('gastos.presupuesto')}</span>
              <span>{t('gastos.gastado')}</span><span>{t('gastos.consumo')}</span>
            </div>
            {lista(datos.categorias).map((c) => {
              const monto = Number(montos[c.categoria_id]) || 0;
              const consumo = monto ? c.gastado / monto : null;
              return (
                <div key={c.categoria_id} className="gasto-presupuesto-fila">
                  <label htmlFor={`p-${c.categoria_id}`} className="gasto-presupuesto-nombre">
                    {c.nombre}{!c.activa && <span className="chip-dato">{t('gastos.retirada')}</span>}
                  </label>
                  <input id={`p-${c.categoria_id}`} className="form-input" type="number" inputMode="decimal"
                    min="0" step="0.01" value={montos[c.categoria_id] ?? ''} placeholder="0.00"
                    onChange={(e) => setMontos((m) => ({ ...m, [c.categoria_id]: e.target.value }))} />
                  <span className="gasto-presupuesto-cifra">
                    <span className="gasto-presupuesto-rotulo">{t('gastos.gastado')}</span>
                    {dineroTexto(c.gastado, idioma, { decimales: 0 })}
                  </span>
                  <span className={`gasto-presupuesto-cifra${consumo > 1 ? ' gasto-presupuesto-cifra--peligro' : ''}`}>
                    <span className="gasto-presupuesto-rotulo">{t('gastos.consumo')}</span>
                    {consumo === null ? '—' : new Intl.NumberFormat(localeDe(idioma), { style: 'percent' }).format(consumo)}
                  </span>
                </div>
              );
            })}
            <div className="gasto-presupuesto-fila gasto-presupuesto-fila--total">
              <span>{t('gastos.total')}</span>
              <strong>{dinero(total, idioma, { decimales: 0 })}</strong>
            </div>
          </div>
          <div className="gasto-formulario-pie">
            <button type="submit" className="btn-acento" disabled={guardando}>
              <Save size={15} /> {guardando ? t('temas.guardando') : t('gastos.guardar_presupuesto')}
            </button>
          </div>
        </Formulario>
      )}
    </GlassCard>
  );
}

function Categorias({ categorias, onCambio }) {
  const { t } = useTranslation();
  const [nueva, setNueva] = useState('');
  const [editando, setEditando] = useState(null);
  const [nombre, setNombre] = useState('');
  const [aviso, setAviso] = useState('');

  const crear = async (e) => {
    e.preventDefault();
    if (!nueva.trim()) return;
    try {
      await api.post('/gastos/categorias', { nombre: nueva.trim() });
      setNueva('');
      setAviso('');
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
    }
  };

  const editar = async (c, cambios) => {
    try {
      await api.patch(`/gastos/categorias/${c.id}`, cambios);
      setEditando(null);
      setAviso('');
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
    }
  };

  return (
    <>
      <ul className="gasto-catalogo">
        {categorias.map((c) => (
          <li key={c.id} className={c.activa ? '' : 'gasto-catalogo--retirada'}>
            {editando === c.id ? (
              <Formulario className="gasto-catalogo-editar" onSubmit={(e) => { e.preventDefault(); editar(c, { nombre }); }}>
                <input className="form-input" value={nombre} onChange={(e) => setNombre(e.target.value)} maxLength={80}
                  required aria-label={t('gastos.nombre')} autoFocus />
                <button type="submit" className="boton-mini" aria-label={t('temas.guardar')}><Check size={14} /></button>
                <button type="button" className="boton-mini" onClick={() => setEditando(null)} aria-label={t('temas.cancelar')}><X size={14} /></button>
              </Formulario>
            ) : (
              <>
                <span className="gasto-catalogo-nombre">{c.nombre}</span>
                <span className="gasto-catalogo-meta">
                  {t('gastos.n_gastos', { count: c.n })}{!c.activa && ` · ${t('gastos.retirada')}`}
                </span>
                <span className="gasto-catalogo-acciones">
                  <button type="button" className="boton-mini" title={t('gastos.renombrar')} aria-label={`${t('gastos.renombrar')}: ${c.nombre}`}
                    onClick={() => { setEditando(c.id); setNombre(c.nombre); }}><Pencil size={14} /></button>
                  <button type="button" className="boton-mini"
                    title={c.activa ? t('gastos.retirar') : t('gastos.devolver')}
                    aria-label={`${c.activa ? t('gastos.retirar') : t('gastos.devolver')}: ${c.nombre}`}
                    onClick={() => editar(c, { activa: !c.activa })}>
                    {c.activa ? <Archive size={14} /> : <ArchiveRestore size={14} />}
                  </button>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
      <Formulario className="gasto-catalogo-nuevo" onSubmit={crear}>
        <input className="form-input" value={nueva} onChange={(e) => setNueva(e.target.value)} maxLength={80}
          placeholder={t('gastos.categoria_nueva')} aria-label={t('gastos.categoria_nueva')} />
        <button type="submit" className="btn-secondary metricas-boton"><Plus size={15} /> {t('gastos.agregar')}</button>
      </Formulario>
      <p className="nota-suave">{t('gastos.categorias_ayuda')}</p>
      <Aviso texto={aviso} tono="peligro" />
    </>
  );
}

function Proveedores({ proveedores, onCambio }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [nuevo, setNuevo] = useState({ nombre: '', rfc: '' });
  const [editando, setEditando] = useState(null);
  const [borrar, setBorrar] = useState(null);
  const [aviso, setAviso] = useState('');

  const crear = async (e) => {
    e.preventDefault();
    try {
      await api.post('/gastos/proveedores', { nombre: nuevo.nombre.trim(), rfc: nuevo.rfc.trim() || null });
      setNuevo({ nombre: '', rfc: '' });
      setAviso('');
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
    }
  };

  const guardar = async (e) => {
    e.preventDefault();
    try {
      await api.patch(`/gastos/proveedores/${editando.id}`, { nombre: editando.nombre.trim(), rfc: editando.rfc.trim() });
      setEditando(null);
      setAviso('');
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
    }
  };

  const quitar = async () => {
    const p = borrar;
    setBorrar(null);
    try {
      await api.delete(`/gastos/proveedores/${p.id}`);
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_borrar')));
    }
  };

  return (
    <>
      {proveedores.length === 0 && <p className="metricas-vacio">{t('gastos.sin_proveedores')}</p>}
      <ul className="gasto-catalogo">
        {proveedores.map((p) => (
          <li key={p.id}>
            {editando?.id === p.id ? (
              <Formulario className="gasto-catalogo-editar" onSubmit={guardar}>
                <input className="form-input" value={editando.nombre} maxLength={150} required aria-label={t('gastos.nombre')}
                  onChange={(e) => setEditando({ ...editando, nombre: e.target.value })} autoFocus />
                <input className="form-input gasto-catalogo-rfc" value={editando.rfc} maxLength={13} aria-label={t('gastos.rfc')}
                  placeholder={t('gastos.rfc')} onChange={(e) => setEditando({ ...editando, rfc: e.target.value.toUpperCase() })} />
                <button type="submit" className="boton-mini" aria-label={t('temas.guardar')}><Check size={14} /></button>
                <button type="button" className="boton-mini" onClick={() => setEditando(null)} aria-label={t('temas.cancelar')}><X size={14} /></button>
              </Formulario>
            ) : (
              <>
                <span className="gasto-catalogo-nombre">
                  {p.nombre}{p.rfc && <span className="gasto-rfc">{p.rfc}</span>}
                </span>
                <span className="gasto-catalogo-meta">
                  {t('gastos.n_gastos', { count: p.n })}
                  {p.n > 0 && ` · ${dineroTexto(p.total_mxn, idioma, { decimales: 0 })}`}
                  {p.categoria_habitual && ` · ${p.categoria_habitual.nombre}`}
                </span>
                <span className="gasto-catalogo-acciones">
                  <button type="button" className="boton-mini" title={t('gastos.editar')} aria-label={`${t('gastos.editar')}: ${p.nombre}`}
                    onClick={() => setEditando({ id: p.id, nombre: p.nombre, rfc: p.rfc || '' })}><Pencil size={14} /></button>
                  {p.n === 0 && (
                    <button type="button" className="boton-mini" title={t('gastos.borrar')} aria-label={`${t('gastos.borrar')}: ${p.nombre}`}
                      onClick={() => setBorrar(p)}><Trash2 size={14} /></button>
                  )}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
      <Formulario className="gasto-catalogo-nuevo" onSubmit={crear}>
        <input className="form-input" value={nuevo.nombre} onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })}
          maxLength={150} required placeholder={t('gastos.proveedor_nombre')} aria-label={t('gastos.proveedor_nombre')} />
        <input className="form-input gasto-catalogo-rfc" value={nuevo.rfc} maxLength={13}
          onChange={(e) => setNuevo({ ...nuevo, rfc: e.target.value.toUpperCase() })}
          placeholder={t('gastos.rfc_opcional')} aria-label={t('gastos.rfc_opcional')} />
        <button type="submit" className="btn-secondary metricas-boton"><Plus size={15} /> {t('gastos.agregar')}</button>
      </Formulario>
      <p className="nota-suave">{t('gastos.proveedores_ayuda')}</p>
      <Aviso texto={aviso} tono="peligro" />
      {borrar && (
        <Confirmacion titulo={t('gastos.borrar_proveedor')} mensaje={t('gastos.borrar_proveedor_mensaje', { nombre: borrar.nombre })}
          textoConfirmar={t('gastos.borrar')} tono="peligro" onConfirmar={quitar} onCancelar={() => setBorrar(null)} />
      )}
    </>
  );
}
