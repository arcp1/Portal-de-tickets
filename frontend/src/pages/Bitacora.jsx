import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ScrollText } from 'lucide-react';
import api from '../api/client';
import lista from '../lib/lista';
import forma from '../lib/forma';
import Selector from '../components/Selector';
import Aviso from '../components/Aviso';
import EstadoVacio from '../components/EstadoVacio';
import { EsqueletoLista } from '../components/Cargando';

const PAGINA = 100;

/** A dónde lleva el id de una fila, si es algo que tiene pantalla propia. */
function enlaceDe(entidad, id) {
  if (!id) return null;
  if (entidad === 'ticket') return `/tickets/${id}`;
  if (entidad === 'usuario') return `/personas/${id}`;
  if (entidad === 'carpeta') return `/documentos/archivos/${id}`;
  return null;
}

/** Un valor del detalle, corto y legible: la bitácora es para leerse de
 *  corrido, no para depurar JSON. */
function corto(valor) {
  if (valor === null || valor === undefined || valor === '') return '—';
  if (typeof valor === 'object') {
    const texto = JSON.stringify(valor);
    return texto.length > 80 ? texto.slice(0, 77) + '…' : texto;
  }
  const texto = String(valor);
  return texto.length > 120 ? texto.slice(0, 117) + '…' : texto;
}

/** El detalle de una fila en renglones: «campo: antes → después» cuando
 *  registró un cambio, «campo: valor» cuando no. */
function renglones(detalle) {
  if (!detalle || typeof detalle !== 'object') return [];
  return Object.entries(detalle).map(([campo, v]) => {
    if (v && typeof v === 'object' && !Array.isArray(v) && ('antes' in v || 'despues' in v)) {
      return { campo, texto: `${corto(v.antes)} → ${corto(v.despues)}` };
    }
    return { campo, texto: corto(v) };
  });
}

/**
 * La bitácora: quién hizo qué y cuándo, en todas las plantas.
 *
 * La tabla existía desde el principio y la API también, pero no había
 * pantalla: para saber quién canceló un resguardo había que abrir la base.
 * Es de solo lectura, igual que la API —una bitácora que se puede editar no
 * sirve de bitácora—.
 */
export default function Bitacora() {
  const { t, i18n } = useTranslation();
  const [opciones, setOpciones] = useState({ acciones: [], entidades: [], personas: [] });
  const [accion, setAccion] = useState('');
  const [entidad, setEntidad] = useState('');
  const [persona, setPersona] = useState('');
  const [dias, setDias] = useState('30');
  const [filas, setFilas] = useState([]);
  const [hayMas, setHayMas] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [aviso, setAviso] = useState('');

  useEffect(() => {
    api.get('/auditoria/opciones')
      .then((res) => {
        if (!forma(res.data, ['acciones', 'entidades', 'personas'], 'las opciones de la bitácora')) return;
        setOpciones({
          acciones: lista(res.data.acciones, 'las acciones de la bitácora'),
          entidades: lista(res.data.entidades, 'las entidades de la bitácora'),
          personas: lista(res.data.personas, 'las personas de la bitácora'),
        });
      })
      .catch(() => { /* sin filtros, la lista sigue sirviendo */ });
  }, []);

  const params = useCallback((extra = {}) => {
    const p = { limite: PAGINA, dias: Number(dias), ...extra };
    if (accion) p.accion = accion;
    if (entidad) p.entidad = entidad;
    if (persona) p.usuario_id = Number(persona);
    return p;
  }, [accion, entidad, persona, dias]);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const datos = lista((await api.get('/auditoria', { params: params() })).data, 'la bitácora');
      setFilas(datos);
      setHayMas(datos.length === PAGINA);
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('bitacora.error_cargar'));
    } finally {
      setCargando(false);
    }
  }, [params, t]);

  useEffect(() => { cargar(); }, [cargar]);

  const masAntiguas = async () => {
    const ultima = filas[filas.length - 1];
    if (!ultima) return;
    try {
      const datos = lista((await api.get('/auditoria', { params: params({ antes_de: ultima.id }) })).data, 'la bitácora');
      setFilas((f) => [...f, ...datos]);
      setHayMas(datos.length === PAGINA);
    } catch (err) {
      setAviso(err.response?.data?.detail || t('bitacora.error_cargar'));
    }
  };

  const nombreAccion = (a) => t(`bitacora.acciones.${a.replace(/\./g, '_')}`, { defaultValue: a });
  const nombreEntidad = (e) => t(`bitacora.entidades.${e}`, { defaultValue: e });
  const fecha = (iso) => new Date(iso).toLocaleString(i18n.language, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('bitacora.titulo')}</h1>
          <p>{t('bitacora.sub')}</p>
        </div>
      </div>

      <div className="barra-herramientas filtros-en-fila">
        <Selector className="form-select" value={accion} onChange={(e) => setAccion(e.target.value)}
          aria-label={t('bitacora.filtro_accion')}>
          <option value="">{t('bitacora.todas_acciones')}</option>
          {opciones.acciones.map((a) => <option key={a} value={a}>{nombreAccion(a)}</option>)}
        </Selector>
        <Selector className="form-select" value={entidad} onChange={(e) => setEntidad(e.target.value)}
          aria-label={t('bitacora.filtro_entidad')}>
          <option value="">{t('bitacora.todas_entidades')}</option>
          {opciones.entidades.map((e) => <option key={e} value={e}>{nombreEntidad(e)}</option>)}
        </Selector>
        <Selector className="form-select" value={persona} onChange={(e) => setPersona(e.target.value)}
          aria-label={t('bitacora.filtro_persona')}>
          <option value="">{t('bitacora.todas_personas')}</option>
          {opciones.personas.map((p) => (
            <option key={p.id} value={String(p.id)}>{p.nombre}</option>
          ))}
        </Selector>
        <Selector className="form-select" value={dias} onChange={(e) => setDias(e.target.value)}
          aria-label={t('bitacora.filtro_periodo')}>
          <option value="7">{t('comun.ultimos_dias', { count: 7 })}</option>
          <option value="30">{t('comun.ultimos_dias', { count: 30 })}</option>
          <option value="90">{t('comun.ultimos_dias', { count: 90 })}</option>
          <option value="365">{t('comun.ultimos_dias', { count: 365 })}</option>
        </Selector>
      </div>

      {aviso && <Aviso texto={aviso} tono="peligro" />}

      {cargando && filas.length === 0 ? (
        <EsqueletoLista filas={5} />
      ) : filas.length === 0 ? (
        <EstadoVacio icono={<ScrollText size={28} />} texto={t('bitacora.vacia')} detalle={t('bitacora.vacia_detalle')} />
      ) : (
        <ol className="apple-card bitacora-lista">
          {filas.map((f) => {
            const enlace = enlaceDe(f.entidad, f.entidad_id);
            const detalle = renglones(f.detalle);
            return (
              <li key={f.id} className="bitacora-fila">
                <div className="bitacora-cuando">
                  <time dateTime={f.creado_en}>{fecha(f.creado_en)}</time>
                  {f.ip && <span className="bitacora-ip">{f.ip}</span>}
                </div>
                <div className="bitacora-que">
                  <div>
                    <strong>{f.usuario?.nombre || '—'}</strong>
                    {' · '}
                    <span className="bitacora-accion">{nombreAccion(f.accion)}</span>
                  </div>
                  <div className="bitacora-entidad">
                    {nombreEntidad(f.entidad)}
                    {f.entidad_id ? (enlace
                      ? <> <Link to={enlace}>#{f.entidad_id}</Link></>
                      : ` #${f.entidad_id}`) : null}
                  </div>
                  {detalle.length > 0 && (
                    <dl className="bitacora-detalle">
                      {detalle.map((d) => (
                        <React.Fragment key={d.campo}>
                          <dt>{d.campo}</dt>
                          <dd>{d.texto}</dd>
                        </React.Fragment>
                      ))}
                    </dl>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {hayMas && (
        <div style={{ textAlign: 'center', marginTop: '18px' }}>
          <button type="button" className="btn-secondary" onClick={masAntiguas}>{t('bitacora.mas_antiguas')}</button>
        </div>
      )}
    </div>
  );
}
