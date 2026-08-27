import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import {
  ListChecks, BookOpen, Sparkles, Plus, Trash2, Pencil,
  Check, X, EyeOff, Eye, AlertTriangle, TrendingUp
} from 'lucide-react';

const CATEGORIAS = ['impresora', 'red', 'equipo', 'software', 'accesos', 'otro'];

/**
 * Administración de temas.
 *
 * Tres cosas que el admin necesita poder hacer sin tocar la base de datos:
 * editar los pasos de diagnóstico, mantener la base de conocimiento, y revisar
 * los problemas recurrentes que el portal detectó y todavía no tiene cubiertos.
 */
const Temas = () => {
  const { t } = useTranslation();
  const [pestana, setPestana] = useState('pasos');

  const pestanas = [
    { id: 'pasos', icono: <ListChecks size={17} />, texto: t('temas.tab_pasos') },
    { id: 'kb', icono: <BookOpen size={17} />, texto: t('temas.tab_kb') },
    { id: 'detectados', icono: <Sparkles size={17} />, texto: t('temas.tab_detectados') }
  ];

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1000px' }}>
      <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-primary)' }}>
        {t('temas.title')}
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '28px' }}>
        {t('temas.subtitle')}
      </p>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '28px', flexWrap: 'wrap' }}>
        {pestanas.map((p) => (
          <button
            key={p.id}
            onClick={() => setPestana(p.id)}
            className={pestana === p.id ? 'btn-primary' : 'btn-secondary'}
            style={{ padding: '10px 18px', fontSize: '0.9rem' }}
          >
            {p.icono}
            {p.texto}
          </button>
        ))}
      </div>

      {pestana === 'pasos' && <Pasos />}
      {pestana === 'kb' && <Conocimiento />}
      {pestana === 'detectados' && <Detectados />}
    </div>
  );
};

/* ================================================================
   Pasos de checklist
   ================================================================ */
const Pasos = () => {
  const { t } = useTranslation();
  const [pasos, setPasos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [filtro, setFiltro] = useState('');
  const [editando, setEditando] = useState(null);
  const [creando, setCreando] = useState(false);
  const [aviso, setAviso] = useState('');

  const cargar = async () => {
    setCargando(true);
    try {
      const res = await api.get('/admin/pasos?incluir_inactivos=true');
      setPasos(res.data);
    } catch (err) {
      setAviso(t('temas.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  const guardar = async (datos, id) => {
    try {
      if (id) await api.patch(`/admin/pasos/${id}`, datos);
      else await api.post('/admin/pasos', datos);
      setEditando(null);
      setCreando(false);
      setAviso('');
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('temas.error_guardar'));
    }
  };

  const alternarActivo = async (paso) => {
    await api.patch(`/admin/pasos/${paso.id}`, { activo: !paso.activo });
    cargar();
  };

  const eliminar = async (paso) => {
    if (!window.confirm(t('temas.confirmar_baja'))) return;
    await api.delete(`/admin/pasos/${paso.id}`);
    cargar();
  };

  if (cargando) return <EsqueletoLista filas={4} />;

  const visibles = filtro ? pasos.filter((p) => p.categoria === filtro) : pasos;

  return (
    <div>
      {aviso && <Aviso texto={aviso} />}

      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap', alignItems: 'center' }}>
        <select className="form-select" value={filtro} onChange={(e) => setFiltro(e.target.value)}
          style={{ maxWidth: '260px' }}>
          <option value="">{t('temas.todas_categorias')}</option>
          {CATEGORIAS.map((c) => (
            <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>
          ))}
        </select>
        <button onClick={() => { setCreando(true); setEditando(null); }} className="btn-primary"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <Plus size={16} />
          {t('temas.nuevo_paso')}
        </button>
      </div>

      {creando && (
        <FormularioPaso
          categoriaInicial={filtro || 'equipo'}
          onGuardar={(d) => guardar(d)}
          onCancelar={() => setCreando(false)}
        />
      )}

      {visibles.length === 0 && !creando && <Vacio texto={t('temas.sin_pasos')} />}

      <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {visibles.map((paso) => (
          editando === paso.id ? (
            <FormularioPaso
              key={paso.id}
              paso={paso}
              categoriaInicial={paso.categoria}
              onGuardar={(d) => guardar(d, paso.id)}
              onCancelar={() => setEditando(null)}
            />
          ) : (
            <div key={paso.id} className="apple-card" style={{
              padding: '18px 20px',
              opacity: paso.activo ? 1 : 0.55,
              borderLeft: paso.resuelve ? '3px solid var(--status-resuelto-text)' : '3px solid transparent'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: '240px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
                    <Etiqueta texto={t(`new_ticket.category_${paso.categoria}`)} />
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>#{paso.orden}</span>
                    {paso.resuelve && (
                      <Etiqueta texto={t('temas.resuelve')} tono="verde" />
                    )}
                    {!paso.activo && <Etiqueta texto={t('temas.inactivo')} tono="gris" />}
                  </div>
                  <div style={{ fontWeight: '600', color: 'var(--text-primary)', marginBottom: '6px', lineHeight: 1.4 }}>
                    {paso.pregunta_texto || paso.pregunta_key}
                  </div>
                  {paso.accion_si_no && (
                    <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                      {paso.accion_si_no}
                    </div>
                  )}
                  {paso.veces_resolvio > 0 && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--status-resuelto-text)', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <TrendingUp size={14} />
                      {t('temas.resolvio_veces', { n: paso.veces_resolvio })}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                  <button onClick={() => { setEditando(paso.id); setCreando(false); }}
                    className="btn-secondary" style={{ padding: '8px 12px' }} title={t('temas.editar')}>
                    <Pencil size={15} />
                  </button>
                  <button onClick={() => alternarActivo(paso)} className="btn-secondary"
                    style={{ padding: '8px 12px' }} title={paso.activo ? t('temas.ocultar') : t('temas.mostrar')}>
                    {paso.activo ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                  <button onClick={() => eliminar(paso)} className="btn-secondary"
                    style={{ padding: '8px 12px', color: '#D8000C' }} title={t('temas.dar_baja')}>
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  );
};

const FormularioPaso = ({ paso, categoriaInicial, onGuardar, onCancelar }) => {
  const { t } = useTranslation();
  const [categoria, setCategoria] = useState(paso?.categoria || categoriaInicial);
  const [pregunta, setPregunta] = useState(paso?.pregunta_texto || '');
  const [accion, setAccion] = useState(paso?.accion_si_no || '');
  const [resuelve, setResuelve] = useState(paso?.resuelve || false);

  const valido = pregunta.trim().length >= 5;

  return (
    <form
      className="apple-card animate-scale-in"
      style={{ padding: '22px', marginBottom: '14px', border: '1px solid var(--accent-primary)' }}
      onSubmit={(e) => {
        e.preventDefault();
        if (!valido) return;
        onGuardar({
          categoria,
          pregunta_texto: pregunta.trim(),
          accion_si_no: accion.trim() || null,
          resuelve
        });
      }}
    >
      <div className="form-group">
        <label>{t('ticket.categoria')}</label>
        <select className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
          {CATEGORIAS.map((c) => (
            <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>
          ))}
        </select>
      </div>

      <div className="form-group">
        <label>{t('temas.pregunta')}</label>
        <textarea className="form-textarea" rows={2} value={pregunta} required
          placeholder={t('temas.pregunta_ejemplo')}
          onChange={(e) => setPregunta(e.target.value)} />
      </div>

      <div className="form-group">
        <label>{t('temas.accion')}</label>
        <textarea className="form-textarea" rows={2} value={accion}
          placeholder={t('temas.accion_ejemplo')}
          onChange={(e) => setAccion(e.target.value)} />
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', marginBottom: '18px' }}>
        <input type="checkbox" checked={resuelve} onChange={(e) => setResuelve(e.target.checked)}
          style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
        <span style={{ fontSize: '0.92rem', color: 'var(--text-primary)' }}>
          {t('temas.marca_resuelve')}
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

/* ================================================================
   Base de conocimiento
   ================================================================ */
const Conocimiento = () => {
  const { t } = useTranslation();
  const [entradas, setEntradas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [creando, setCreando] = useState(false);
  const [editando, setEditando] = useState(null);
  const [aviso, setAviso] = useState('');

  const cargar = async () => {
    setCargando(true);
    try {
      setEntradas((await api.get('/admin/kb')).data);
    } catch {
      setAviso(t('temas.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  const guardar = async (datos, id) => {
    try {
      if (id) await api.patch(`/admin/kb/${id}`, datos);
      else await api.post('/admin/kb', datos);
      setCreando(false);
      setEditando(null);
      setAviso('');
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('temas.error_guardar'));
    }
  };

  const eliminar = async (entrada) => {
    if (!window.confirm(t('temas.confirmar_borrar_kb'))) return;
    await api.delete(`/admin/kb/${entrada.id}`);
    cargar();
  };

  if (cargando) return <EsqueletoLista filas={3} />;

  return (
    <div>
      {aviso && <Aviso texto={aviso} />}

      <button onClick={() => { setCreando(true); setEditando(null); }} className="btn-primary"
        style={{ padding: '10px 18px', fontSize: '0.9rem', marginBottom: '20px' }}>
        <Plus size={16} /> {t('temas.nueva_entrada')}
      </button>

      {creando && <FormularioKB onGuardar={(d) => guardar(d)} onCancelar={() => setCreando(false)} />}

      {entradas.length === 0 && !creando && <Vacio texto={t('temas.sin_kb')} />}

      <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {entradas.map((e) => (
          editando === e.id ? (
            <FormularioKB key={e.id} entrada={e} onGuardar={(d) => guardar(d, e.id)} onCancelar={() => setEditando(null)} />
          ) : (
            <div key={e.id} className="apple-card" style={{ padding: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: '240px' }}>
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                    <Etiqueta texto={t(`new_ticket.category_${e.categoria}`)} />
                    {!e.tiene_embedding && <Etiqueta texto={t('temas.sin_vector')} tono="ambar" />}
                    {e.ticket_origen_id && <Etiqueta texto={t('temas.desde_ticket')} tono="gris" />}
                  </div>
                  <div style={{ fontWeight: '600', color: 'var(--text-primary)', marginBottom: '6px' }}>{e.titulo}</div>
                  <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.5, whiteSpace: 'pre-line' }}>
                    {e.contenido}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '10px' }}>
                    {t('temas.mostrada_veces', { n: e.veces_sugerida })}
                    {e.tasa_utilidad !== null && ` · ${t('temas.util_pct', { pct: e.tasa_utilidad })}`}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                  <button onClick={() => { setEditando(e.id); setCreando(false); }} className="btn-secondary" style={{ padding: '8px 12px' }}>
                    <Pencil size={15} />
                  </button>
                  <button onClick={() => eliminar(e)} className="btn-secondary" style={{ padding: '8px 12px', color: '#D8000C' }}>
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  );
};

const FormularioKB = ({ entrada, onGuardar, onCancelar }) => {
  const { t } = useTranslation();
  const [titulo, setTitulo] = useState(entrada?.titulo || '');
  const [contenido, setContenido] = useState(entrada?.contenido || '');
  const [categoria, setCategoria] = useState(entrada?.categoria || 'equipo');

  const valido = titulo.trim().length >= 5 && contenido.trim().length >= 20;

  return (
    <form className="apple-card animate-scale-in"
      style={{ padding: '22px', marginBottom: '14px', border: '1px solid var(--accent-primary)' }}
      onSubmit={(e) => {
        e.preventDefault();
        if (!valido) return;
        onGuardar({ titulo: titulo.trim(), contenido: contenido.trim(), categoria });
      }}>
      <div className="form-group">
        <label>{t('ticket.categoria')}</label>
        <select className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
          {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>)}
        </select>
      </div>
      <div className="form-group">
        <label>{t('temas.titulo_entrada')}</label>
        <input className="form-input" value={titulo} required style={{ width: '100%' }}
          placeholder={t('temas.titulo_ejemplo')} onChange={(e) => setTitulo(e.target.value)} />
      </div>
      <div className="form-group">
        <label>{t('temas.solucion_entrada')}</label>
        <textarea className="form-textarea" rows={5} value={contenido} required
          placeholder={t('temas.solucion_ejemplo')} onChange={(e) => setContenido(e.target.value)} />
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
          {t('temas.nota_vector')}
        </div>
      </div>
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

/* ================================================================
   Temas detectados automáticamente
   ================================================================ */
const Detectados = () => {
  const { t } = useTranslation();
  const [temas, setTemas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [promoviendo, setPromoviendo] = useState(null);

  const cargar = async () => {
    setCargando(true);
    try {
      setTemas((await api.get('/admin/temas-sugeridos')).data);
    } catch {
      setTemas([]);
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  const descartar = async (tema) => {
    await api.post(`/admin/temas-sugeridos/${tema.id}/descartar`);
    cargar();
  };

  if (cargando) return <EsqueletoLista filas={2} />;

  if (temas.length === 0) {
    return (
      <Vacio
        texto={t('temas.sin_detectados')}
        detalle={t('temas.sin_detectados_detalle')}
      />
    );
  }

  return (
    <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {temas.map((tema) => (
        <div key={tema.id} className="apple-card" style={{
          padding: '22px',
          borderLeft: tema.estado === 'listo' ? '3px solid var(--accent-primary)' : '3px solid transparent'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px', flexWrap: 'wrap' }}>
            <Etiqueta
              texto={t('temas.veces_reportado', { n: tema.ocurrencias })}
              tono={tema.estado === 'listo' ? 'azul' : 'gris'}
            />
            {tema.estado === 'listo' && <Etiqueta texto={t('temas.listo_promover')} tono="verde" />}
          </div>

          <div style={{ fontWeight: '600', color: 'var(--text-primary)', marginBottom: '8px', lineHeight: 1.4 }}>
            {tema.titulo}
          </div>

          {tema.soluciones_previas.length > 0 && (
            <div style={{
              marginTop: '14px', padding: '14px', background: 'var(--bg-tertiary)',
              borderRadius: 'var(--radius-md)'
            }}>
              <div style={{ fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                {t('temas.como_se_resolvio')}
              </div>
              {tema.soluciones_previas.map((s) => (
                <div key={s.ticket_id} style={{ fontSize: '0.88rem', color: 'var(--text-primary)', marginBottom: '8px', lineHeight: 1.5 }}>
                  <strong style={{ color: 'var(--accent-primary)' }}>{s.folio}</strong> · {s.solucion}
                </div>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', marginTop: '18px', flexWrap: 'wrap' }}>
            <button onClick={() => setPromoviendo(promoviendo === tema.id ? null : tema.id)}
              className="btn-primary" style={{ padding: '9px 16px', fontSize: '0.88rem' }}>
              <Plus size={15} /> {t('temas.convertir')}
            </button>
            <button onClick={() => descartar(tema)} className="btn-secondary"
              style={{ padding: '9px 16px', fontSize: '0.88rem' }}>
              <X size={15} /> {t('temas.descartar')}
            </button>
          </div>

          {promoviendo === tema.id && (
            <FormularioPromover
              tema={tema}
              onListo={() => { setPromoviendo(null); cargar(); }}
              onCancelar={() => setPromoviendo(null)}
            />
          )}
        </div>
      ))}
    </div>
  );
};

const FormularioPromover = ({ tema, onListo, onCancelar }) => {
  const { t } = useTranslation();
  const [categoria, setCategoria] = useState(tema.categoria_sugerida || 'otro');
  const [pregunta, setPregunta] = useState('');
  const [accion, setAccion] = useState(
    tema.soluciones_previas[0]?.solucion || ''
  );
  const [guardando, setGuardando] = useState(false);

  const enviar = async (e) => {
    e.preventDefault();
    setGuardando(true);
    try {
      await api.post(`/admin/temas-sugeridos/${tema.id}/promover`, {
        categoria,
        pasos: pregunta.trim().length >= 5
          ? [{ categoria, pregunta_texto: pregunta.trim(), accion_si_no: accion.trim() || null, resuelve: true }]
          : []
      });
      onListo();
    } finally {
      setGuardando(false);
    }
  };

  return (
    <form onSubmit={enviar} className="animate-scale-in" style={{
      marginTop: '18px', paddingTop: '18px', borderTop: '1px solid var(--border-color)'
    }}>
      <div className="form-group">
        <label>{t('temas.en_que_categoria')}</label>
        <select className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
          {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>)}
        </select>
      </div>
      <div className="form-group">
        <label>{t('temas.pregunta_nueva')}</label>
        <textarea className="form-textarea" rows={2} value={pregunta}
          placeholder={t('temas.pregunta_ejemplo')} onChange={(e) => setPregunta(e.target.value)} />
      </div>
      <div className="form-group">
        <label>{t('temas.accion')}</label>
        <textarea className="form-textarea" rows={3} value={accion}
          onChange={(e) => setAccion(e.target.value)} />
        {tema.soluciones_previas.length > 0 && (
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
            {t('temas.prellenado_historial')}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        <button type="button" onClick={onCancelar} className="btn-secondary" style={{ padding: '9px 16px' }}>
          {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-primary" disabled={guardando} style={{ padding: '9px 16px' }}>
          <Check size={15} /> {guardando ? t('temas.guardando') : t('temas.crear_tema')}
        </button>
      </div>
    </form>
  );
};

/* ================================================================
   Piezas compartidas
   ================================================================ */
const TONOS = {
  azul: ['var(--accent-primary)', 'rgba(0,122,255,0.10)'],
  verde: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  ambar: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  gris: ['var(--text-secondary)', 'var(--bg-tertiary)']
};

const Etiqueta = ({ texto, tono = 'azul' }) => {
  const [color, fondo] = TONOS[tono] || TONOS.azul;
  return (
    <span style={{
      fontSize: '0.75rem', fontWeight: '600', padding: '4px 10px',
      borderRadius: 'var(--radius-full)', color, background: fondo
    }}>
      {texto}
    </span>
  );
};

const Aviso = ({ texto }) => (
  <div className="animate-scale-in" style={{
    display: 'flex', alignItems: 'center', gap: '10px',
    background: 'var(--status-espera-proveedor-bg)',
    color: 'var(--status-espera-proveedor-text)',
    padding: '14px 18px', borderRadius: 'var(--radius-md)',
    marginBottom: '18px', fontSize: '0.9rem'
  }}>
    <AlertTriangle size={18} /> {texto}
  </div>
);

const Vacio = ({ texto, detalle }) => (
  <div className="apple-card animate-appear" style={{
    padding: '48px 24px', textAlign: 'center', color: 'var(--text-muted)'
  }}>
    <div style={{ fontSize: '1rem', color: 'var(--text-secondary)', marginBottom: detalle ? '8px' : 0 }}>
      {texto}
    </div>
    {detalle && <div style={{ fontSize: '0.88rem', maxWidth: '460px', margin: '0 auto', lineHeight: 1.5 }}>{detalle}</div>}
  </div>
);

export default Temas;
