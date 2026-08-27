import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import {
  BookOpen, Plus, Search, Pencil, Trash2, Check, X, EyeOff,
  AlertTriangle, Sparkles, ChevronDown, ChevronRight
} from 'lucide-react';

const CATEGORIAS = [
  'procedimiento', 'red', 'inventario_logico', 'proveedor', 'credenciales', 'otro'
];

/**
 * Documentación operativa de TI.
 *
 * Lo que hoy vive en la cabeza de dos personas y en un Excel que nadie
 * encuentra: cómo dar de alta telefonía, qué VLAN es cuál, a quién se le llama
 * cuando falla el enlace.
 *
 * Solo admin. Es el único contenido del portal con esa restricción absoluta.
 */
const DocumentacionTI = () => {
  const { t, i18n } = useTranslation();

  const [documentos, setDocumentos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [busqueda, setBusqueda] = useState('');
  const [porSignificado, setPorSignificado] = useState(false);
  const [categoria, setCategoria] = useState('');
  const [creando, setCreando] = useState(false);
  const [editando, setEditando] = useState(null);
  const [abierto, setAbierto] = useState(null);
  const [aviso, setAviso] = useState('');

  const cargar = async () => {
    setCargando(true);
    try {
      if (porSignificado && busqueda.trim().length >= 3) {
        setDocumentos((await api.post('/documentacion/buscar', { texto: busqueda.trim() })).data);
      } else {
        const params = new URLSearchParams();
        if (categoria) params.set('categoria', categoria);
        if (busqueda) params.set('buscar', busqueda);
        setDocumentos((await api.get(`/documentacion?${params}`)).data);
      }
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('docti.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    const temporizador = setTimeout(cargar, busqueda ? 400 : 0);
    return () => clearTimeout(temporizador);
  }, [busqueda, categoria, porSignificado]);

  const guardar = async (datos, id) => {
    try {
      if (id) await api.patch(`/documentacion/${id}`, datos);
      else await api.post('/documentacion', datos);
      setCreando(false);
      setEditando(null);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('docti.error_guardar'));
    }
  };

  const borrar = async (d) => {
    if (!window.confirm(t('docti.confirmar_borrar', { titulo: d.titulo }))) return;
    try {
      await api.delete(`/documentacion/${d.id}`);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('docti.error_borrar'));
    }
  };

  const fecha = (iso) => iso ? new Date(iso).toLocaleDateString(i18n.language, {
    day: '2-digit', month: 'short', year: 'numeric'
  }) : '';

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1020px' }}>
      <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '6px', color: 'var(--text-primary)' }}>
        {t('docti.title')}
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '26px' }}>
        {t('docti.subtitle')}
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

      <div style={{ display: 'flex', gap: '10px', marginBottom: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button onClick={() => { setCreando(true); setEditando(null); }} className="btn-primary"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <Plus size={16} /> {t('docti.nuevo')}
        </button>

        <div style={{ position: 'relative', flex: 1, minWidth: '220px' }}>
          <Search size={16} style={{
            position: 'absolute', left: '12px', top: '50%',
            transform: 'translateY(-50%)', color: 'var(--text-muted)'
          }} />
          <input className="form-input" value={busqueda} onChange={(e) => setBusqueda(e.target.value)}
            placeholder={porSignificado ? t('docti.buscar_significado') : t('docti.buscar')}
            style={{ width: '100%', paddingLeft: '38px' }} />
        </div>

        <select className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}
          disabled={porSignificado} style={{ maxWidth: '210px' }}>
          <option value="">{t('docti.todas')}</option>
          {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`docti.cat_${c}`)}</option>)}
        </select>
      </div>

      {/* La búsqueda por significado encuentra el procedimiento aunque no se
          recuerde cómo se titulaba. */}
      <label style={{
        display: 'inline-flex', alignItems: 'center', gap: '8px',
        fontSize: '0.85rem', color: 'var(--text-secondary)',
        cursor: 'pointer', marginBottom: '20px'
      }}>
        <input type="checkbox" checked={porSignificado}
          onChange={(e) => setPorSignificado(e.target.checked)}
          style={{ width: '16px', height: '16px', cursor: 'pointer' }} />
        <Sparkles size={14} color="var(--accent-primary)" />
        {t('docti.por_significado')}
      </label>

      {creando && (
        <Formulario onGuardar={(d) => guardar(d)} onCancelar={() => setCreando(false)} />
      )}

      {cargando ? (
        <EsqueletoLista filas={3} />
      ) : documentos.length === 0 ? (
        <div className="apple-card" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
          {busqueda ? t('docti.sin_resultados') : t('docti.vacio')}
        </div>
      ) : (
        <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {documentos.map((d) => (
            editando === d.id ? (
              <Formulario key={d.id} documento={d}
                onGuardar={(datos) => guardar(datos, d.id)}
                onCancelar={() => setEditando(null)} />
            ) : (
              <div key={d.id} className="apple-card" style={{ padding: '20px 22px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
                  <button
                    onClick={() => setAbierto(abierto === d.id ? null : d.id)}
                    style={{
                      flex: 1, minWidth: '240px', textAlign: 'left', border: 'none',
                      background: 'none', cursor: 'pointer', padding: 0
                    }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
                      {abierto === d.id
                        ? <ChevronDown size={16} color="var(--text-muted)" />
                        : <ChevronRight size={16} color="var(--text-muted)" />}
                      <span style={{
                        fontSize: '0.72rem', fontWeight: '600', padding: '3px 10px',
                        borderRadius: 'var(--radius-full)',
                        color: 'var(--accent-primary)', background: 'rgba(0,122,255,0.10)'
                      }}>
                        {t(`docti.cat_${d.categoria}`)}
                      </span>
                      {d.sensible && (
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', gap: '5px',
                          fontSize: '0.72rem', fontWeight: '600', padding: '3px 10px',
                          borderRadius: 'var(--radius-full)',
                          color: 'var(--status-espera-proveedor-text)',
                          background: 'var(--status-espera-proveedor-bg)'
                        }}>
                          <EyeOff size={11} /> {t('docti.sensible')}
                        </span>
                      )}
                    </div>
                    <div style={{ fontWeight: '600', color: 'var(--text-primary)', fontSize: '1rem', paddingLeft: '26px' }}>
                      {d.titulo}
                    </div>
                    {d.etiquetas && (
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', paddingLeft: '26px', marginTop: '4px' }}>
                        {d.etiquetas}
                      </div>
                    )}
                  </button>

                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                    <button onClick={() => { setEditando(d.id); setCreando(false); }}
                      className="btn-secondary" style={{ padding: '8px 12px' }}>
                      <Pencil size={15} />
                    </button>
                    <button onClick={() => borrar(d)} className="btn-secondary"
                      style={{ padding: '8px 12px', color: '#D8000C' }}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>

                {abierto === d.id && (
                  <div className="animate-appear" style={{ marginTop: '16px', paddingLeft: '26px' }}>
                    <div style={{
                      whiteSpace: 'pre-wrap', fontSize: '0.9rem', lineHeight: 1.65,
                      color: 'var(--text-primary)', background: 'var(--bg-tertiary)',
                      padding: '16px 18px', borderRadius: 'var(--radius-md)',
                      fontFamily: d.categoria === 'red' ? 'monospace' : 'inherit'
                    }}>
                      {d.contenido}
                    </div>
                    <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '10px' }}>
                      {d.autor_nombre && t('docti.creado_por', { quien: d.autor_nombre, fecha: fecha(d.creado_en) })}
                      {d.actualizado_en && ` · ${t('docti.editado_por', { quien: d.editor_nombre || '—', fecha: fecha(d.actualizado_en) })}`}
                    </div>
                  </div>
                )}
              </div>
            )
          ))}
        </div>
      )}
    </div>
  );
};

/* ================================================================ */
const Formulario = ({ documento, onGuardar, onCancelar }) => {
  const { t } = useTranslation();
  const [categoria, setCategoria] = useState(documento?.categoria || 'procedimiento');
  const [titulo, setTitulo] = useState(documento?.titulo || '');
  const [contenido, setContenido] = useState(documento?.contenido || '');
  const [etiquetas, setEtiquetas] = useState(documento?.etiquetas || '');
  const [sensible, setSensible] = useState(documento?.sensible || false);

  const valido = titulo.trim().length >= 4 && contenido.trim().length >= 10;

  return (
    <form className="apple-card animate-scale-in"
      style={{ padding: '26px', marginBottom: '16px', border: '1px solid var(--accent-primary)' }}
      onSubmit={(e) => {
        e.preventDefault();
        if (!valido) return;
        onGuardar({
          categoria, titulo: titulo.trim(), contenido: contenido.trim(),
          etiquetas: etiquetas.trim() || null, sensible
        });
      }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '16px' }}>
        <div className="form-group">
          <label>{t('docti.categoria')}</label>
          <select className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
            {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`docti.cat_${c}`)}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label>{t('docti.etiquetas')}</label>
          <input className="form-input" style={{ width: '100%' }} value={etiquetas}
            placeholder={t('docti.etiquetas_ejemplo')}
            onChange={(e) => setEtiquetas(e.target.value)} />
        </div>
      </div>

      <div className="form-group">
        <label>{t('docti.titulo_campo')}</label>
        <input className="form-input" required style={{ width: '100%' }} value={titulo}
          placeholder={t('docti.titulo_ejemplo')}
          onChange={(e) => setTitulo(e.target.value)} />
      </div>

      <div className="form-group">
        <label>{t('docti.contenido')}</label>
        <textarea className="form-textarea" rows={12} required value={contenido}
          placeholder={t('docti.contenido_ejemplo')}
          style={{ fontFamily: categoria === 'red' ? 'monospace' : 'inherit', fontSize: '0.9rem' }}
          onChange={(e) => setContenido(e.target.value)} />
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', marginBottom: '18px' }}>
        <input type="checkbox" checked={sensible} onChange={(e) => setSensible(e.target.checked)}
          style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
        <span style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>
          {t('docti.marcar_sensible')}
        </span>
      </label>

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        <button type="button" onClick={onCancelar} className="btn-secondary" style={{ padding: '10px 18px' }}>
          <X size={15} /> {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-primary" disabled={!valido} style={{ padding: '10px 18px' }}>
          <Check size={15} /> {t('temas.guardar')}
        </button>
      </div>
    </form>
  );
};

export default DocumentacionTI;
