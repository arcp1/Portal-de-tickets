import React, {
  forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState
} from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight, ImagePlus, Images, Trash2, X } from 'lucide-react';
import api, { ESPERA_SUBIDA } from '../api/client';
import ImagenApi from './ImagenApi';
import CapaModal from './CapaModal';
import lista from '../lib/lista';

/**
 * Imágenes que acompañan a un texto del conocimiento: un paso del checklist,
 * una entrada de la base de conocimiento o la solución de un ticket.
 *
 * Dos piezas:
 *
 *  - `GaleriaImagenes`, para leer. Es lo que ve quien sigue un paso o abre su
 *    ticket resuelto: miniaturas debajo del texto y, al tocar una, la imagen
 *    entera.
 *  - `EditorImagenes`, para TI. Subir, arrastrar, **pegar con Ctrl+V** —una
 *    captura recortada con Win+Shift+S va directo al portapapeles, y obligar a
 *    guardarla en un archivo antes es un paso que nadie quiere dar—, poner pie
 *    de foto y quitar.
 *
 * Las imágenes viven detrás del token, así que se pintan con `ImagenApi`, que
 * las descarga autenticadas. El backend está en app/api/imagenes.py.
 */

/** Lo mismo que acepta el backend. HEIC no: fuera de Safari no se pinta. */
const TIPOS = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
const MAX_MB = 10;
/* Un solo arreglo vacío para todos. Con `= []` en los parámetros cada render
   estrenaría uno, y el efecto que sigue a `imagenes` se dispararía sin fin. */
const SIN_IMAGENES = [];

/**
 * Los archivos de imagen de un portapapeles o de lo que se arrastró.
 *
 * **Si además viene texto, no es una captura.** Copiar celdas de Excel o un
 * párrafo de Word pone en el portapapeles el texto *y* un dibujo de lo
 * copiado. Quien pega ahí quiere el texto; quedarse con la imagen se lo
 * comería. Solo se intercepta lo que llega como imagen sola.
 */
export function imagenesDe(datos, { soloSiNoHayTexto = false } = {}) {
  if (!datos) return [];
  if (soloSiNoHayTexto && datos.types && Array.from(datos.types).includes('text/plain')) return [];
  return Array.from(datos.files || []).filter((f) => f.type?.startsWith('image/'));
}

/* ------------------------------------------------------------------ */
/* Ver                                                                 */
/* ------------------------------------------------------------------ */

/**
 * La imagen entera, encima de todo. Con flechas si hay varias: en una
 * secuencia de pasos lo natural es ir a la siguiente sin cerrar.
 */
export function VisorImagen({ imagenes, inicial = 0, onCerrar }) {
  const { t } = useTranslation();
  const [indice, setIndice] = useState(inicial);
  const total = imagenes.length;
  const actual = imagenes[indice];

  const mover = useCallback((paso) => {
    setIndice((i) => (i + paso + total) % total);
  }, [total]);

  useEffect(() => {
    if (total < 2) return undefined;
    const alPulsar = (e) => {
      if (e.key === 'ArrowRight') mover(1);
      if (e.key === 'ArrowLeft') mover(-1);
    };
    window.addEventListener('keydown', alPulsar);
    return () => window.removeEventListener('keydown', alPulsar);
  }, [mover, total]);

  if (!actual) return null;

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={actual.pie || t('imagenes.ver')}>
      <figure className="visor-imagen" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="visor-imagen-cerrar" onClick={onCerrar}
          aria-label={t('imagenes.cerrar')}>
          <X size={18} />
        </button>
        {/* Una imagen todavía sin subir es un blob local: no hay ruta que
            pedir. Las demás van por `ImagenApi`, con el token. */}
        {actual.url ? (
          <img src={actual.url} alt={actual.pie || ''} className="visor-imagen-local" />
        ) : (
          <ImagenApi
            ruta={`/imagenes/${actual.id}`}
            alt={actual.pie || actual.nombre_original || ''}
            alto="auto"
            ajuste="contain"
            estilo={{ maxHeight: '76vh', background: 'rgba(0,0,0,0.35)' }}
          />
        )}
        {(actual.pie || total > 1) && (
          <figcaption className="visor-imagen-pie">
            {total > 1 && (
              <button type="button" className="boton-mini" onClick={() => mover(-1)}
                aria-label={t('imagenes.anterior')}>
                <ChevronLeft size={16} />
              </button>
            )}
            <span>
              {actual.pie}
              {total > 1 && <span className="visor-imagen-cuenta">{indice + 1} / {total}</span>}
            </span>
            {total > 1 && (
              <button type="button" className="boton-mini" onClick={() => mover(1)}
                aria-label={t('imagenes.siguiente')}>
                <ChevronRight size={16} />
              </button>
            )}
          </figcaption>
        )}
      </figure>
    </CapaModal>
  );
}

/**
 * Miniaturas debajo de un texto. Con `imagenes` las pinta tal cual —los
 * listados ya las traen—; sin ellas, las pide a `/imagenes/{tipo}/{id}`.
 * Sin imágenes no pinta nada: ni un título encima de un hueco.
 */
export function GaleriaImagenes({ imagenes, tipo, id, compacta = false, className = '' }) {
  const { t } = useTranslation();
  const [propias, setPropias] = useState(null);
  const [abierta, setAbierta] = useState(null);

  const pedir = imagenes === undefined && tipo && id;
  useEffect(() => {
    if (!pedir) return undefined;
    let vivo = true;
    api.get(`/imagenes/${tipo}/${id}`)
      .then((r) => { if (vivo) setPropias(lista(r.data, 'las imágenes')); })
      // Sin imágenes el texto sigue sirviendo: no hay nada que avisar.
      .catch(() => { if (vivo) setPropias([]); });
    return () => { vivo = false; };
  }, [pedir, tipo, id]);

  const todas = lista(imagenes ?? propias ?? [], 'las imágenes');
  if (todas.length === 0) return null;

  return (
    <>
      <div className={`galeria-imagenes${compacta ? ' galeria-imagenes--compacta' : ''} ${className}`}
        role="list" aria-label={t('imagenes.titulo')}>
        {todas.map((img, i) => (
          <figure key={img.id} className="galeria-imagen" role="listitem">
            <button type="button" className="galeria-imagen-boton" onClick={() => setAbierta(i)}
              aria-label={img.pie ? t('imagenes.ampliar_con_pie', { pie: img.pie }) : t('imagenes.ampliar')}>
              <ImagenApi
                ruta={`/imagenes/${img.id}`}
                alt={img.pie || img.nombre_original || ''}
                alto={compacta ? '86px' : '150px'}
              />
            </button>
            {img.pie && !compacta && <figcaption className="galeria-pie">{img.pie}</figcaption>}
          </figure>
        ))}
      </div>
      {abierta !== null && (
        <VisorImagen imagenes={todas} inicial={abierta} onCerrar={() => setAbierta(null)} />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Editar (TI)                                                         */
/* ------------------------------------------------------------------ */

let consecutivo = 0;

/**
 * Las imágenes de un paso, de una entrada o de la solución de un ticket.
 *
 * **Dos modos, según exista ya o no aquello a lo que pertenecen.**
 *
 *  - Con `id`: lo que se sube, se corrige o se quita va al servidor en el
 *    acto, y `onCambio` recibe la lista nueva.
 *  - Sin `id` —un paso que todavía no se guarda, una solución que se está
 *    escribiendo—: las imágenes se quedan aquí, en vista previa, y se suben
 *    con `subirPendientes(id)` cuando quien llama ya tiene el id. Así cancelar
 *    el formulario no deja imágenes huérfanas colgando de nada.
 *
 * Por `ref` se exponen `pegar(evento)` —para que el formulario entero acepte
 * Ctrl+V, no solo esta caja— y `subirPendientes(id)`.
 */
export const EditorImagenes = forwardRef(function EditorImagenes(
  { tipo, id = null, imagenes = SIN_IMAGENES, onCambio, etiqueta }, ref
) {
  const { t } = useTranslation();
  const [actuales, setActuales] = useState(() => lista(imagenes, 'las imágenes'));
  const [pendientes, setPendientes] = useState([]);
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState('');
  const [arrastrando, setArrastrando] = useState(false);
  const [abierta, setAbierta] = useState(null);
  const entrada = useRef(null);
  const pendientesRef = useRef([]);
  pendientesRef.current = pendientes;

  // Si el dueño se recarga desde fuera —otra pestaña, el evento en vivo—, se
  // toma su lista. Solo en modo directo: en el diferido la verdad está aquí.
  useEffect(() => {
    if (id) setActuales(lista(imagenes, 'las imágenes'));
  }, [id, imagenes]);

  // Las vistas previas son blobs: sin esto se quedan en memoria mientras
  // viva la pestaña.
  useEffect(() => () => {
    pendientesRef.current.forEach((p) => URL.revokeObjectURL(p.url));
  }, []);

  const directo = Boolean(id);

  const aceptables = (archivos) => {
    const buenos = [];
    for (const f of archivos) {
      if (!TIPOS.includes(f.type)) {
        setError(t('imagenes.tipo_no_valido', { nombre: f.name || t('imagenes.pegada') }));
      } else if (f.size > MAX_MB * 1024 * 1024) {
        setError(t('imagenes.muy_grande', { nombre: f.name || t('imagenes.pegada'), mb: MAX_MB }));
      } else {
        buenos.push(f);
      }
    }
    return buenos;
  };

  const enviar = async (destinoId, archivo, pie = '') => {
    const datos = new FormData();
    // Una captura pegada llega como "image.png" en todos los navegadores: se
    // le pone un nombre que diga algo en la descarga.
    const nombre = archivo.name && archivo.name !== 'image.png'
      ? archivo.name
      : `captura-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`;
    datos.append('archivo', archivo, nombre);
    datos.append('pie', pie || '');
    const res = await api.post(`/imagenes/${tipo}/${destinoId}`, datos, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: ESPERA_SUBIDA
    });
    return lista(res.data, 'las imágenes');
  };

  const agregar = async (archivos) => {
    setError('');
    const buenos = aceptables(Array.from(archivos || []));
    if (buenos.length === 0) return;

    if (!directo) {
      setPendientes((p) => [
        ...p,
        ...buenos.map((archivo) => ({
          clave: `p${++consecutivo}`, archivo, pie: '', url: URL.createObjectURL(archivo)
        }))
      ]);
      return;
    }

    setSubiendo(true);
    let ultima = null;
    let actual = null;
    try {
      for (const archivo of buenos) {
        actual = archivo;
        ultima = await enviar(id, archivo);
      }
    } catch (err) {
      const motivo = err.response?.data?.detail || t('imagenes.error_subir');
      setError(buenos.length > 1 && actual?.name ? `${actual.name}: ${motivo}` : motivo);
    } finally {
      if (ultima) { setActuales(ultima); onCambio?.(ultima); }
      setSubiendo(false);
      if (entrada.current) entrada.current.value = '';
    }
  };

  const pegar = (e) => {
    const archivos = imagenesDe(e.clipboardData, { soloSiNoHayTexto: true });
    if (archivos.length === 0) return false;
    e.preventDefault();
    agregar(archivos);
    return true;
  };

  /** Sube lo que estaba en vista previa. Devuelve cuántas no se pudieron. */
  const subirPendientes = async (destinoId) => {
    const lote = pendientesRef.current;
    if (!destinoId || lote.length === 0) return 0;
    setSubiendo(true);
    let fallidas = 0;
    let ultima = null;
    for (const p of lote) {
      try {
        ultima = await enviar(destinoId, p.archivo, p.pie);
      } catch {
        fallidas += 1;
      }
    }
    lote.forEach((p) => URL.revokeObjectURL(p.url));
    setPendientes([]);
    setSubiendo(false);
    if (ultima) onCambio?.(ultima);
    return fallidas;
  };

  useImperativeHandle(ref, () => ({
    pegar,
    agregar,
    subirPendientes,
    hayPendientes: () => pendientesRef.current.length > 0,
  }));

  const quitar = async (img) => {
    setError('');
    if (!directo) {
      URL.revokeObjectURL(img.url);
      setPendientes((p) => p.filter((x) => x.clave !== img.clave));
      return;
    }
    try {
      const res = await api.delete(`/imagenes/${img.id}`);
      const nueva = lista(res.data, 'las imágenes');
      setActuales(nueva);
      onCambio?.(nueva);
    } catch (err) {
      setError(err.response?.data?.detail || t('imagenes.error_quitar'));
    }
  };

  const cambiarPie = (img, pie) => {
    if (!directo) {
      setPendientes((p) => p.map((x) => (x.clave === img.clave ? { ...x, pie } : x)));
    } else {
      setActuales((a) => a.map((x) => (x.id === img.id ? { ...x, pie } : x)));
    }
  };

  // El pie se guarda al salir del campo, no a cada tecla.
  const guardarPie = async (img) => {
    if (!directo) return;
    try {
      const res = await api.patch(`/imagenes/${img.id}`, { pie: img.pie || '' });
      const nueva = lista(res.data, 'las imágenes');
      setActuales(nueva);
      onCambio?.(nueva);
    } catch (err) {
      setError(err.response?.data?.detail || t('imagenes.error_pie'));
    }
  };

  const fichas = directo ? actuales : pendientes;
  const paraVisor = fichas.map((f) => (directo ? f : { ...f, id: f.clave }));

  return (
    <div className="editor-imagenes">
      <div className="editor-imagenes-rotulo">
        <Images size={15} aria-hidden="true" />
        <span>{etiqueta || t('imagenes.titulo_opcional')}</span>
        {fichas.length > 0 && <span className="editor-imagenes-cuenta">{fichas.length}</span>}
      </div>

      {fichas.length > 0 && (
        <div className="galeria-imagenes galeria-imagenes--edicion">
          {fichas.map((img, i) => (
            <figure key={img.id || img.clave} className="galeria-imagen">
              <button type="button" className="galeria-imagen-boton" onClick={() => setAbierta(i)}
                aria-label={t('imagenes.ampliar')}>
                {directo ? (
                  <ImagenApi ruta={`/imagenes/${img.id}`} alt={img.pie || ''} alto="96px" />
                ) : (
                  <img src={img.url} alt={img.pie || ''}
                    style={{ width: '100%', height: '96px', objectFit: 'cover', display: 'block' }} />
                )}
              </button>
              <input
                className="form-input galeria-pie-campo"
                value={img.pie || ''}
                maxLength={300}
                placeholder={t('imagenes.pie_placeholder')}
                aria-label={t('imagenes.pie')}
                onChange={(e) => cambiarPie(img, e.target.value)}
                onBlur={() => guardarPie(img)}
                // Enter no envía el formulario de fuera: guarda este pie.
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur(); } }}
              />
              <button type="button" className="galeria-quitar" onClick={() => quitar(img)}
                aria-label={t('imagenes.quitar')} title={t('imagenes.quitar')}>
                <Trash2 size={14} />
              </button>
            </figure>
          ))}
        </div>
      )}

      <div
        className={`zona-imagenes${arrastrando ? ' zona-imagenes--activa' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastrando(false);
          agregar(imagenesDe(e.dataTransfer));
        }}
      >
        <button type="button" className="btn-secondary" disabled={subiendo}
          onClick={() => entrada.current?.click()} style={{ padding: '8px 14px', fontSize: '0.86rem' }}>
          <ImagePlus size={15} />
          {subiendo ? t('imagenes.subiendo') : t('imagenes.agregar')}
        </button>
        <span className="zona-imagenes-texto">{t('imagenes.como_agregar')}</span>
        <input
          ref={entrada}
          type="file"
          accept={TIPOS.join(',')}
          multiple
          hidden
          onChange={(e) => agregar(e.target.files)}
        />
      </div>

      <div className="editor-imagenes-nota">
        {t('imagenes.formatos', { mb: MAX_MB })}
        {' '}
        {directo ? t('imagenes.se_guardan_al_subir') : t('imagenes.se_guardan_al_guardar')}
      </div>

      {error && <div className="editor-imagenes-error" role="alert">{error}</div>}

      {abierta !== null && (
        <VisorImagen imagenes={paraVisor} inicial={abierta} onCerrar={() => setAbierta(null)} />
      )}
    </div>
  );
});
