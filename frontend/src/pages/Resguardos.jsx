import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import {
  FileSignature, Plus, Download, RotateCcw, XCircle, AlertTriangle,
  Check, X, User, Laptop, Search
} from 'lucide-react';

const ESTADOS = {
  pendiente_firma: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  firmado: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  devuelto: ['var(--text-secondary)', 'var(--bg-tertiary)'],
  cancelado: ['#D8000C', '#FFF0F0']
};

/** Administración de resguardos: emitir, dar seguimiento y cerrar. */
const Resguardos = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  const [resguardos, setResguardos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [filtro, setFiltro] = useState('');
  const [busqueda, setBusqueda] = useState('');
  const [emitiendo, setEmitiendo] = useState(false);
  const [accion, setAccion] = useState(null);   // { tipo: 'devolver'|'cancelar', resguardo }
  const [aviso, setAviso] = useState('');

  const cargar = async () => {
    setCargando(true);
    try {
      const ruta = filtro ? `/resguardos?estado=${filtro}` : '/resguardos';
      setResguardos((await api.get(ruta)).data);
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('resguardos.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, [filtro]);

  const abrirPdf = async (r) => {
    try {
      const res = await api.get(`/resguardos/${r.id}/pdf`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank', 'noopener,noreferrer');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch { setAviso(t('resguardos.error_pdf')); }
  };

  const fecha = (iso) => iso ? new Date(iso).toLocaleDateString(i18n.language, {
    day: '2-digit', month: 'short', year: 'numeric'
  }) : '—';

  const visibles = resguardos.filter((r) => {
    if (!busqueda) return true;
    const q = busqueda.toLowerCase();
    return r.folio.toLowerCase().includes(q)
      || (r.usuario?.nombre || '').toLowerCase().includes(q)
      || (r.equipo ? `${r.equipo.marca} ${r.equipo.modelo} ${r.equipo.numero_serie || ''}`.toLowerCase().includes(q) : false);
  });

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1050px' }}>
      <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '6px', color: 'var(--text-primary)' }}>
        {t('resguardos.title')}
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '26px' }}>
        {t('resguardos.subtitle')}
      </p>

      {aviso && (
        <div className="animate-scale-in" style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          padding: '14px 18px', borderRadius: 'var(--radius-md)',
          marginBottom: '18px', fontSize: '0.9rem'
        }}>
          <AlertTriangle size={18} /> {aviso}
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button onClick={() => setEmitiendo(true)} className="btn-primary"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <Plus size={16} /> {t('resguardos.emitir')}
        </button>

        <div style={{ position: 'relative', flex: 1, minWidth: '200px' }}>
          <Search size={16} style={{
            position: 'absolute', left: '12px', top: '50%',
            transform: 'translateY(-50%)', color: 'var(--text-muted)'
          }} />
          <input className="form-input" value={busqueda} onChange={(e) => setBusqueda(e.target.value)}
            placeholder={t('resguardos.buscar')} style={{ width: '100%', paddingLeft: '38px' }} />
        </div>

        <select className="form-select" value={filtro} onChange={(e) => setFiltro(e.target.value)}
          style={{ maxWidth: '210px' }}>
          <option value="">{t('resguardos.todos')}</option>
          <option value="pendiente_firma">{t('resguardos.estado_pendiente_firma')}</option>
          <option value="firmado">{t('resguardos.estado_firmado')}</option>
          <option value="devuelto">{t('resguardos.estado_devuelto')}</option>
          <option value="cancelado">{t('resguardos.estado_cancelado')}</option>
        </select>
      </div>

      {emitiendo && (
        <FormularioEmision
          onCerrar={() => setEmitiendo(false)}
          onEmitido={() => { setEmitiendo(false); cargar(); }}
          onError={setAviso}
        />
      )}

      {cargando ? (
        <EsqueletoLista filas={4} />
      ) : visibles.length === 0 ? (
        <div className="apple-card" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
          {t('resguardos.sin_resultados')}
        </div>
      ) : (
        <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {visibles.map((r) => {
            const [color, fondo] = ESTADOS[r.estado] || ESTADOS.devuelto;
            const activo = ['pendiente_firma', 'firmado'].includes(r.estado);
            return (
              <div key={r.id} className="apple-card" style={{
                padding: '18px 22px', display: 'flex', justifyContent: 'space-between',
                gap: '18px', flexWrap: 'wrap',
                borderLeft: r.estado === 'pendiente_firma'
                  ? '3px solid var(--status-espera-proveedor-text)' : '3px solid transparent'
              }}>
                <div style={{ flex: 1, minWidth: '250px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px', flexWrap: 'wrap' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: '600', fontSize: '0.9rem', color: 'var(--accent-primary)' }}>
                      {r.folio}
                    </span>
                    <span style={{
                      fontSize: '0.74rem', fontWeight: '600', padding: '3px 10px',
                      borderRadius: 'var(--radius-full)', color, background: fondo
                    }}>
                      {t(`resguardos.estado_${r.estado}`)}
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', fontSize: '0.88rem' }}>
                    <button
                      onClick={() => navigate(`/expediente/${r.usuario_id}`)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '6px', border: 'none',
                        background: 'none', cursor: 'pointer', padding: 0,
                        color: 'var(--accent-primary)', fontWeight: '600', fontSize: '0.88rem'
                      }}
                      title={t('resguardos.ver_expediente')}
                    >
                      <User size={14} /> {r.usuario?.nombre || '—'}
                    </button>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                      <Laptop size={14} />
                      {r.equipo ? `${r.equipo.marca} ${r.equipo.modelo}` : '—'}
                      {r.equipo?.numero_serie && ` · ${r.equipo.numero_serie}`}
                    </span>
                  </div>

                  <div style={{ fontSize: '0.79rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                    {t('resguardos.entregado_el', { fecha: fecha(r.entregado_en) })}
                    {r.firmado_en && ` · ${t('resguardos.firmado_el', { fecha: fecha(r.firmado_en) })}`}
                    {r.devuelto_en && ` · ${t('resguardos.devuelto_el', { fecha: fecha(r.devuelto_en) })}`}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                  <button onClick={() => abrirPdf(r)} className="btn-secondary"
                    style={{ padding: '9px 13px' }} title={t('resguardos.ver_pdf')}>
                    <Download size={15} />
                  </button>
                  {activo && (
                    <button onClick={() => setAccion({ tipo: 'devolver', resguardo: r })}
                      className="btn-secondary" style={{ padding: '9px 14px', fontSize: '0.85rem' }}>
                      <RotateCcw size={15} /> {t('resguardos.devolver')}
                    </button>
                  )}
                  {r.estado === 'pendiente_firma' && (
                    <button onClick={() => setAccion({ tipo: 'cancelar', resguardo: r })}
                      className="btn-secondary" style={{ padding: '9px 13px', color: '#D8000C' }}
                      title={t('resguardos.cancelar')}>
                      <XCircle size={15} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {accion && (
        <DialogoAccion
          accion={accion}
          onCerrar={() => setAccion(null)}
          onListo={() => { setAccion(null); cargar(); }}
          onError={setAviso}
        />
      )}
    </div>
  );
};

/* ================================================================ */
const FormularioEmision = ({ onCerrar, onEmitido, onError }) => {
  const { t } = useTranslation();
  const [equipos, setEquipos] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [equipoId, setEquipoId] = useState('');
  const [usuarioId, setUsuarioId] = useState('');
  const [accesorios, setAccesorios] = useState('');
  const [observaciones, setObservaciones] = useState('');
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    // Solo se ofrecen equipos libres: uno asignado ya tiene resguardo vigente.
    api.get('/equipos').then((r) => setEquipos(r.data.filter((e) => e.estado === 'disponible')));
    api.get('/auth/usuarios').then((r) => setUsuarios(r.data)).catch(() => setUsuarios([]));
  }, []);

  const enviar = async (e) => {
    e.preventDefault();
    if (!equipoId || !usuarioId) return;
    setEnviando(true);
    try {
      await api.post('/resguardos', {
        equipo_id: parseInt(equipoId),
        usuario_id: parseInt(usuarioId),
        accesorios: accesorios.trim() || null,
        observaciones: observaciones.trim() || null
      });
      onEmitido();
    } catch (err) {
      onError(err.response?.data?.detail || t('resguardos.error_emitir'));
      setEnviando(false);
    }
  };

  return (
    <form onSubmit={enviar} className="apple-card animate-scale-in"
      style={{ padding: '26px', marginBottom: '20px', border: '1px solid var(--accent-primary)' }}>
      <h3 style={{ fontSize: '1.05rem', fontWeight: '700', marginBottom: '18px', color: 'var(--text-primary)' }}>
        {t('resguardos.emitir_titulo')}
      </h3>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
        <div className="form-group">
          <label>{t('resguardos.equipo')}</label>
          <select className="form-select" value={equipoId} required
            onChange={(e) => setEquipoId(e.target.value)}>
            <option value="">{t('resguardos.elija_equipo')}</option>
            {equipos.map((e) => (
              <option key={e.id} value={e.id}>
                {e.marca} {e.modelo} · {e.numero_serie || 'S/N'}
              </option>
            ))}
          </select>
          {equipos.length === 0 && (
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
              {t('resguardos.sin_equipos_libres')}
            </div>
          )}
        </div>

        <div className="form-group">
          <label>{t('resguardos.resguardante')}</label>
          <select className="form-select" value={usuarioId} required
            onChange={(e) => setUsuarioId(e.target.value)}>
            <option value="">{t('resguardos.elija_persona')}</option>
            {usuarios.map((u) => (
              <option key={u.id} value={u.id}>{u.nombre} · {u.email}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="form-group">
        <label>{t('resguardos.accesorios')}</label>
        <input className="form-input" style={{ width: '100%' }} value={accesorios}
          placeholder={t('resguardos.accesorios_ejemplo')}
          onChange={(e) => setAccesorios(e.target.value)} />
      </div>

      <div className="form-group">
        <label>{t('resguardos.observaciones')}</label>
        <textarea className="form-textarea" rows={2} value={observaciones}
          placeholder={t('resguardos.observaciones_ejemplo')}
          onChange={(e) => setObservaciones(e.target.value)} />
      </div>

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
        <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '10px 18px' }}>
          <X size={15} /> {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-primary" disabled={enviando || !equipoId || !usuarioId}
          style={{ padding: '10px 18px' }}>
          <Check size={15} /> {enviando ? t('temas.guardando') : t('resguardos.emitir')}
        </button>
      </div>
    </form>
  );
};

/* ================================================================ */
const DialogoAccion = ({ accion, onCerrar, onListo, onError }) => {
  const { t } = useTranslation();
  const [texto, setTexto] = useState('');
  const [estadoEquipo, setEstadoEquipo] = useState('disponible');
  const [enviando, setEnviando] = useState(false);

  const esDevolucion = accion.tipo === 'devolver';
  const valido = esDevolucion || texto.trim().length >= 5;

  const enviar = async (e) => {
    e.preventDefault();
    if (!valido) return;
    setEnviando(true);
    try {
      if (esDevolucion) {
        await api.post(`/resguardos/${accion.resguardo.id}/devolver`, {
          observaciones: texto.trim() || null,
          estado_equipo: estadoEquipo
        });
      } else {
        await api.post(`/resguardos/${accion.resguardo.id}/cancelar`, { motivo: texto.trim() });
      }
      onListo();
    } catch (err) {
      onError(err.response?.data?.detail || t('resguardos.error_accion'));
      setEnviando(false);
      onCerrar();
    }
  };

  return (
    <div onClick={onCerrar} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '20px', zIndex: 1000
    }}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={enviar}
        className="apple-card animate-scale-in" style={{ padding: '30px', maxWidth: '520px', width: '100%' }}>
        <h2 style={{ fontSize: '1.2rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-primary)' }}>
          {esDevolucion ? t('resguardos.devolver_titulo') : t('resguardos.cancelar_titulo')}
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '18px' }}>
          {accion.resguardo.folio} · {accion.resguardo.usuario?.nombre}
        </p>

        {esDevolucion && (
          <div className="form-group">
            <label>{t('resguardos.estado_del_equipo')}</label>
            <select className="form-select" value={estadoEquipo}
              onChange={(e) => setEstadoEquipo(e.target.value)}>
              <option value="disponible">{t('resguardos.equipo_disponible')}</option>
              <option value="mantenimiento">{t('resguardos.equipo_mantenimiento')}</option>
              <option value="baja">{t('resguardos.equipo_baja')}</option>
            </select>
          </div>
        )}

        <div className="form-group">
          <label>{esDevolucion ? t('resguardos.observaciones') : t('resguardos.motivo')}</label>
          <textarea className="form-textarea" rows={3} value={texto}
            required={!esDevolucion}
            placeholder={esDevolucion ? t('resguardos.observaciones_devolucion') : t('resguardos.motivo_ejemplo')}
            onChange={(e) => setTexto(e.target.value)} />
        </div>

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
          <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '11px 20px' }}>
            {t('temas.cancelar')}
          </button>
          <button type="submit" className="btn-primary" disabled={!valido || enviando}
            style={{ padding: '11px 20px' }}>
            <Check size={16} /> {enviando ? t('temas.guardando') : t('resguardos.confirmar')}
          </button>
        </div>
      </form>
    </div>
  );
};

export default Resguardos;
