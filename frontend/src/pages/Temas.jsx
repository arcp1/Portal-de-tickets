import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import Confirmacion from '../components/Confirmacion';
import Selector from '../components/Selector';
import EstadoVacio from '../components/EstadoVacio';
import Formulario from '../components/Formulario';
import {
  Plus, Trash2, Pencil,
  Check, X, EyeOff, Eye, AlertTriangle, TrendingUp
} from 'lucide-react';
import lista from '../lib/lista';
import { EditorImagenes, GaleriaImagenes } from '../components/ImagenesConocimiento';

const CATEGORIAS = ['impresora', 'red', 'equipo', 'software', 'accesos', 'otro'];

/**
 * Las tres pantallas de conocimiento que antes eran pestañas de «Temas».
 *
 * Temas mezclaba lo que se escribe a mano (pasos de diagnóstico, artículos)
 * con lo que espera revisión (lo que el portal detectó solo). Desde la
 * reorganización del 2026-10-05 cada una es una pestaña del módulo de
 * Conocimiento con su propia ruta, así que se puede enlazar, volver atrás y
 * abrir en otra pestaña del navegador. Las piezas de abajo no cambiaron.
 */
const Pagina = ({ titulo, subtitulo, children }) => (
  <div className="page-container animate-fade-in">
    <div className="page-header">
      <div>
        <h1 className="page-title">{titulo}</h1>
        <p>{subtitulo}</p>
      </div>
    </div>
    {children}
  </div>
);

export const PaginaPasos = () => {
  const { t } = useTranslation();
  return <Pagina titulo={t('temas.tab_pasos')} subtitulo={t('temas.sub_pasos')}><Pasos /></Pagina>;
};

export const PaginaArticulos = () => {
  const { t } = useTranslation();
  return <Pagina titulo={t('temas.tab_kb')} subtitulo={t('temas.sub_kb')}><Conocimiento /></Pagina>;
};

/** Lo que espera a una persona: los borradores que escribió la máquina y los
 *  problemas que el portal agrupó solo. Nada de esto le contesta a nadie
 *  mientras siga aquí. */
export const PaginaBandeja = () => {
  const { t } = useTranslation();
  return (
    <Pagina titulo={t('temas.bandeja_titulo')} subtitulo={t('temas.bandeja_sub')}>
      <Borradores />
      <h2 className="seccion-titulo-bandeja">{t('temas.tab_detectados')}</h2>
      <Detectados />
    </Pagina>
  );
};

/** Procedimientos y fichas visuales en borrador, con un enlace a donde se
 *  firman. Solo se listan: revisarlos es cosa de su pestaña. */
const Borradores = () => {
  const { t } = useTranslation();
  const [filas, setFilas] = useState(null);

  useEffect(() => {
    let vivo = true;
    Promise.allSettled([
      api.get('/admin/soluciones', { params: { estado: 'borrador' } }),
      api.get('/admin/visual', { params: { estado: 'borrador' } })
    ]).then(([sol, vis]) => {
      if (!vivo) return;
      const procedimientos = sol.status === 'fulfilled'
        ? lista(sol.value.data, 'los procedimientos').map((s) => ({
          clave: 'p' + s.id, titulo: s.titulo, tipo: 'procedimiento',
          ruta: '/conocimiento/procedimientos', categoria: s.categoria }))
        : [];
      const fichas = vis.status === 'fulfilled'
        ? lista(vis.value.data, 'las fichas visuales').map((f) => ({
          clave: 'v' + f.id, titulo: f.titulo, tipo: 'ficha',
          ruta: '/conocimiento/catalogo', categoria: f.categoria }))
        : [];
      setFilas([...procedimientos, ...fichas]);
    });
    return () => { vivo = false; };
  }, []);

  if (filas === null) return <EsqueletoLista filas={2} />;
  return (
    <section className="apple-card bandeja-borradores" aria-label={t('temas.borradores')}>
      <div className="bandeja-borradores-cabecera">
        <strong>{t('temas.borradores')}</strong>
        <span className="bandeja-cuenta">{filas.length}</span>
      </div>
      {filas.length === 0 ? (
        <p className="bandeja-vacia">{t('temas.sin_borradores')}</p>
      ) : (
        <ul className="bandeja-lista">
          {filas.map((f) => (
            <li key={f.clave}>
              <Etiqueta texto={t(`temas.borrador_${f.tipo}`)} tono={f.tipo === 'ficha' ? 'verde' : 'azul'} />
              <span className="bandeja-titulo">{f.titulo}</span>
              {f.categoria && (
                <span className="bandeja-categoria">
                  {t(`new_ticket.category_${f.categoria}`, { defaultValue: f.categoria })}
                </span>
              )}
              <Link viewTransition to={f.ruta} className="boton-texto">{t('temas.revisar')}</Link>
            </li>
          ))}
        </ul>
      )}
    </section>
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
  // El paso que está esperando el "¿seguro?". null = no hay pregunta abierta.
  const [porEliminar, setPorEliminar] = useState(null);

  const cargar = async () => {
    setCargando(true);
    try {
      const res = await api.get('/admin/pasos?incluir_inactivos=true');
      setPasos(lista(res.data, 'los pasos del tema'));
    } catch (err) {
      setAviso(t('temas.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  // Guardar devuelve lo guardado y no cierra nada: el formulario todavía
  // tiene que subir las imágenes que esperaban el id del paso nuevo.
  const guardar = async (datos, id) => {
    try {
      const res = id
        ? await api.patch(`/admin/pasos/${id}`, datos)
        : await api.post('/admin/pasos', datos);
      setAviso('');
      return res.data;
    } catch (err) {
      setAviso(err.response?.data?.detail || t('temas.error_guardar'));
      return null;
    }
  };

  const terminar = (fallidas = 0) => {
    setEditando(null);
    setCreando(false);
    if (fallidas) setAviso(t('imagenes.algunas_no_subieron', { count: fallidas }));
    cargar();
  };

  // Al editar, las imágenes se guardan en cuanto se suben: la tarjeta tiene
  // que enterarse aunque luego se cancele el texto.
  const imagenesDe = (id) => (nuevas) =>
    setPasos((ps) => ps.map((x) => (x.id === id ? { ...x, imagenes: nuevas } : x)));

  const alternarActivo = async (paso) => {
    try {
      await api.patch(`/admin/pasos/${paso.id}`, { activo: !paso.activo });
      setAviso('');
      cargar();
    } catch (err) {
      // Sin esto un 403 o un 404 dejaban el boton muerto y sin explicacion.
      setAviso(err.response?.data?.detail || t('temas.error_guardar'));
    }
  };

  const eliminar = async (paso) => {
    setPorEliminar(null);
    try {
      await api.delete(`/admin/pasos/${paso.id}`);
      setAviso('');
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('temas.error_borrar'));
    }
  };

  // El texto del paso: sembrado desde `seed.py` viene como llave de i18n,
  // creado por el admin viene como texto tal cual. `defaultValue` cubre las
  // llaves que aún no estén en los locales: se ve la llave, no una pantalla
  // rota, y así fue como se detectó que aquí faltaba pasar por `t(...)`.
  const textoPaso = (paso) =>
    paso.pregunta_texto || t(paso.pregunta_key, { defaultValue: paso.pregunta_key });

  if (cargando) return <EsqueletoLista filas={4} />;

  const visibles = filtro ? pasos.filter((p) => p.categoria === filtro) : pasos;

  return (
    <div>
      {aviso && <Aviso texto={aviso} />}

      <div className="barra-herramientas">
        <Selector className="form-select" value={filtro} onChange={(e) => setFiltro(e.target.value)}
          style={{ maxWidth: '260px' }}>
          <option value="">{t('temas.todas_categorias')}</option>
          {CATEGORIAS.map((c) => (
            <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>
          ))}
        </Selector>
        <button onClick={() => { setCreando(true); setEditando(null); }} className="btn-acento"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <Plus size={16} />
          {t('temas.nuevo_paso')}
        </button>
      </div>

      {creando && (
        <FormularioPaso
          categoriaInicial={filtro || 'equipo'}
          onGuardar={(d) => guardar(d)}
          onTerminado={terminar}
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
              onTerminado={terminar}
              onImagenes={imagenesDe(paso.id)}
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
                    {textoPaso(paso)}
                  </div>
                  {paso.accion_si_no && (
                    <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                      {paso.accion_si_no}
                    </div>
                  )}
                  <GaleriaImagenes imagenes={paso.imagenes} compacta />
                  {paso.veces_resolvio > 0 && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--status-resuelto-text)', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <TrendingUp size={14} />
                      {t('temas.resolvio_veces', { count: paso.veces_resolvio })}
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
                  <button onClick={() => setPorEliminar(paso)} className="btn-secondary btn-secondary--peligro"
                    style={{ padding: '8px 12px' }} title={t('temas.dar_baja')}>
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </div>
          )
        ))}
      </div>

      {porEliminar && (
        <Confirmacion
          titulo={textoPaso(porEliminar)}
          mensaje={t('temas.confirmar_baja')}
          textoConfirmar={t('temas.dar_baja')}
          tono="peligro"
          onConfirmar={() => eliminar(porEliminar)}
          onCancelar={() => setPorEliminar(null)}
        />
      )}
    </div>
  );
};

/** Cuánto le falta a un campo para que "Guardar" se encienda. */
const AvisoFaltante = ({ children }) => (
  <div style={{ fontSize: '0.8rem', color: 'var(--status-espera-proveedor-text)', marginTop: '6px' }}>
    {children}
  </div>
);

const FormularioPaso = ({ paso, categoriaInicial, onGuardar, onTerminado, onImagenes, onCancelar }) => {
  const { t } = useTranslation();
  const [categoria, setCategoria] = useState(paso?.categoria || categoriaInicial);
  // **Los pasos de fábrica guardan una llave de traducción, no el texto.** Al
  // editarlos el campo salía vacío y "Guardar" bloqueado: para ponerle una
  // foto o marcar "resuelve" había que volver a escribir la pregunta. Se
  // propone la traducción, y si no se toca no se manda —el paso sigue
  // saliendo en el idioma de cada quien en vez de quedarse en éste—.
  const preguntaSembrada = paso && !paso.pregunta_texto
    ? t(paso.pregunta_key, { defaultValue: '' })
    : '';
  const [pregunta, setPregunta] = useState(paso?.pregunta_texto || preguntaSembrada);
  const [accion, setAccion] = useState(paso?.accion_si_no || '');
  const [resuelve, setResuelve] = useState(paso?.resuelve || false);
  const [guardando, setGuardando] = useState(false);
  const imagenes = useRef(null);

  const valido = pregunta.trim().length >= 5;
  // "Guardar" se apaga sin decir por qué: se dice cuánto falta en cuanto hay
  // algo escrito, o si se está editando —que es cuando más desconcierta—.
  const faltaPregunta = Math.max(0, 5 - pregunta.trim().length);

  return (
    <Formulario
      className="apple-card animate-scale-in"
      style={{ padding: '22px', marginBottom: '14px', border: '1px solid var(--accent-primary)' }}
      // Una captura pegada en cualquier campo del formulario se queda como
      // imagen del paso; el texto se pega como siempre.
      onPaste={(e) => imagenes.current?.pegar(e)}
      onSubmit={async (e) => {
        e.preventDefault();
        if (!valido || guardando) return;
        setGuardando(true);
        const sinTocar = preguntaSembrada && pregunta.trim() === preguntaSembrada.trim();
        const guardado = await onGuardar({
          categoria,
          ...(sinTocar ? {} : { pregunta_texto: pregunta.trim() }),
          accion_si_no: accion.trim() || null,
          resuelve
        });
        if (!guardado) { setGuardando(false); return; }
        const fallidas = await imagenes.current?.subirPendientes(guardado.id) || 0;
        onTerminado(fallidas);
      }}
    >
      <div className="form-group">
        <label>{t('ticket.categoria')}</label>
        <Selector className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
          {CATEGORIAS.map((c) => (
            <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>
          ))}
        </Selector>
      </div>

      <div className="form-group">
        <label>{t('temas.pregunta')}</label>
        <textarea className="form-textarea" rows={2} value={pregunta} required
          placeholder={t('temas.pregunta_ejemplo')}
          onChange={(e) => setPregunta(e.target.value)} />
        {faltaPregunta > 0 && (pregunta || paso) && (
          <AvisoFaltante>{t('temas.faltan_pregunta', { count: faltaPregunta })}</AvisoFaltante>
        )}
      </div>

      <div className="form-group">
        <label>{t('temas.accion')}</label>
        <textarea className="form-textarea" rows={2} value={accion}
          placeholder={t('temas.accion_ejemplo')}
          onChange={(e) => setAccion(e.target.value)} />
      </div>

      <EditorImagenes ref={imagenes} tipo="paso" id={paso?.id || null}
        imagenes={paso?.imagenes} onCambio={onImagenes} />

      <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', marginBottom: '18px' }}>
        <input type="checkbox" checked={resuelve} onChange={(e) => setResuelve(e.target.checked)}
          style={{ width: '18px', height: '18px', cursor: 'pointer' }} />
        <span style={{ fontSize: '0.92rem', color: 'var(--text-primary)' }}>
          {t('temas.marca_resuelve')}
        </span>
      </label>

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button type="button" onClick={onCancelar} className="btn-secondary" style={{ padding: '10px 18px' }}>
          <X size={15} /> {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-acento" disabled={!valido || guardando} style={{ padding: '10px 18px' }}>
          <Check size={15} /> {guardando ? t('temas.guardando') : t('temas.guardar')}
        </button>
      </div>
    </Formulario>
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
  const [porEliminar, setPorEliminar] = useState(null);

  const cargar = async () => {
    setCargando(true);
    try {
      setEntradas(lista((await api.get('/admin/kb')).data, 'las entradas de conocimiento'));
    } catch {
      setAviso(t('temas.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  // Igual que en los pasos: guardar devuelve lo guardado y el formulario
  // decide cuándo cerrar, después de subir sus imágenes.
  const guardar = async (datos, id) => {
    try {
      const res = id
        ? await api.patch(`/admin/kb/${id}`, datos)
        : await api.post('/admin/kb', datos);
      setAviso('');
      return res.data;
    } catch (err) {
      setAviso(err.response?.data?.detail || t('temas.error_guardar'));
      return null;
    }
  };

  const terminar = (fallidas = 0) => {
    setCreando(false);
    setEditando(null);
    if (fallidas) setAviso(t('imagenes.algunas_no_subieron', { count: fallidas }));
    cargar();
  };

  const imagenesDe = (id) => (nuevas) =>
    setEntradas((es) => es.map((x) => (x.id === id ? { ...x, imagenes: nuevas } : x)));

  const eliminar = async (entrada) => {
    setPorEliminar(null);
    try {
      await api.delete(`/admin/kb/${entrada.id}`);
      setAviso('');
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('temas.error_borrar'));
    }
  };

  if (cargando) return <EsqueletoLista filas={3} />;

  return (
    <div>
      {aviso && <Aviso texto={aviso} />}

      <button onClick={() => { setCreando(true); setEditando(null); }} className="btn-acento"
        style={{ padding: '10px 18px', fontSize: '0.9rem', marginBottom: '20px' }}>
        <Plus size={16} /> {t('temas.nueva_entrada')}
      </button>

      {creando && <FormularioKB onGuardar={(d) => guardar(d)} onTerminado={terminar}
        onCancelar={() => setCreando(false)} />}

      {entradas.length === 0 && !creando && <Vacio texto={t('temas.sin_kb')} />}

      <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {entradas.map((e) => (
          editando === e.id ? (
            <FormularioKB key={e.id} entrada={e} onGuardar={(d) => guardar(d, e.id)}
              onTerminado={terminar} onImagenes={imagenesDe(e.id)} onCancelar={() => setEditando(null)} />
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
                  <GaleriaImagenes imagenes={[...(e.imagenes || []), ...(e.imagenes_ticket || [])]} compacta />
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '10px' }}>
                    {t('temas.mostrada_veces', { count: e.veces_sugerida })}
                    {e.tasa_utilidad !== null && ` · ${t('temas.util_pct', { pct: e.tasa_utilidad })}`}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                  <button onClick={() => { setEditando(e.id); setCreando(false); }} className="btn-secondary" style={{ padding: '8px 12px' }}>
                    <Pencil size={15} />
                  </button>
                  <button onClick={() => setPorEliminar(e)} className="btn-secondary btn-secondary--peligro" style={{ padding: '8px 12px' }}>
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </div>
          )
        ))}
      </div>

      {porEliminar && (
        <Confirmacion
          titulo={porEliminar.titulo}
          mensaje={t('temas.confirmar_borrar_kb')}
          textoConfirmar={t('comun.eliminar')}
          tono="peligro"
          onConfirmar={() => eliminar(porEliminar)}
          onCancelar={() => setPorEliminar(null)}
        />
      )}
    </div>
  );
};

const FormularioKB = ({ entrada, onGuardar, onTerminado, onImagenes, onCancelar }) => {
  const { t } = useTranslation();
  const [titulo, setTitulo] = useState(entrada?.titulo || '');
  const [contenido, setContenido] = useState(entrada?.contenido || '');
  const [categoria, setCategoria] = useState(entrada?.categoria || 'equipo');
  const [guardando, setGuardando] = useState(false);
  const imagenes = useRef(null);

  const valido = titulo.trim().length >= 5 && contenido.trim().length >= 20;
  const faltaTitulo = Math.max(0, 5 - titulo.trim().length);
  const faltaContenido = Math.max(0, 20 - contenido.trim().length);

  return (
    <Formulario className="apple-card animate-scale-in"
      style={{ padding: '22px', marginBottom: '14px', border: '1px solid var(--accent-primary)' }}
      onPaste={(e) => imagenes.current?.pegar(e)}
      onSubmit={async (e) => {
        e.preventDefault();
        if (!valido || guardando) return;
        setGuardando(true);
        const guardada = await onGuardar({ titulo: titulo.trim(), contenido: contenido.trim(), categoria });
        if (!guardada) { setGuardando(false); return; }
        const fallidas = await imagenes.current?.subirPendientes(guardada.id) || 0;
        onTerminado(fallidas);
      }}>
      <div className="form-group">
        <label>{t('ticket.categoria')}</label>
        <Selector className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
          {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>)}
        </Selector>
      </div>
      <div className="form-group">
        <label>{t('temas.titulo_entrada')}</label>
        <input className="form-input" value={titulo} required style={{ width: '100%' }}
          placeholder={t('temas.titulo_ejemplo')} onChange={(e) => setTitulo(e.target.value)} />
        {faltaTitulo > 0 && (titulo || entrada) && (
          <AvisoFaltante>{t('temas.faltan_titulo', { count: faltaTitulo })}</AvisoFaltante>
        )}
      </div>
      <div className="form-group">
        <label>{t('temas.solucion_entrada')}</label>
        <textarea className="form-textarea" rows={5} value={contenido} required
          placeholder={t('temas.solucion_ejemplo')} onChange={(e) => setContenido(e.target.value)} />
        {faltaContenido > 0 && (contenido || entrada) && (
          <AvisoFaltante>{t('temas.faltan_solucion', { count: faltaContenido })}</AvisoFaltante>
        )}
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
          {t('temas.nota_vector')}
        </div>
      </div>
      <EditorImagenes ref={imagenes} tipo="kb" id={entrada?.id || null}
        imagenes={entrada?.imagenes} onCambio={onImagenes} />
      {/* Las de la solución del ticket de origen vienen enlazadas: se ven
          aquí y en las sugerencias, pero se cambian desde el ticket. */}
      {entrada?.imagenes_ticket?.length > 0 && (
        <div className="editor-imagenes" style={{ marginTop: '-6px' }}>
          <div className="editor-imagenes-rotulo">{t('imagenes.del_ticket')}</div>
          <GaleriaImagenes imagenes={entrada.imagenes_ticket} compacta />
        </div>
      )}
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button type="button" onClick={onCancelar} className="btn-secondary" style={{ padding: '10px 18px' }}>
          <X size={15} /> {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-acento" disabled={!valido || guardando} style={{ padding: '10px 18px' }}>
          <Check size={15} /> {guardando ? t('temas.guardando') : t('temas.guardar')}
        </button>
      </div>
    </Formulario>
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
  const [aviso, setAviso] = useState('');

  const cargar = async () => {
    setCargando(true);
    try {
      setTemas(lista((await api.get('/admin/temas-sugeridos')).data, 'los temas sugeridos'));
    } catch {
      setTemas([]);
      setAviso(t('temas.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  const descartar = async (tema) => {
    try {
      await api.post(`/admin/temas-sugeridos/${tema.id}/descartar`);
      setAviso('');
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('temas.error_guardar'));
    }
  };

  if (cargando) return <EsqueletoLista filas={2} />;

  if (temas.length === 0) {
    return (
      <>
        {aviso && <Aviso texto={aviso} />}
        <Vacio
          texto={t('temas.sin_detectados')}
          detalle={t('temas.sin_detectados_detalle')}
        />
      </>
    );
  }

  return (
    <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {aviso && <Aviso texto={aviso} />}
      {temas.map((tema) => (
        <div key={tema.id} className="apple-card" style={{
          padding: '22px',
          borderLeft: tema.estado === 'listo' ? '3px solid var(--accent-primary)' : '3px solid transparent'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px', flexWrap: 'wrap' }}>
            <Etiqueta
              texto={t('temas.veces_reportado', { count: tema.ocurrencias })}
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
              className="btn-acento" style={{ padding: '9px 16px', fontSize: '0.88rem' }}>
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
  const [error, setError] = useState('');

  const enviar = async (e) => {
    e.preventDefault();
    setGuardando(true);
    setError('');
    try {
      await api.post(`/admin/temas-sugeridos/${tema.id}/promover`, {
        categoria,
        pasos: pregunta.trim().length >= 5
          ? [{ categoria, pregunta_texto: pregunta.trim(), accion_si_no: accion.trim() || null, resuelve: true }]
          : []
      });
      onListo();
    } catch (err) {
      // Habia try/finally sin catch: si fallaba, el formulario se quedaba
      // igual y nadie sabia por que.
      setError(err.response?.data?.detail || t('temas.error_guardar'));
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Formulario onSubmit={enviar} className="animate-scale-in" style={{
      marginTop: '18px', paddingTop: '18px', borderTop: '1px solid var(--border-color)'
    }}>
      <div className="form-group">
        <label>{t('temas.en_que_categoria')}</label>
        <Selector className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
          {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>)}
        </Selector>
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
      {error && <Aviso texto={error} />}
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        <button type="button" onClick={onCancelar} className="btn-secondary" style={{ padding: '9px 16px' }}>
          {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-acento" disabled={guardando} style={{ padding: '9px 16px' }}>
          <Check size={15} /> {guardando ? t('temas.guardando') : t('temas.crear_tema')}
        </button>
      </div>
    </Formulario>
  );
};

/* ================================================================
   Piezas compartidas
   ================================================================ */
const TONOS = {
  azul: ['var(--accent-primary)', 'var(--acento-bg)'],
  verde: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  ambar: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  gris: ['var(--text-secondary)', 'var(--bg-tertiary)']
};

/* La forma la pone `.chip-dato`, compartida con el tablero y con resguardos;
   aquí solo queda el color, que es lo único propio de esta pantalla. Antes
   cada sitio se dibujaba su pastilla y la fila salía con tres redondeos
   distintos. */
const Etiqueta = ({ texto, tono = 'azul' }) => {
  const [color, fondo] = TONOS[tono] || TONOS.azul;
  return <span className="chip-dato" style={{ color, background: fondo }}>{texto}</span>;
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

/* Se conserva el nombre local para no tocar los tres sitios que lo usan;
   lo que cambia es que ya no dibuja su propia caja. */
const Vacio = ({ texto, detalle }) => <EstadoVacio texto={texto} detalle={detalle} />;

export default PaginaPasos;
