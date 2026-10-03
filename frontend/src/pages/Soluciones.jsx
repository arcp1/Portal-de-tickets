import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import {
  BookOpenCheck, Sparkles, Check, Archive, Pencil, X, Layers,
  AlertTriangle, Ban, Plus
} from 'lucide-react';
import Selector from '../components/Selector';
import lista from '../lib/lista';

/**
 * Soluciones generales: un procedimiento por problema recurrente.
 *
 * El flujo es de dos manos a propósito. La máquina propone el borrador; **la
 * publicación la firma una persona**. Mientras es borrador no le contesta a
 * nadie: no tiene embedding, así que no aparece en ninguna búsqueda.
 *
 * Esa separación no es burocracia. Un procedimiento equivocado manda a alguien a
 * desarmar un equipo sano.
 */
const ESTADOS = {
  borrador: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  publicada: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  archivada: ['var(--text-secondary)', 'var(--bg-tertiary)']
};

// Las de los tickets: la categoría de una solución es la de los tickets a los
// que contesta. Vacía = sirve para cualquiera.
const CATEGORIAS = ['impresora', 'red', 'equipo', 'software', 'accesos', 'otro'];

// Lo que exige el backend al crear (`CrearSolucion`). Al editar no lo exige,
// pero un título vacío chocaba con la columna NOT NULL y salía un 500.
const MINIMO_TITULO = 5;
const MINIMO_CONTENIDO = 20;

const Soluciones = () => {
  const { t } = useTranslation();
  const [soluciones, setSoluciones] = useState([]);
  const [candidatos, setCandidatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [trabajando, setTrabajando] = useState(false);
  const [aviso, setAviso] = useState('');
  const [editando, setEditando] = useState(null);
  const [creando, setCreando] = useState(false);

  const cargar = async () => {
    try {
      // `publicadas` y no `lista`: ese nombre lo ocupa ahora el ayudante que
      // obliga a que la respuesta sea una lista.
      const [publicadas, grupos] = await Promise.all([
        api.get('/admin/soluciones'),
        api.get('/admin/soluciones/candidatos')
      ]);
      setSoluciones(lista(publicadas.data, 'las soluciones'));
      // `candidatos` **no** pasa por `lista`: ese endpoint devuelve un objeto
      // `{ total, grupos }`, no una lista. Envolverlo lo vaciaba —se llegó a
      // hacer— y la tarjeta salía contando `undefined` problemas. Aquí no
      // hace falta guarda: lo que se lee son `candidatos.total`, que como
      // mucho queda en `undefined`, y `candidatos.grupos?.length`, que ya
      // trae la suya. Nada de esto revienta el render.
      setCandidatos(grupos.data);
    } catch {
      setAviso(t('soluciones.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  const proponer = async () => {
    setTrabajando(true);
    setAviso('');
    try {
      const res = await api.post('/admin/soluciones/proponer');
      setAviso(res.data.redactadas
        ? t('soluciones.redactadas', { count: res.data.redactadas })
        : (res.data.detalle || t('soluciones.nada_que_redactar')));
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('soluciones.error_proponer'));
    } finally {
      setTrabajando(false);
    }
  };

  const accion = async (ruta) => {
    try {
      await api.post(ruta);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('soluciones.error_accion'));
    }
  };

  const guardar = async (solucion, cambios) => {
    try {
      await api.patch(`/admin/soluciones/${solucion.id}`, cambios);
      setEditando(null);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('soluciones.error_accion'));
    }
  };

  /* **Escribirla a mano, sin esperar a que el problema se repita.** El backend
     lo permitía desde el principio (`POST /admin/soluciones`), pero la pantalla
     no tenía por dónde: el único camino era que la máquina propusiera, y eso
     exige que la falla ya haya pasado varias veces. Lo que TI ya sabe no tiene
     por qué esperar. Nace como borrador, igual que las propuestas: la firma
     sigue siendo un paso aparte. */
  const crear = async (datos) => {
    try {
      await api.post('/admin/soluciones', {
        ...datos,
        categoria: datos.categoria || null,
        descartado: datos.descartado || null
      });
      setCreando(false);
      setAviso('');
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('soluciones.error_accion'));
    }
  };

  if (cargando) return <div className="page-container"><EsqueletoLista /></div>;

  const borradores = soluciones.filter((s) => s.estado === 'borrador');

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {t('soluciones.title')}
          </h1>
          {/* Sin ancho propio: el subtítulo de todas las pantallas es un
              rótulo en versalitas monoespaciadas, y a 70ch este caía en un
              bloque de cuatro renglones estrechos debajo de un título que
              ocupaba el ancho entero. Un rótulo de panel es de un renglón; lo
              que explica el porqué de la pantalla está en el texto de la
              tarjeta de candidatos, que es donde se necesita leerlo. */}
          <p>{t('soluciones.subtitle')}</p>
        </div>

        {!creando && (
          <button onClick={() => { setCreando(true); setEditando(null); }} className="btn-primary">
            <Plus size={18} />
            {t('soluciones.nueva')}
          </button>
        )}
      </div>

      {creando && (
        <div style={{ marginBottom: '22px' }}>
          <Editor
            solucion={{ titulo: '', contenido: '', descartado: '', categoria: '' }}
            esNueva
            onGuardar={(_, datos) => crear(datos)}
            onCancelar={() => setCreando(false)}
            t={t}
          />
        </div>
      )}

      {aviso && (
        <div className="animate-scale-in" style={{
          display: 'flex', alignItems: 'flex-start', gap: '10px',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          padding: '13px 16px', borderRadius: 'var(--radius-md)',
          marginBottom: '18px', fontSize: '0.9rem', lineHeight: 1.5
        }}>
          <AlertTriangle size={17} style={{ flexShrink: 0, marginTop: '1px' }} /> {aviso}
        </div>
      )}

      {/* Qué problemas ya se repitieron lo suficiente. */}
      {candidatos && (
        <div className="apple-card" style={{ padding: '20px', marginBottom: '22px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
            <Layers size={18} color="var(--accent-primary)" />
            <strong style={{ color: 'var(--text-primary)' }}>
              {t('soluciones.candidatos', { count: candidatos.total })}
            </strong>
          </div>
          <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.55, margin: '0 0 14px' }}>
            {candidatos.total > 0 ? t('soluciones.candidatos_detalle') : t('soluciones.sin_candidatos')}
          </p>

          {candidatos.grupos?.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '7px', marginBottom: '14px' }}>
              {candidatos.grupos.slice(0, 8).map((g, i) => (
                <span key={i} style={{
                  fontSize: '0.8rem', padding: '4px 11px', borderRadius: 'var(--radius-full)',
                  background: 'var(--bg-tertiary)', color: 'var(--text-secondary)'
                }}>
                  {g.titulo.slice(0, 46)}{g.titulo.length > 46 ? '…' : ''}
                  {' · '}<strong>{g.ocurrencias}</strong>
                </span>
              ))}
            </div>
          )}

          <button onClick={proponer} disabled={trabajando || !candidatos.total}
            className="btn-acento" style={{ padding: '11px 20px', fontSize: '0.9rem' }}>
            <Sparkles size={16} />
            {trabajando ? t('soluciones.redactando') : t('soluciones.proponer')}
          </button>
        </div>
      )}

      {borradores.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: '10px',
          background: 'var(--bg-tertiary)', padding: '13px 16px',
          borderRadius: 'var(--radius-md)', marginBottom: '18px',
          fontSize: '0.88rem', lineHeight: 1.55, color: 'var(--text-secondary)'
        }}>
          <Ban size={17} style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>{t('soluciones.aviso_borradores', { count: borradores.length })}</span>
        </div>
      )}

      {soluciones.length === 0 ? (
        <div className="apple-card" style={{ padding: '38px', textAlign: 'center' }}>
          <BookOpenCheck size={34} color="var(--text-muted)" style={{ marginBottom: '12px' }} />
          <div style={{ color: 'var(--text-secondary)' }}>{t('soluciones.vacio')}</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {soluciones.map((s) => (
            editando === s.id
              ? <Editor key={s.id} solucion={s} onGuardar={guardar}
                  onCancelar={() => setEditando(null)} t={t} />
              : <Tarjeta key={s.id} solucion={s} t={t}
                  onEditar={() => setEditando(s.id)}
                  onPublicar={() => accion(`/admin/soluciones/${s.id}/publicar`)}
                  onArchivar={() => accion(`/admin/soluciones/${s.id}/archivar`)} />
          ))}
        </div>
      )}
    </div>
  );
};

const Tarjeta = ({ solucion, onEditar, onPublicar, onArchivar, t }) => {
  const [color, fondo] = ESTADOS[solucion.estado] || ESTADOS.archivada;

  return (
    <div className="apple-card" style={{ padding: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '10px' }}>
        <strong style={{ color: 'var(--text-primary)', fontSize: '1rem', flex: 1, minWidth: '200px' }}>
          {solucion.titulo}
        </strong>
        <span className="chip-dato" style={{ color, background: fondo }}>
          {t(`soluciones.estado_${solucion.estado}`)}
        </span>
      </div>

      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '12px' }}>
        {/* Una escrita a mano no sale de ningún ticket: "de 0 tickets" leía
            como si le faltara algo. */}
        {solucion.tickets_origen > 0
          ? t('soluciones.de_tickets', { count: solucion.tickets_origen })
          : t('soluciones.sin_tickets_origen')}
        {solucion.redactada_por && ` · ${t(`soluciones.por_${solucion.redactada_por}`)}`}
        {' · '}
        {solucion.categoria
          ? t(`new_ticket.category_${solucion.categoria}`, { defaultValue: solucion.categoria })
          : t('soluciones.categoria_general')}
      </div>

      <div style={{
        fontSize: '0.9rem', lineHeight: 1.6, color: 'var(--text-primary)',
        whiteSpace: 'pre-wrap', background: 'var(--bg-tertiary)',
        padding: '14px 16px', borderRadius: 'var(--radius-md)'
      }}>
        {solucion.contenido}
      </div>

      {solucion.descartado && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: '8px', marginTop: '10px',
          padding: '10px 13px', borderRadius: 'var(--radius-md)',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          fontSize: '0.85rem', lineHeight: 1.5, whiteSpace: 'pre-wrap'
        }}>
          <Ban size={15} style={{ flexShrink: 0, marginTop: '2px' }} />
          <span><strong>{t('soluciones.descartado')}</strong> {solucion.descartado}</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: '9px', marginTop: '14px', flexWrap: 'wrap' }}>
        <button onClick={onEditar} className="btn-secondary"
          style={{ padding: '8px 14px', fontSize: '0.84rem' }}>
          <Pencil size={14} /> {t('soluciones.revisar')}
        </button>
        {solucion.estado !== 'publicada' && (
          <button onClick={onPublicar} className="btn-acento"
            style={{ padding: '8px 14px', fontSize: '0.84rem' }}>
            <Check size={14} /> {t('soluciones.publicar')}
          </button>
        )}
        {solucion.estado === 'publicada' && (
          <button onClick={onArchivar} className="btn-secondary"
            style={{ padding: '8px 14px', fontSize: '0.84rem' }}>
            <Archive size={14} /> {t('soluciones.archivar')}
          </button>
        )}
      </div>
    </div>
  );
};

const Editor = ({ solucion, esNueva = false, onGuardar, onCancelar, t }) => {
  const [titulo, setTitulo] = useState(solucion.titulo);
  const [contenido, setContenido] = useState(solucion.contenido);
  const [descartado, setDescartado] = useState(solucion.descartado || '');
  const [categoria, setCategoria] = useState(solucion.categoria || '');

  const completa = titulo.trim().length >= MINIMO_TITULO
    && contenido.trim().length >= MINIMO_CONTENIDO;

  return (
    <div className="apple-card animate-scale-in" style={{
      padding: '20px', border: '1px solid var(--accent-primary)'
    }}>
      {esNueva && (
        <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.55, margin: '0 0 16px' }}>
          {t('soluciones.nueva_ayuda')}
        </p>
      )}
      <div className="form-group">
        <label>{t('soluciones.titulo_campo')}</label>
        <input className="form-input" style={{ width: '100%' }} autoFocus={esNueva}
          maxLength={200}
          value={titulo} onChange={(e) => setTitulo(e.target.value)} />
      </div>
      <div className="form-group">
        <label>{t('soluciones.categoria_campo')}</label>
        <Selector className="form-select" value={categoria}
          onChange={(e) => setCategoria(e.target.value)}>
          <option value="">{t('soluciones.categoria_general')}</option>
          {CATEGORIAS.map((c) => (
            <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>
          ))}
        </Selector>
      </div>
      <div className="form-group">
        <label>{t('soluciones.procedimiento')}</label>
        <textarea className="form-textarea" rows={12} style={{ width: '100%', fontSize: '0.92rem' }}
          value={contenido} onChange={(e) => setContenido(e.target.value)} />
      </div>
      <div className="form-group">
        <label>{t('soluciones.descartado_campo')}</label>
        <textarea className="form-textarea" rows={3} style={{ width: '100%', fontSize: '0.92rem' }}
          value={descartado} onChange={(e) => setDescartado(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        <button onClick={onCancelar} className="btn-secondary" style={{ padding: '9px 16px' }}>
          <X size={15} /> {t('temas.cancelar')}
        </button>
        {/* Decía "Guardando" —salía de recortar los puntos a
            `temas.guardando`— antes de haber pulsado nada. */}
        <button onClick={() => onGuardar(solucion, { titulo, contenido, descartado, categoria })}
          disabled={!completa}
          title={completa ? undefined : t('soluciones.falta_texto', {
            titulo: MINIMO_TITULO, contenido: MINIMO_CONTENIDO })}
          className="btn-acento" style={{ padding: '9px 16px' }}>
          <Check size={15} /> {t('temas.guardar')}
        </button>
      </div>
    </div>
  );
};

export default Soluciones;
