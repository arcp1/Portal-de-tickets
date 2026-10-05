import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Folder, FolderPlus, FolderOpen, Upload, Download, Eye, History, Pencil, Trash2, RotateCcw,
  FileText, FileSpreadsheet, FileImage, FileArchive, File, Search, X, Check, ChevronRight,
  Home, Lock, Globe, Factory, MoveRight
} from 'lucide-react';
import api, { ESPERA_SUBIDA } from '../api/client';
import lista from '../lib/lista';
import forma from '../lib/forma';
import { avisar } from '../lib/avisos';
import Aviso from '../components/Aviso';
import CapaModal from '../components/CapaModal';
import Confirmacion from '../components/Confirmacion';
import EstadoVacio from '../components/EstadoVacio';
import Formulario from '../components/Formulario';
import Selector from '../components/Selector';
import { EsqueletoLista } from '../components/Cargando';
import { usePlantas, PlantasMultiples } from '../lib/plantas';

/* Lo mismo que acepta el backend (services/directorio_service.py). Se mira
   aquí también para decirlo antes de subir 40 MB que van a rebotar; quien
   decide es el servidor. */
const ACEPTADAS = ['pdf', 'docx', 'xlsx', 'pptx', 'doc', 'xls', 'ppt', 'odt', 'ods', 'odp',
  'jpg', 'jpeg', 'png', 'webp', 'gif', 'csv', 'txt', 'zip'];
const MAX_MB = 50;
const PROFUNDIDAD_MAX = 8;

const ICONOS = {
  pdf: FileText, doc: FileText, docx: FileText, odt: FileText, txt: FileText,
  xls: FileSpreadsheet, xlsx: FileSpreadsheet, ods: FileSpreadsheet, csv: FileSpreadsheet,
  ppt: FileText, pptx: FileText, odp: FileText,
  jpg: FileImage, jpeg: FileImage, png: FileImage, webp: FileImage, gif: FileImage,
  zip: FileArchive,
};

function bytes(n, idioma) {
  if (n == null) return '';
  const f = (v, d) => v.toLocaleString(idioma, { maximumFractionDigits: d });
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${f(n / 1024, 0)} KB`;
  return `${f(n / (1024 * 1024), 1)} MB`;
}

function extensionDe(nombre) {
  const i = nombre.lastIndexOf('.');
  return i > 0 ? nombre.slice(i + 1).toLowerCase() : '';
}

/** Pide el archivo con la sesión y lo abre o lo guarda. Los enlaces normales
 *  no llevan el token: por eso no hay `<a href>` directos a la API. */
async function traer(ruta, nombre, ver) {
  const res = await api.get(ruta, { responseType: 'blob', timeout: ESPERA_SUBIDA,
    params: ver ? {} : { descargar: true } });
  const url = URL.createObjectURL(res.data);
  if (ver) {
    window.open(url, '_blank', 'noopener,noreferrer');
  } else {
    const a = document.createElement('a');
    a.href = url;
    a.download = nombre;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

/**
 * El directorio de documentos: carpetas y archivos de la empresa.
 *
 * TI crea carpetas, sube, renombra, mueve, guarda versiones y manda a la
 * papelera. La planta solo lee, y solo las carpetas cuya visibilidad la
 * incluye: lo demás ni aparece. La carpeta abierta va en la URL
 * (`/documentos/archivos/12`), así que se puede volver atrás y mandar el
 * enlace a alguien —que verá la carpeta solo si su visibilidad lo deja—.
 */
export default function Directorio() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { carpetaId } = useParams();
  const [datos, setDatos] = useState(null);
  const [arbol, setArbol] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState(null);
  const [busqueda, setBusqueda] = useState('');
  const [resultados, setResultados] = useState(null);
  const [verPapelera, setVerPapelera] = useState(false);
  const [dialogo, setDialogo] = useState(null);
  const [subiendo, setSubiendo] = useState(null);
  const [arrastrando, setArrastrando] = useState(false);
  const entrada = useRef(null);

  const puedeEditar = Boolean(datos?.puede_editar);
  const carpeta = datos?.carpeta || null;

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const ruta = carpetaId ? `/directorio/carpetas/${carpetaId}` : '/directorio/raiz';
      const [res, resArbol] = await Promise.all([api.get(ruta), api.get('/directorio/arbol')]);
      if (!forma(res.data, ['carpetas', 'archivos', 'migas'], 'el directorio')) throw new Error('forma');
      setDatos(res.data);
      setArbol(lista(resArbol.data, 'el árbol del directorio'));
      setError('');
    } catch (err) {
      setDatos(null);
      setError(err.response?.status === 404 ? t('directorio.no_encontrada') : t('directorio.error_cargar'));
    } finally {
      setCargando(false);
    }
  }, [carpetaId, t]);

  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => { setVerPapelera(false); }, [carpetaId]);

  // La búsqueda espera a que se deje de teclear.
  useEffect(() => {
    const q = busqueda.trim();
    if (q.length < 2) { setResultados(null); return undefined; }
    const temporizador = setTimeout(async () => {
      try {
        const res = await api.get('/directorio/buscar', { params: { q } });
        setResultados({
          carpetas: lista(res.data?.carpetas, 'las carpetas encontradas'),
          archivos: lista(res.data?.archivos, 'los archivos encontrados'),
        });
      } catch { setResultados({ carpetas: [], archivos: [] }); }
    }, 300);
    return () => clearTimeout(temporizador);
  }, [busqueda]);

  const subir = async (archivos) => {
    if (!carpeta || !archivos.length) return;
    const ajenos = archivos.filter((a) => !ACEPTADAS.includes(extensionDe(a.name)));
    const total = archivos.reduce((s, a) => s + a.size, 0);
    if (total > MAX_MB * 1024 * 1024) {
      setAviso({ tono: 'peligro', texto: t('directorio.demasiado', { mb: MAX_MB }) });
      return;
    }
    const validos = archivos.filter((a) => !ajenos.includes(a));
    if (!validos.length) {
      setAviso({ tono: 'peligro', texto: t('directorio.tipo_no_permitido', { nombres: ajenos.map((a) => a.name).join(', ') }) });
      return;
    }
    const cuerpo = new FormData();
    validos.forEach((a) => cuerpo.append('archivos', a, a.name));
    setSubiendo(0);
    try {
      const res = await api.post(`/directorio/carpetas/${carpeta.id}/archivos`, cuerpo, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: ESPERA_SUBIDA,
        onUploadProgress: (e) => e.total && setSubiendo(Math.round((e.loaded / e.total) * 100)),
      });
      const subidos = lista(res.data?.subidos, 'los archivos subidos');
      const rechazados = [
        ...ajenos.map((a) => ({ nombre: a.name, motivo: t('directorio.tipo_no_permitido_corto') })),
        ...lista(res.data?.rechazados, 'los archivos rechazados'),
      ];
      if (rechazados.length) {
        setAviso({ tono: 'atencion', texto: t('directorio.subidos_con_rechazos', { count: subidos.length }),
          lista: rechazados });
      } else {
        setAviso(null);
        avisar(t('directorio.subidos', { count: subidos.length }), { tono: 'exito' });
      }
      cargar();
    } catch (err) {
      setAviso({ tono: 'peligro', texto: err.response?.data?.detail || t('directorio.error_subir') });
    } finally {
      setSubiendo(null);
    }
  };

  const borrar = async ({ tipo, item }) => {
    setDialogo(null);
    try {
      await api.delete(`/directorio/${tipo === 'carpeta' ? 'carpetas' : 'archivos'}/${item.id}`);
      avisar(t('directorio.a_papelera', { nombre: item.nombre }), { tono: 'exito' });
      cargar();
    } catch (err) {
      setAviso({ tono: 'peligro', texto: err.response?.data?.detail || t('directorio.error_guardar') });
    }
  };

  const abrir = (a, ver) => traer(`/directorio/archivos/${a.id}/descarga`, a.nombre, ver)
    .catch(() => setAviso({ tono: 'peligro', texto: t('directorio.error_descargar') }));

  const soltar = (e) => {
    e.preventDefault();
    setArrastrando(false);
    if (puedeEditar && carpeta) subir(Array.from(e.dataTransfer.files || []));
  };

  const titulo = carpeta ? carpeta.nombre : t('directorio.titulo');

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">{titulo}</h1>
          <p>{carpeta?.descripcion || t(puedeEditar ? 'directorio.sub_ti' : 'directorio.sub_planta')}</p>
        </div>
        {puedeEditar && (
          <div className="directorio-acciones">
            {(!carpeta || carpeta.profundidad < PROFUNDIDAD_MAX) && (
              <button type="button" className="btn-secondary"
                onClick={() => setDialogo({ tipo: 'carpeta', padre: carpeta })}>
                <FolderPlus size={16} /> {t('directorio.nueva_carpeta')}
              </button>
            )}
            {carpeta && (
              <button type="button" className="btn-acento" onClick={() => entrada.current?.click()}
                disabled={subiendo !== null}>
                <Upload size={16} /> {subiendo !== null ? t('directorio.subiendo', { pct: subiendo }) : t('directorio.subir')}
              </button>
            )}
            <input ref={entrada} type="file" multiple hidden
              accept={ACEPTADAS.map((e) => '.' + e).join(',')}
              onChange={(e) => { subir(Array.from(e.target.files || [])); e.target.value = ''; }} />
          </div>
        )}
      </div>

      <div className="barra-herramientas directorio-barra">
        <nav className="directorio-migas" aria-label={t('directorio.ubicacion')}>
          <Link to="/documentos/archivos"><Home size={14} aria-hidden="true" /> {t('directorio.inicio')}</Link>
          {(datos?.migas || []).map((m) => (
            <React.Fragment key={m.id}>
              <ChevronRight size={14} aria-hidden="true" />
              <Link to={`/documentos/archivos/${m.id}`}>{m.nombre}</Link>
            </React.Fragment>
          ))}
        </nav>
        <div className="directorio-busqueda">
          <Search size={15} aria-hidden="true" />
          <input className="form-input" type="search" value={busqueda} maxLength={100}
            onChange={(e) => setBusqueda(e.target.value)} placeholder={t('directorio.buscar')}
            aria-label={t('directorio.buscar')} />
        </div>
        {puedeEditar && (
          <button type="button" className={`chip-filtro${verPapelera ? ' chip-filtro--activo' : ''}`}
            onClick={() => setVerPapelera((v) => !v)} aria-pressed={verPapelera}>
            <Trash2 size={14} /> {t('directorio.papelera')}
          </button>
        )}
      </div>

      {aviso && (
        <div className={`aviso-barra aviso-barra--${aviso.tono}`} role="alert">
          <div>
            <div>{aviso.texto}</div>
            {aviso.lista && (
              <ul className="directorio-rechazos">
                {aviso.lista.map((r, i) => <li key={i}><strong>{r.nombre}</strong>: {r.motivo}</li>)}
              </ul>
            )}
          </div>
          <button type="button" className="boton-mini" onClick={() => setAviso(null)} aria-label={t('comun.cerrar_aviso')}>
            <X size={13} />
          </button>
        </div>
      )}

      <div className="directorio-cuerpo">
        <ArbolCarpetas arbol={arbol} actual={carpeta?.id} />

        <div
          className={`directorio-contenido${arrastrando ? ' directorio-contenido--soltar' : ''}`}
          onDragOver={(e) => { if (puedeEditar && carpeta) { e.preventDefault(); setArrastrando(true); } }}
          onDragLeave={() => setArrastrando(false)}
          onDrop={soltar}
        >
          {verPapelera ? (
            <Papelera onCambio={cargar} />
          ) : resultados ? (
            <Resultados resultados={resultados} onAbrir={abrir} />
          ) : cargando && !datos ? (
            <EsqueletoLista filas={4} />
          ) : error ? (
            <Aviso texto={error} tono="peligro" />
          ) : (
            <Contenido
              datos={datos}
              puedeEditar={puedeEditar}
              onAbrir={abrir}
              onDialogo={setDialogo}
              onCarpeta={(c) => navigate(`/documentos/archivos/${c.id}`)}
              idioma={i18n.language}
            />
          )}
          {puedeEditar && carpeta && !verPapelera && !resultados && (
            <p className="directorio-pista">{t('directorio.pista_soltar', { mb: MAX_MB })}</p>
          )}
        </div>
      </div>

      {dialogo?.tipo === 'carpeta' && (
        <DialogoCarpeta padre={dialogo.padre} carpeta={dialogo.carpeta}
          onCerrar={() => setDialogo(null)} onListo={() => { setDialogo(null); cargar(); }} />
      )}
      {dialogo?.tipo === 'mover' && (
        <DialogoMover item={dialogo.item} esCarpeta={dialogo.esCarpeta} arbol={arbol}
          onCerrar={() => setDialogo(null)} onListo={() => { setDialogo(null); cargar(); }} />
      )}
      {dialogo?.tipo === 'archivo' && (
        <DialogoArchivo archivo={dialogo.item}
          onCerrar={() => setDialogo(null)} onListo={() => { setDialogo(null); cargar(); }} />
      )}
      {dialogo?.tipo === 'versiones' && (
        <DialogoVersiones archivo={dialogo.item} puedeEditar={puedeEditar}
          onCerrar={() => setDialogo(null)} onCambio={cargar} />
      )}
      {dialogo?.tipo === 'borrar' && (
        <Confirmacion
          titulo={t('directorio.confirmar_borrar_titulo')}
          mensaje={t(dialogo.esCarpeta ? 'directorio.confirmar_borrar_carpeta' : 'directorio.confirmar_borrar_archivo',
            { nombre: dialogo.item.nombre, dias: 30 })}
          textoConfirmar={t('directorio.mandar_papelera')}
          tono="peligro"
          onConfirmar={() => borrar({ tipo: dialogo.esCarpeta ? 'carpeta' : 'archivo', item: dialogo.item })}
          onCancelar={() => setDialogo(null)}
        />
      )}
    </div>
  );
}

/** El árbol de la izquierda: todas las carpetas que la persona alcanza. Se
 *  despliega solo el camino hasta la abierta, para no enseñar cien nombres. */
function ArbolCarpetas({ arbol, actual }) {
  const { t } = useTranslation();
  const hijas = useMemo(() => {
    const m = new Map();
    arbol.forEach((c) => {
      const k = c.padre_id || 0;
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(c);
    });
    return m;
  }, [arbol]);
  const camino = useMemo(() => {
    const porId = new Map(arbol.map((c) => [c.id, c]));
    const ids = new Set();
    let c = porId.get(actual);
    while (c) { ids.add(c.id); c = porId.get(c.padre_id); }
    return ids;
  }, [arbol, actual]);

  const rama = (padre) => (
    <ul>
      {(hijas.get(padre) || []).map((c) => (
        <li key={c.id}>
          <Link to={`/documentos/archivos/${c.id}`}
            className={`directorio-arbol-enlace${c.id === actual ? ' directorio-arbol-enlace--actual' : ''}`}
            aria-current={c.id === actual ? 'page' : undefined}>
            {camino.has(c.id) ? <FolderOpen size={14} aria-hidden="true" /> : <Folder size={14} aria-hidden="true" />}
            <span>{c.nombre}</span>
          </Link>
          {camino.has(c.id) && hijas.has(c.id) && rama(c.id)}
        </li>
      ))}
    </ul>
  );

  return (
    <aside className="directorio-arbol apple-card" aria-label={t('directorio.carpetas')}>
      {arbol.length ? rama(0) : <p className="directorio-pista">{t('directorio.sin_carpetas')}</p>}
    </aside>
  );
}

function EtiquetaVisibilidad({ carpeta }) {
  const { t } = useTranslation();
  const v = carpeta.visibilidad;
  if (!v) return null;
  const Icono = v === 'ti' ? Lock : v === 'todos' ? Globe : Factory;
  const plantas = (carpeta.plantas || []).map((p) => p.clave).join(', ');
  return (
    <span className={`chip-dato directorio-visibilidad directorio-visibilidad--${v}`}>
      <Icono size={12} aria-hidden="true" /> {t(`directorio.vis_${v}`)}{v === 'plantas' && plantas ? `: ${plantas}` : ''}
    </span>
  );
}

function Contenido({ datos, puedeEditar, onAbrir, onDialogo, onCarpeta, idioma }) {
  const { t } = useTranslation();
  const { carpetas, archivos, carpeta } = datos;
  const fecha = (iso) => (iso ? new Date(iso).toLocaleDateString(idioma, { day: 'numeric', month: 'short', year: 'numeric' }) : '');

  if (!carpetas.length && !archivos.length) {
    return (
      <EstadoVacio icono={<FolderOpen size={28} />}
        texto={carpeta ? t('directorio.carpeta_vacia') : t('directorio.sin_carpetas')}
        detalle={puedeEditar ? (carpeta ? t('directorio.carpeta_vacia_ti') : t('directorio.sin_carpetas_ti')) : null} />
    );
  }

  return (
    <ul className="apple-card directorio-lista">
      {carpeta?.visibilidad_efectiva && puedeEditar && (
        <li className="directorio-fila directorio-fila--info">
          <EtiquetaVisibilidad carpeta={{ visibilidad: carpeta.visibilidad_efectiva, plantas: carpeta.plantas }} />
          {carpeta.padre_id && <span className="directorio-meta">{t('directorio.hereda')}</span>}
        </li>
      )}
      {carpetas.map((c) => (
        <li key={`c${c.id}`} className="directorio-fila">
          <button type="button" className="directorio-nombre" onClick={() => onCarpeta(c)}>
            <Folder size={18} className="directorio-icono directorio-icono--carpeta" aria-hidden="true" />
            <span className="directorio-nombre-texto">{c.nombre}</span>
          </button>
          <span className="directorio-meta">
            {t('directorio.contenido_carpeta', { carpetas: c.subcarpetas, archivos: c.archivos })}
          </span>
          {puedeEditar && <EtiquetaVisibilidad carpeta={c} />}
          {puedeEditar && (
            <span className="directorio-botones">
              <button type="button" className="boton-mini" title={t('directorio.editar')} aria-label={t('directorio.editar')}
                onClick={() => onDialogo({ tipo: 'carpeta', carpeta: c })}><Pencil size={13} /></button>
              <button type="button" className="boton-mini" title={t('directorio.mover')} aria-label={t('directorio.mover')}
                onClick={() => onDialogo({ tipo: 'mover', item: c, esCarpeta: true })}><MoveRight size={13} /></button>
              <button type="button" className="boton-mini" title={t('directorio.mandar_papelera')} aria-label={t('directorio.mandar_papelera')}
                onClick={() => onDialogo({ tipo: 'borrar', item: c, esCarpeta: true })}><Trash2 size={13} /></button>
            </span>
          )}
        </li>
      ))}
      {archivos.map((a) => {
        const Icono = ICONOS[a.extension] || File;
        return (
          <li key={`a${a.id}`} className="directorio-fila">
            <button type="button" className="directorio-nombre" onClick={() => onAbrir(a, a.en_linea)}
              title={a.en_linea ? t('directorio.ver') : t('directorio.descargar')}>
              <Icono size={18} className="directorio-icono" aria-hidden="true" />
              <span className="directorio-nombre-texto">{a.nombre}</span>
            </button>
            <span className="directorio-meta">
              {bytes(a.tamano_bytes, idioma)} · {fecha(a.actualizado_en)}
              {a.version > 1 && <> · v{a.version}</>}
              {a.subido_por && <> · {a.subido_por.nombre}</>}
            </span>
            <span className="directorio-botones">
              {a.en_linea && (
                <button type="button" className="boton-mini" title={t('directorio.ver')} aria-label={t('directorio.ver')}
                  onClick={() => onAbrir(a, true)}><Eye size={13} /></button>
              )}
              <button type="button" className="boton-mini" title={t('directorio.descargar')} aria-label={t('directorio.descargar')}
                onClick={() => onAbrir(a, false)}><Download size={13} /></button>
              {(a.version > 1 || puedeEditar) && (
                <button type="button" className="boton-mini" title={t('directorio.versiones')} aria-label={t('directorio.versiones')}
                  onClick={() => onDialogo({ tipo: 'versiones', item: a })}><History size={13} /></button>
              )}
              {puedeEditar && (
                <>
                  <button type="button" className="boton-mini" title={t('directorio.editar')} aria-label={t('directorio.editar')}
                    onClick={() => onDialogo({ tipo: 'archivo', item: a })}><Pencil size={13} /></button>
                  <button type="button" className="boton-mini" title={t('directorio.mover')} aria-label={t('directorio.mover')}
                    onClick={() => onDialogo({ tipo: 'mover', item: a, esCarpeta: false })}><MoveRight size={13} /></button>
                  <button type="button" className="boton-mini" title={t('directorio.mandar_papelera')} aria-label={t('directorio.mandar_papelera')}
                    onClick={() => onDialogo({ tipo: 'borrar', item: a, esCarpeta: false })}><Trash2 size={13} /></button>
                </>
              )}
            </span>
            {a.descripcion && <p className="directorio-descripcion">{a.descripcion}</p>}
          </li>
        );
      })}
    </ul>
  );
}

function Resultados({ resultados, onAbrir }) {
  const { t } = useTranslation();
  const { carpetas, archivos } = resultados;
  if (!carpetas.length && !archivos.length) {
    return <EstadoVacio icono={<Search size={26} />} texto={t('directorio.sin_resultados')} />;
  }
  return (
    <ul className="apple-card directorio-lista">
      {carpetas.map((c) => (
        <li key={`c${c.id}`} className="directorio-fila">
          <Link to={`/documentos/archivos/${c.id}`} className="directorio-nombre">
            <Folder size={18} className="directorio-icono directorio-icono--carpeta" aria-hidden="true" />
            <span className="directorio-nombre-texto">{c.nombre}</span>
          </Link>
          <span className="directorio-meta">{(c.ubicacion || []).join(' › ') || t('directorio.inicio')}</span>
        </li>
      ))}
      {archivos.map((a) => {
        const Icono = ICONOS[a.extension] || File;
        return (
          <li key={`a${a.id}`} className="directorio-fila">
            <button type="button" className="directorio-nombre" onClick={() => onAbrir(a, a.en_linea)}>
              <Icono size={18} className="directorio-icono" aria-hidden="true" />
              <span className="directorio-nombre-texto">{a.nombre}</span>
            </button>
            <span className="directorio-meta">
              <Link to={`/documentos/archivos/${a.carpeta_id}`}>{(a.ubicacion || []).join(' › ')}</Link>
            </span>
            <span className="directorio-botones">
              <button type="button" className="boton-mini" title={t('directorio.descargar')} aria-label={t('directorio.descargar')}
                onClick={() => onAbrir(a, false)}><Download size={13} /></button>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Papelera({ onCambio }) {
  const { t, i18n } = useTranslation();
  const [filas, setFilas] = useState(null);
  const [aviso, setAviso] = useState('');

  const cargar = useCallback(async () => {
    try {
      setFilas(lista((await api.get('/directorio/papelera')).data, 'la papelera'));
    } catch { setFilas([]); setAviso(t('directorio.error_cargar')); }
  }, [t]);
  useEffect(() => { cargar(); }, [cargar]);

  const restaurar = async (f) => {
    try {
      await api.post(`/directorio/papelera/${f.tipo}/${f.id}/restaurar`);
      avisar(t('directorio.restaurado', { nombre: f.nombre }), { tono: 'exito' });
      setAviso('');
      cargar();
      onCambio();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('directorio.error_guardar'));
    }
  };

  const fecha = (iso) => new Date(iso).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' });
  if (filas === null) return <EsqueletoLista filas={3} />;
  return (
    <>
      {aviso && <Aviso texto={aviso} tono="peligro" />}
      <p className="directorio-pista">{t('directorio.papelera_explica', { dias: 30 })}</p>
      {filas.length === 0 ? (
        <EstadoVacio icono={<Trash2 size={26} />} texto={t('directorio.papelera_vacia')} />
      ) : (
        <ul className="apple-card directorio-lista">
          {filas.map((f) => {
            const Icono = f.tipo === 'carpeta' ? Folder : (ICONOS[f.extension] || File);
            return (
              <li key={`${f.tipo}${f.id}`} className="directorio-fila">
                <span className="directorio-nombre directorio-nombre--quieto">
                  <Icono size={18} className="directorio-icono" aria-hidden="true" />
                  <span className="directorio-nombre-texto">{f.nombre}</span>
                </span>
                <span className="directorio-meta">
                  {(f.ubicacion || []).join(' › ') || t('directorio.inicio')}
                  {' · '}{t('directorio.borrado_por', { quien: f.eliminado_por || '—', cuando: fecha(f.eliminado_en) })}
                  {' · '}{t('directorio.se_purga', { cuando: fecha(f.purga_en) })}
                </span>
                <span className="directorio-botones">
                  <button type="button" className="btn-secondary directorio-restaurar" disabled={!f.restaurable}
                    title={f.restaurable ? '' : t('directorio.restaurar_antes')} onClick={() => restaurar(f)}>
                    <RotateCcw size={14} /> {t('directorio.restaurar')}
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

function DialogoCarpeta({ padre, carpeta, onCerrar, onListo }) {
  const { t } = useTranslation();
  const [plantas] = usePlantas();
  const esRaiz = carpeta ? !carpeta.padre_id : !padre;
  const [nombre, setNombre] = useState(carpeta?.nombre || '');
  const [descripcion, setDescripcion] = useState(carpeta?.descripcion || '');
  const [visibilidad, setVisibilidad] = useState(carpeta?.visibilidad || 'ti');
  const [sitios, setSitios] = useState((carpeta?.plantas || []).map((p) => p.id));
  const [aviso, setAviso] = useState('');
  const [enviando, setEnviando] = useState(false);

  const guardar = async () => {
    if (esRaiz && visibilidad === 'plantas' && !sitios.length) {
      setAviso(t('directorio.elige_planta'));
      return;
    }
    setEnviando(true);
    const cuerpo = { nombre: nombre.trim(), descripcion: descripcion.trim() || null };
    if (esRaiz) Object.assign(cuerpo, { visibilidad, sitio_ids: visibilidad === 'plantas' ? sitios : [] });
    try {
      if (carpeta) await api.patch(`/directorio/carpetas/${carpeta.id}`, cuerpo);
      else await api.post('/directorio/carpetas', { ...cuerpo, padre_id: padre?.id || null });
      onListo();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('directorio.error_guardar'));
    } finally {
      setEnviando(false);
    }
  };

  const titulo = carpeta ? t('directorio.editar_carpeta') : t('directorio.nueva_carpeta');
  return (
    <CapaModal onCerrar={onCerrar} etiqueta={titulo}>
      <Formulario onSubmit={guardar} className="apple-card animate-scale-in directorio-dialogo"
        onClick={(e) => e.stopPropagation()}>
        <h2>{titulo}</h2>
        {padre && <p className="nota-suave">{t('directorio.dentro_de', { nombre: padre.nombre })}</p>}
        <div className="form-group">
          <label htmlFor="carpeta-nombre">{t('directorio.nombre')}</label>
          <input id="carpeta-nombre" className="form-input" required maxLength={120} autoFocus
            value={nombre} onChange={(e) => setNombre(e.target.value)} />
        </div>
        <div className="form-group">
          <label htmlFor="carpeta-descripcion">{t('directorio.descripcion')}</label>
          <textarea id="carpeta-descripcion" className="form-textarea" rows={2} maxLength={2000}
            value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
        </div>
        {esRaiz ? (
          <div className="form-group">
            <label htmlFor="carpeta-visibilidad">{t('directorio.quien_ve')}</label>
            <Selector id="carpeta-visibilidad" className="form-select" value={visibilidad}
              onChange={(e) => setVisibilidad(e.target.value)}>
              <option value="ti">{t('directorio.vis_ti_largo')}</option>
              <option value="todos">{t('directorio.vis_todos_largo')}</option>
              <option value="plantas">{t('directorio.vis_plantas_largo')}</option>
            </Selector>
            {visibilidad === 'plantas' && (
              <div style={{ marginTop: '10px' }}>
                <PlantasMultiples plantas={plantas} value={sitios} onChange={setSitios}
                  idGrupo="carpeta-plantas" conPrincipal={false} />
              </div>
            )}
            <p className="nota-suave">{t('directorio.visibilidad_nota')}</p>
          </div>
        ) : (
          <p className="nota-suave">{t('directorio.hereda_largo')}</p>
        )}
        <Aviso texto={aviso} />
        <div className="directorio-dialogo-pie">
          <button type="button" onClick={onCerrar} className="btn-secondary"><X size={15} /> {t('comun.cancelar')}</button>
          <button type="submit" className="btn-acento" disabled={enviando}>
            <Check size={15} /> {enviando ? t('temas.guardando') : t('temas.guardar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
}

function DialogoMover({ item, esCarpeta, arbol, onCerrar, onListo }) {
  const { t } = useTranslation();
  const [destino, setDestino] = useState('');
  const [aviso, setAviso] = useState('');
  const [enviando, setEnviando] = useState(false);

  // Una carpeta no puede ir dentro de sí misma ni de lo que tiene debajo.
  const prohibidas = useMemo(() => {
    if (!esCarpeta) return new Set();
    const ids = new Set([item.id]);
    let creciendo = true;
    while (creciendo) {
      creciendo = false;
      arbol.forEach((c) => { if (c.padre_id && ids.has(c.padre_id) && !ids.has(c.id)) { ids.add(c.id); creciendo = true; } });
    }
    return ids;
  }, [arbol, item, esCarpeta]);

  const opciones = useMemo(() => {
    const porPadre = new Map();
    arbol.forEach((c) => {
      const k = c.padre_id || 0;
      if (!porPadre.has(k)) porPadre.set(k, []);
      porPadre.get(k).push(c);
    });
    const salida = [];
    const recorrer = (padre, nivel) => (porPadre.get(padre) || []).forEach((c) => {
      if (prohibidas.has(c.id)) return;
      salida.push({ id: c.id, texto: `${' '.repeat(nivel)}${c.nombre}` });
      recorrer(c.id, nivel + 1);
    });
    recorrer(0, 0);
    return salida;
  }, [arbol, prohibidas]);

  const mover = async () => {
    setEnviando(true);
    try {
      if (esCarpeta) {
        await api.patch(`/directorio/carpetas/${item.id}`, { padre_id: destino === 'raiz' ? null : Number(destino) });
      } else {
        await api.patch(`/directorio/archivos/${item.id}`, { carpeta_id: Number(destino) });
      }
      onListo();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('directorio.error_guardar'));
    } finally {
      setEnviando(false);
    }
  };

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={t('directorio.mover')}>
      <Formulario onSubmit={mover} className="apple-card animate-scale-in directorio-dialogo"
        onClick={(e) => e.stopPropagation()}>
        <h2>{t('directorio.mover_titulo', { nombre: item.nombre })}</h2>
        <div className="form-group">
          <label htmlFor="mover-destino">{t('directorio.destino')}</label>
          <Selector id="mover-destino" className="form-select" required value={destino}
            onChange={(e) => setDestino(e.target.value)}>
            <option value="" disabled>{t('directorio.elige_destino')}</option>
            {esCarpeta && <option value="raiz">{t('directorio.primer_nivel')}</option>}
            {opciones.map((o) => <option key={o.id} value={String(o.id)}>{o.texto}</option>)}
          </Selector>
          {esCarpeta && <p className="nota-suave">{t('directorio.mover_nota')}</p>}
        </div>
        <Aviso texto={aviso} />
        <div className="directorio-dialogo-pie">
          <button type="button" onClick={onCerrar} className="btn-secondary"><X size={15} /> {t('comun.cancelar')}</button>
          <button type="submit" className="btn-acento" disabled={enviando || !destino}>
            <MoveRight size={15} /> {t('directorio.mover')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
}

function DialogoArchivo({ archivo, onCerrar, onListo }) {
  const { t } = useTranslation();
  const [nombre, setNombre] = useState(archivo.nombre);
  const [descripcion, setDescripcion] = useState(archivo.descripcion || '');
  const [aviso, setAviso] = useState('');
  const [enviando, setEnviando] = useState(false);

  const guardar = async () => {
    setEnviando(true);
    try {
      await api.patch(`/directorio/archivos/${archivo.id}`, { nombre: nombre.trim(), descripcion: descripcion.trim() || null });
      onListo();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('directorio.error_guardar'));
    } finally {
      setEnviando(false);
    }
  };

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={t('directorio.editar')}>
      <Formulario onSubmit={guardar} className="apple-card animate-scale-in directorio-dialogo"
        onClick={(e) => e.stopPropagation()}>
        <h2>{t('directorio.editar_archivo')}</h2>
        <div className="form-group">
          <label htmlFor="archivo-nombre">{t('directorio.nombre')}</label>
          <input id="archivo-nombre" className="form-input" required maxLength={255} autoFocus
            value={nombre} onChange={(e) => setNombre(e.target.value)} />
          <p className="nota-suave">{t('directorio.misma_extension', { ext: '.' + archivo.extension })}</p>
        </div>
        <div className="form-group">
          <label htmlFor="archivo-descripcion">{t('directorio.descripcion')}</label>
          <textarea id="archivo-descripcion" className="form-textarea" rows={3} maxLength={2000}
            value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
        </div>
        <Aviso texto={aviso} />
        <div className="directorio-dialogo-pie">
          <button type="button" onClick={onCerrar} className="btn-secondary"><X size={15} /> {t('comun.cancelar')}</button>
          <button type="submit" className="btn-acento" disabled={enviando}>
            <Check size={15} /> {enviando ? t('temas.guardando') : t('temas.guardar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
}

function DialogoVersiones({ archivo, puedeEditar, onCerrar, onCambio }) {
  const { t, i18n } = useTranslation();
  const [versiones, setVersiones] = useState(null);
  const [aviso, setAviso] = useState('');
  const [subiendo, setSubiendo] = useState(false);
  const entrada = useRef(null);

  const cargar = useCallback(async () => {
    try {
      setVersiones(lista((await api.get(`/directorio/archivos/${archivo.id}/versiones`)).data, 'las versiones'));
    } catch { setVersiones([]); setAviso(t('directorio.error_cargar')); }
  }, [archivo.id, t]);
  useEffect(() => { cargar(); }, [cargar]);

  const nueva = async (fichero) => {
    if (!fichero) return;
    if (fichero.size > MAX_MB * 1024 * 1024) { setAviso(t('directorio.demasiado', { mb: MAX_MB })); return; }
    const cuerpo = new FormData();
    cuerpo.append('archivo', fichero, fichero.name);
    setSubiendo(true);
    try {
      await api.put(`/directorio/archivos/${archivo.id}/contenido`, cuerpo, {
        headers: { 'Content-Type': 'multipart/form-data' }, timeout: ESPERA_SUBIDA });
      setAviso('');
      avisar(t('directorio.version_nueva_lista'), { tono: 'exito' });
      cargar();
      onCambio();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('directorio.error_subir'));
    } finally {
      setSubiendo(false);
    }
  };

  const fecha = (iso) => new Date(iso).toLocaleString(i18n.language, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  const base = archivo.nombre.replace(/\.[^.]+$/, '');

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={t('directorio.versiones')}>
      <div className="apple-card animate-scale-in directorio-dialogo directorio-dialogo--ancho"
        onClick={(e) => e.stopPropagation()}>
        <h2>{t('directorio.versiones_de', { nombre: archivo.nombre })}</h2>
        <p className="nota-suave">{t('directorio.versiones_nota', { max: 10 })}</p>
        <Aviso texto={aviso} tono="peligro" />
        {versiones === null ? <EsqueletoLista filas={2} /> : (
          <ul className="directorio-lista directorio-lista--simple">
            {versiones.map((v) => (
              <li key={v.version} className="directorio-fila">
                <span className="directorio-nombre directorio-nombre--quieto">
                  <strong>v{v.version}</strong>
                  {v.vigente && <span className="chip-dato">{t('directorio.vigente')}</span>}
                </span>
                <span className="directorio-meta">
                  {fecha(v.creado_en)} · {bytes(v.tamano_bytes, i18n.language)}{v.subido_por && <> · {v.subido_por.nombre}</>}
                </span>
                <span className="directorio-botones">
                  <button type="button" className="boton-mini" title={t('directorio.descargar')} aria-label={t('directorio.descargar')}
                    onClick={() => traer(`/directorio/archivos/${archivo.id}/versiones/${v.version}`,
                      v.vigente ? archivo.nombre : `${base} (v${v.version}).${archivo.extension}`, false)
                      .catch(() => setAviso(t('directorio.error_descargar')))}>
                    <Download size={13} />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="directorio-dialogo-pie">
          {puedeEditar && (
            <>
              <input ref={entrada} type="file" hidden accept={'.' + archivo.extension}
                onChange={(e) => { nueva(e.target.files?.[0]); e.target.value = ''; }} />
              <button type="button" className="btn-acento" disabled={subiendo} onClick={() => entrada.current?.click()}>
                <Upload size={15} /> {subiendo ? t('directorio.subiendo_simple') : t('directorio.subir_version')}
              </button>
            </>
          )}
          <button type="button" onClick={onCerrar} className="btn-secondary"><X size={15} /> {t('directorio.cerrar')}</button>
        </div>
      </div>
    </CapaModal>
  );
}
