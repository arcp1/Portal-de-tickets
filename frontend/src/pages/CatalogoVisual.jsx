import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api, { ESPERA_SUBIDA } from '../api/client';
import Confirmacion from '../components/Confirmacion';
import { EsqueletoLista } from '../components/Cargando';
import Selector from '../components/Selector';
import Formulario from '../components/Formulario';
import EstadoVacio from '../components/EstadoVacio';
import Aviso from '../components/Aviso';
import ImagenApi from '../components/ImagenApi';
import {
  Plus, Search, Pencil, Trash2, Check, X, Camera, MousePointerClick,
  Upload, Eye, Archive, FileWarning, ArrowUp, ArrowDown, Wand2, RefreshCw,
  AlertTriangle
} from 'lucide-react';
import lista from '../lib/lista';

const CATEGORIAS = ['impresora', 'red', 'equipo', 'software', 'accesos', 'otro'];
const ESTADOS = ['borrador', 'publicada', 'archivada'];

const COLOR_ESTADO = {
  borrador: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  publicada: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  archivada: ['var(--text-secondary)', 'var(--bg-tertiary)']
};

/**
 * Catálogo visual: documentar un problema con la foto de cómo se ve.
 *
 * **Lo que se documenta aquí no cabe en un texto.** Una copia borrosa, una con
 * sombra doble y una con una raya fina se escriben las tres igual —"sale
 * mal"— y se arreglan de tres maneras distintas. Con la foto delante, quien
 * tiene el problema señala la suya en dos segundos.
 *
 * Cada ficha tiene dos mitades y las dos importan:
 *
 *   - **Cómo se ve el problema.** Es la foto con la que el portal pregunta
 *     "¿es esto lo que le pasa?". Sin al menos una, la ficha no se puede
 *     publicar: no tendría cómo preguntar.
 *   - **Dónde hay que picar.** Las capturas señaladas de los pasos. Hay
 *     problemas que se arreglan con dos clics y contarlos por escrito cuesta
 *     un párrafo que nadie sigue.
 *
 * Y el probador de abajo no es un juguete: el disparador se puede equivocar de
 * dos maneras y ninguna se reporta sola —enseñar fotos a quien preguntó por la
 * red, y no enseñárselas a quien sí tenía el defecto—. Aquí se teclea la frase
 * y se ve la decisión con su motivo.
 */
const CatalogoVisual = () => {
  const { t } = useTranslation();

  const [fichas, setFichas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [busqueda, setBusqueda] = useState('');
  const [estado, setEstado] = useState('');
  const [categoria, setCategoria] = useState('');
  const [creando, setCreando] = useState(false);
  const [editando, setEditando] = useState(null);
  const [aviso, setAviso] = useState('');
  const [porBorrar, setPorBorrar] = useState(null);

  const cargar = async () => {
    try {
      const params = new URLSearchParams();
      if (estado) params.set('estado', estado);
      if (categoria) params.set('categoria', categoria);
      if (busqueda) params.set('buscar', busqueda);
      const res = await api.get(`/admin/visual?${params}`);
      setFichas(lista(res.data, 'las fichas visuales'));
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('visual.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    const temporizador = setTimeout(cargar, busqueda ? 400 : 0);
    return () => clearTimeout(temporizador);
  }, [busqueda, estado, categoria]);

  const guardar = async (datos, id) => {
    try {
      if (id) await api.patch(`/admin/visual/${id}`, datos);
      else await api.post('/admin/visual', datos);
      setCreando(false);
      setEditando(null);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('visual.error_guardar'));
    }
  };

  const cambiarEstado = async (ficha, nuevo) => {
    try {
      await api.post(`/admin/visual/${ficha.id}/estado/${nuevo}`);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('visual.error_guardar'));
    }
  };

  const borrar = async (ficha) => {
    setPorBorrar(null);
    try {
      await api.delete(`/admin/visual/${ficha.id}`);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('visual.error_borrar'));
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('visual.title')}</h1>
          <p>{t('visual.subtitle')}</p>
        </div>
      </div>

      <Aviso texto={aviso} />

      {/* **Quién ve esto.** A diferencia de la documentación de TI, que no sale
          del área, una ficha publicada se le enseña a cualquiera que describa
          ese defecto. Una captura de pantalla puede llevar el nombre de una
          persona, un correo o un folio de nómina sin que quien la sube se fije,
          y una vez publicada la ve toda la planta. Decirlo aquí cuesta un
          renglón; no decirlo se paga una vez y mal. */}
      <div style={{
        display: 'flex', alignItems: 'flex-start', gap: '10px',
        padding: '12px 16px', marginBottom: '18px',
        borderRadius: 'var(--radius-md)', fontSize: '0.86rem', lineHeight: 1.5,
        background: 'var(--bg-tertiary)', color: 'var(--text-secondary)'
      }}>
        <Eye size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
        <span>{t('visual.quien_lo_ve')}</span>
      </div>

      <Probador onError={setAviso} />

      <div className="barra-herramientas">
        <button onClick={() => { setCreando(true); setEditando(null); }} className="btn-acento"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <Plus size={16} /> {t('visual.nueva')}
        </button>

        <div style={{ position: 'relative', flex: 1, minWidth: '220px' }}>
          <Search size={16} style={{
            position: 'absolute', left: '12px', top: '50%',
            transform: 'translateY(-50%)', color: 'var(--text-muted)'
          }} />
          <input className="form-input" value={busqueda} onChange={(e) => setBusqueda(e.target.value)}
            placeholder={t('visual.buscar')} style={{ width: '100%', paddingLeft: '38px' }} />
        </div>

        <Selector className="form-select" value={estado} onChange={(e) => setEstado(e.target.value)}
          style={{ maxWidth: '180px' }}>
          <option value="">{t('visual.todos_estados')}</option>
          {ESTADOS.map((e) => <option key={e} value={e}>{t(`visual.estado_${e}`)}</option>)}
        </Selector>

        <Selector className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}
          style={{ maxWidth: '190px' }}>
          <option value="">{t('visual.todas')}</option>
          {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>)}
        </Selector>
      </div>

      {creando && (
        <EditorFicha onGuardar={(d) => guardar(d)} onCancelar={() => setCreando(false)} />
      )}

      {cargando ? (
        <EsqueletoLista filas={3} />
      ) : fichas.length === 0 ? (
        <EstadoVacio texto={busqueda ? t('visual.sin_resultados') : t('visual.vacio')} />
      ) : (
        <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {fichas.map((f) => (
            editando === f.id ? (
              <EditorFicha key={f.id} ficha={f}
                onGuardar={(datos) => guardar(datos, f.id)}
                onCancelar={() => setEditando(null)} />
            ) : (
              <TarjetaFicha
                key={f.id}
                ficha={f}
                onEditar={() => { setEditando(f.id); setCreando(false); }}
                onBorrar={() => setPorBorrar(f)}
                onEstado={(nuevo) => cambiarEstado(f, nuevo)}
                onCambio={cargar}
                onError={setAviso}
              />
            )
          ))}
        </div>
      )}

      {porBorrar && (
        <Confirmacion
          titulo={porBorrar.titulo}
          mensaje={t('visual.confirmar_borrar', { titulo: porBorrar.titulo })}
          textoConfirmar={t('comun.eliminar')}
          tono="peligro"
          onConfirmar={() => borrar(porBorrar)}
          onCancelar={() => setPorBorrar(null)}
        />
      )}
    </div>
  );
};

/* ================================================================ */
/**
 * "¿Qué haría el portal con esta frase?"
 *
 * Lo que enseña no es si hay o no una ficha parecida: es **el motivo**. Una
 * consulta que no activa por `ausencia_de_funcion` está bien resuelta; una que
 * no activa por `sin_parecido` teniendo la ficha escrita significa que el
 * síntoma está redactado con otras palabras que las que usa la gente, y eso se
 * arregla escribiendo la frase real en el campo de frases.
 *
 * No cuenta como "mostrada": probar veinte veces no debe falsear la métrica
 * que dice si una ficha acierta.
 */
const Probador = ({ onError }) => {
  const { t } = useTranslation();
  const [texto, setTexto] = useState('');
  const [resultado, setResultado] = useState(null);
  const [probando, setProbando] = useState(false);

  const probar = async (e) => {
    e.preventDefault();
    if (!texto.trim()) return;
    setProbando(true);
    try {
      const res = await api.post('/admin/visual/probar', { texto: texto.trim() });
      setResultado(res.data);
    } catch (err) {
      onError(err.response?.data?.detail || t('visual.error_probar'));
    } finally {
      setProbando(false);
    }
  };

  return (
    <div className="apple-card" style={{ padding: '20px 22px', marginBottom: '18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
        <Wand2 size={18} color="var(--accent-primary)" />
        <strong style={{ color: 'var(--text-primary)' }}>{t('visual.probador')}</strong>
      </div>
      <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.55, margin: '0 0 14px' }}>
        {t('visual.probador_detalle')}
      </p>

      <form onSubmit={probar} style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <input className="form-input" value={texto} onChange={(e) => setTexto(e.target.value)}
          placeholder={t('visual.probador_ejemplo')} maxLength={2000}
          style={{ flex: 1, minWidth: '220px' }} />
        <button type="submit" className="btn-primary" disabled={probando || !texto.trim()}
          style={{ padding: '10px 18px' }}>
          {t('visual.probar')}
        </button>
      </form>

      {resultado && (
        <div className="animate-scale-in" style={{ marginTop: '14px' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '8px',
            padding: '6px 12px', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem',
            background: resultado.activado ? 'var(--status-resuelto-bg)' : 'var(--bg-tertiary)',
            color: resultado.activado ? 'var(--status-resuelto-text)' : 'var(--text-secondary)'
          }}>
            {resultado.activado ? t('visual.se_activa') : t('visual.no_se_activa')}
            <span style={{ opacity: 0.8, fontFamily: 'var(--font-codigo)' }}>
              {t(`visual.motivo_${resultado.motivo}`)}
            </span>
          </div>

          {resultado.candidatas?.length > 0 && (
            <ul style={{ margin: '12px 0 0', paddingLeft: '20px', fontSize: '0.87rem', color: 'var(--text-secondary)' }}>
              {resultado.candidatas.map((c) => (
                <li key={c.ficha_id} style={{ marginBottom: '4px' }}>
                  {c.titulo}
                  {' '}
                  <span style={{ fontFamily: 'var(--font-codigo)', opacity: 0.75 }}>
                    {c.similitud === null
                      ? t('visual.por_frase')
                      : `${Math.round(c.similitud * 100)}%`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};

/* ================================================================ */
const TarjetaFicha = ({ ficha, onEditar, onBorrar, onEstado, onCambio, onError }) => {
  const { t } = useTranslation();
  const [color, fondo] = COLOR_ESTADO[ficha.estado] || COLOR_ESTADO.borrador;

  const sintomas = ficha.imagenes.filter((i) => i.rol === 'sintoma');
  const pasos = ficha.imagenes.filter((i) => i.rol === 'solucion');

  const reindexar = async () => {
    try {
      await api.post(`/admin/visual/${ficha.id}/reindexar`);
      onCambio();
    } catch (err) {
      onError(err.response?.data?.detail || t('visual.error_guardar'));
    }
  };

  return (
    <div className="apple-card" style={{ padding: '20px 22px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: '200px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <strong style={{ color: 'var(--text-primary)', fontSize: '1rem' }}>{ficha.titulo}</strong>
            <span style={{
              padding: '3px 10px', borderRadius: '999px', fontSize: '0.75rem',
              fontWeight: '600', background: fondo, color
            }}>
              {t(`visual.estado_${ficha.estado}`)}
            </span>
            {ficha.categoria && (
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {t(`new_ticket.category_${ficha.categoria}`)}
              </span>
            )}
            {/* De dónde salió, cuando salió de un ticket. Quien lea esta ficha
                dentro de un año puede abrir el caso real y comprobar. */}
            {ficha.ticket_origen_id && (
              <Link
                to={`/tickets/${ficha.ticket_origen_id}`}
                style={{ fontSize: '0.8rem', color: 'var(--accent-primary)' }}
              >
                {t('visual.desde_ticket')}
              </Link>
            )}
          </div>
          <p style={{ margin: '8px 0 0', fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            {ficha.sintoma}
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {ficha.estado !== 'publicada' && (
            <button className="btn-secondary btn-secondary--exito" onClick={() => onEstado('publicada')}
              style={{ padding: '8px 12px', fontSize: '0.83rem' }}>
              <Eye size={14} /> {t('visual.publicar')}
            </button>
          )}
          {ficha.estado === 'publicada' && (
            <button className="btn-secondary" onClick={() => onEstado('archivada')}
              style={{ padding: '8px 12px', fontSize: '0.83rem' }}>
              <Archive size={14} /> {t('visual.archivar')}
            </button>
          )}
          <button className="btn-secondary" onClick={onEditar} style={{ padding: '8px 12px' }}>
            <Pencil size={14} />
          </button>
          <button className="btn-secondary btn-secondary--peligro" onClick={onBorrar} style={{ padding: '8px 12px' }}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Publicada y sin vector es un estado real: si Ollama estaba caído al
          guardar, la ficha sólo se encuentra por sus frases literales. Se dice
          aquí porque si no, el síntoma es "la búsqueda a veces no la halla" y
          no hay nada que mirar. */}
      {ficha.estado === 'publicada' && !ficha.indexada && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '10px', marginTop: '14px',
          padding: '10px 14px', borderRadius: 'var(--radius-md)', fontSize: '0.85rem',
          background: 'var(--status-espera-proveedor-bg)', color: 'var(--status-espera-proveedor-text)'
        }}>
          <FileWarning size={16} style={{ flexShrink: 0 }} />
          <span style={{ flex: 1 }}>{t('visual.sin_vector')}</span>
          <button className="btn-secondary" onClick={reindexar} style={{ padding: '6px 10px', fontSize: '0.8rem' }}>
            <RefreshCw size={13} /> {t('visual.reindexar')}
          </button>
        </div>
      )}

      <Galeria ficha={ficha} rol="sintoma" imagenes={sintomas} onCambio={onCambio} onError={onError} />
      <Galeria ficha={ficha} rol="solucion" imagenes={pasos} onCambio={onCambio} onError={onError} />

      <details style={{ marginTop: '16px' }}>
        <summary style={{ cursor: 'pointer', fontSize: '0.86rem', color: 'var(--text-secondary)' }}>
          {t('visual.ver_solucion')}
        </summary>
        <p style={{ margin: '10px 0 0', fontSize: '0.9rem', color: 'var(--text-primary)', whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>
          {ficha.solucion}
        </p>
        {ficha.descartado && (
          <p style={{ margin: '10px 0 0', fontSize: '0.87rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            ⚠ {t('visual.descartado_etiqueta')} {ficha.descartado}
          </p>
        )}
      </details>

      {/* Las cuatro juntas o ninguna. "Mostrada" sola no distingue una ficha
          útil de una que estorba, y "confirmada" sola no distingue una foto
          buena de una solución que funcione. */}
      <div style={{
        display: 'flex', gap: '18px', flexWrap: 'wrap', marginTop: '14px',
        paddingTop: '12px', borderTop: '1px solid var(--border-color)',
        fontSize: '0.8rem', color: 'var(--text-muted)'
      }}>
        <span>{t('visual.mostrada', { count: ficha.veces_mostrada })}</span>
        <span>{t('visual.confirmada', { count: ficha.veces_confirmada })}</span>
        <span>{t('visual.descartada', { count: ficha.veces_descartada })}</span>
        <span>{t('visual.resuelta', { count: ficha.veces_resuelta })}</span>
      </div>

      <Diagnostico ficha={ficha} />
    </div>
  );
};

/* ================================================================ */
/**
 * Qué le pasa a esta ficha, dicho en una línea.
 *
 * **Los números de arriba sólo sirven si alguien sabe leerlos**, y las dos
 * lecturas que importan no son evidentes:
 *
 *   - Se enseña mucho y **casi nadie la reconoce** -> la foto o las frases
 *     están mal: empareja con consultas que no son la suya.
 *   - La reconocen y **no les arregla** -> la solución está mal escrita, o
 *     bajo esa misma foto hay dos averías distintas y hay que partirla en dos.
 *
 * El segundo es el peor de los dos y el que no se ve: una ficha con la foto
 * perfecta y la solución equivocada la reconoce todo el mundo, así que en el
 * tablero luce como la mejor del catálogo mientras manda a la planta entera a
 * hacer algo que no sirve.
 *
 * Los mínimos están para no diagnosticar sobre ruido: con dos casos no hay
 * patrón, hay dos casos.
 */
const Diagnostico = ({ ficha }) => {
  const { t } = useTranslation();

  const mostrada = ficha.veces_mostrada || 0;
  const confirmada = ficha.veces_confirmada || 0;
  const resuelta = ficha.veces_resuelta || 0;

  let clave = null;
  if (confirmada >= 3 && resuelta / confirmada < 0.5) clave = 'visual.diag_no_arregla';
  else if (mostrada >= 5 && confirmada / mostrada < 0.3) clave = 'visual.diag_no_reconocen';

  if (!clave) return null;

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: '9px', marginTop: '10px',
      padding: '10px 14px', borderRadius: 'var(--radius-md)', fontSize: '0.85rem',
      lineHeight: 1.5,
      background: 'var(--status-espera-proveedor-bg)',
      color: 'var(--status-espera-proveedor-text)'
    }}>
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
      <span>{t(clave)}</span>
    </div>
  );
};

/* ================================================================ */
/** Las fotos de una mitad de la ficha: o el defecto, o dónde hay que picar. */
const Galeria = ({ ficha, rol, imagenes, onCambio, onError }) => {
  const { t } = useTranslation();
  const [subiendo, setSubiendo] = useState(false);

  const subir = async (archivos) => {
    if (!archivos?.length) return;
    setSubiendo(true);
    try {
      for (const archivo of archivos) {
        const datos = new FormData();
        datos.append('archivo', archivo);
        datos.append('rol', rol);
        await api.post(`/admin/visual/${ficha.id}/imagenes`, datos, {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: ESPERA_SUBIDA
        });
      }
      onCambio();
    } catch (err) {
      onError(err.response?.data?.detail || t('visual.error_subir'));
    } finally {
      setSubiendo(false);
    }
  };

  const guardarPie = async (imagen, pie) => {
    if (pie === (imagen.pie || '')) return;
    try {
      await api.patch(`/admin/visual/${ficha.id}/imagenes/${imagen.id}`, { pie });
      onCambio();
    } catch (err) {
      onError(err.response?.data?.detail || t('visual.error_guardar'));
    }
  };

  /* Mover un paso es intercambiar su número con el del vecino. Dos peticiones
     y no una: el orden es de la imagen, no de la lista, así que renumerar
     entera sería reescribir filas que no cambiaron. */
  const mover = async (imagen, salto) => {
    const posicion = imagenes.findIndex((i) => i.id === imagen.id);
    const vecina = imagenes[posicion + salto];
    if (!vecina) return;
    try {
      await api.patch(`/admin/visual/${ficha.id}/imagenes/${imagen.id}`, { orden: vecina.orden });
      await api.patch(`/admin/visual/${ficha.id}/imagenes/${vecina.id}`, { orden: imagen.orden });
      onCambio();
    } catch (err) {
      onError(err.response?.data?.detail || t('visual.error_guardar'));
    }
  };

  const borrar = async (imagen) => {
    try {
      await api.delete(`/admin/visual/${ficha.id}/imagenes/${imagen.id}`);
      onCambio();
    } catch (err) {
      onError(err.response?.data?.detail || t('visual.error_borrar'));
    }
  };

  const Icono = rol === 'sintoma' ? Camera : MousePointerClick;

  return (
    <div style={{ marginTop: '18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
        <Icono size={16} color="var(--accent-primary)" />
        <strong style={{ fontSize: '0.88rem', color: 'var(--text-primary)' }}>
          {t(`visual.galeria_${rol}`)}
        </strong>
      </div>
      <p style={{ margin: '0 0 12px', fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
        {t(`visual.galeria_${rol}_detalle`)}
      </p>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        {imagenes.map((imagen, i) => (
          <div key={imagen.id} style={{
            width: '190px', borderRadius: 'var(--radius-md)', overflow: 'hidden',
            border: '1px solid var(--border-color)', background: 'var(--bg-tertiary)'
          }}>
            <ImagenApi
              ruta={`/visual/fichas/${ficha.id}/imagenes/${imagen.id}`}
              alt={imagen.pie || imagen.nombre_original}
              ancho="190px"
              alto="120px"
            />
            <div style={{ padding: '8px' }}>
              <input
                className="form-input"
                defaultValue={imagen.pie || ''}
                placeholder={t(`visual.pie_${rol}`)}
                maxLength={300}
                onBlur={(e) => guardarPie(imagen, e.target.value.trim())}
                style={{ width: '100%', fontSize: '0.8rem', padding: '6px 8px' }}
              />
              <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
                {rol === 'solucion' && (
                  <>
                    <button className="btn-secondary" onClick={() => mover(imagen, -1)}
                      disabled={i === 0} style={{ padding: '5px 8px' }}
                      aria-label={t('visual.subir_paso')}>
                      <ArrowUp size={13} />
                    </button>
                    <button className="btn-secondary" onClick={() => mover(imagen, 1)}
                      disabled={i === imagenes.length - 1} style={{ padding: '5px 8px' }}
                      aria-label={t('visual.bajar_paso')}>
                      <ArrowDown size={13} />
                    </button>
                  </>
                )}
                <button className="btn-secondary btn-secondary--peligro" onClick={() => borrar(imagen)}
                  style={{ padding: '5px 8px', marginLeft: 'auto' }}
                  aria-label={t('comun.eliminar')}>
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          </div>
        ))}

        <label style={{
          width: '190px', height: '120px', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: '8px', cursor: 'pointer',
          border: '1px dashed var(--border-color)', borderRadius: 'var(--radius-md)',
          color: 'var(--text-secondary)', fontSize: '0.83rem', textAlign: 'center', padding: '10px'
        }}>
          <Upload size={20} color="var(--accent-primary)" />
          {subiendo ? t('visual.subiendo') : t('visual.subir')}
          <input type="file" accept="image/*" multiple hidden disabled={subiendo}
            onChange={(e) => { subir(Array.from(e.target.files || [])); e.target.value = ''; }} />
        </label>
      </div>
    </div>
  );
};

/* ================================================================ */
const EditorFicha = ({ ficha, onGuardar, onCancelar }) => {
  const { t } = useTranslation();
  const [titulo, setTitulo] = useState(ficha?.titulo || '');
  const [categoria, setCategoria] = useState(ficha?.categoria || 'impresora');
  const [sintoma, setSintoma] = useState(ficha?.sintoma || '');
  const [frases, setFrases] = useState(ficha?.frases || '');
  const [solucion, setSolucion] = useState(ficha?.solucion || '');
  const [descartado, setDescartado] = useState(ficha?.descartado || '');

  const valido = titulo.trim().length >= 4
    && sintoma.trim().length >= 10
    && solucion.trim().length >= 10;

  return (
    <Formulario className="apple-card animate-scale-in"
      style={{ padding: '26px', marginBottom: '16px', border: '1px solid var(--accent-primary)' }}
      onSubmit={(e) => {
        e.preventDefault();
        if (!valido) return;
        onGuardar({
          titulo: titulo.trim(), categoria, sintoma: sintoma.trim(),
          frases: frases.trim() || null, solucion: solucion.trim(),
          descartado: descartado.trim() || null
        });
      }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '16px' }}>
        <div className="form-group">
          <label>{t('visual.campo_titulo')}</label>
          <input className="form-input" required style={{ width: '100%' }} value={titulo}
            placeholder={t('visual.campo_titulo_ejemplo')}
            onChange={(e) => setTitulo(e.target.value)} />
        </div>
        <div className="form-group">
          <label>{t('visual.campo_categoria')}</label>
          <Selector className="form-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
            {CATEGORIAS.map((c) => <option key={c} value={c}>{t(`new_ticket.category_${c}`)}</option>)}
          </Selector>
        </div>
      </div>

      <div className="form-group">
        <label>{t('visual.campo_sintoma')}</label>
        <textarea className="form-textarea" rows={3} required value={sintoma}
          placeholder={t('visual.campo_sintoma_ejemplo')}
          onChange={(e) => setSintoma(e.target.value)} />
      </div>

      <div className="form-group">
        <label>{t('visual.campo_frases')}</label>
        <input className="form-input" style={{ width: '100%' }} value={frases}
          placeholder={t('visual.campo_frases_ejemplo')}
          onChange={(e) => setFrases(e.target.value)} />
        {/* No es un campo de adorno: es lo que le enseña al portal a reconocer
            problemas visuales que nadie previó al escribir el código. */}
        <small style={{ color: 'var(--text-muted)', fontSize: '0.8rem', lineHeight: 1.45 }}>
          {t('visual.campo_frases_ayuda')}
        </small>
      </div>

      <div className="form-group">
        <label>{t('visual.campo_solucion')}</label>
        <textarea className="form-textarea" rows={5} required value={solucion}
          placeholder={t('visual.campo_solucion_ejemplo')}
          onChange={(e) => setSolucion(e.target.value)} />
      </div>

      <div className="form-group">
        <label>{t('visual.campo_descartado')}</label>
        <textarea className="form-textarea" rows={2} value={descartado}
          placeholder={t('visual.campo_descartado_ejemplo')}
          onChange={(e) => setDescartado(e.target.value)} />
      </div>

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        <button type="button" onClick={onCancelar} className="btn-secondary" style={{ padding: '10px 18px' }}>
          <X size={15} /> {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-acento" disabled={!valido} style={{ padding: '10px 18px' }}>
          <Check size={15} /> {t('temas.guardar')}
        </button>
      </div>
    </Formulario>
  );
};

export default CatalogoVisual;
