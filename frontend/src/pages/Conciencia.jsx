import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import GlassCard from '../components/GlassCard';
import Aviso from '../components/Aviso';
import { EsqueletoLista } from '../components/Cargando';
import MapaConocimiento from '../components/MapaConocimiento';
import TuberiaAprendizaje, {
  AvisosAprendizaje, Realimentacion,
} from '../components/TuberiaAprendizaje';
import {
  Brain, Filter, Library, MessageSquareText, Cpu, Cloud, FileText, XCircle, Camera
} from 'lucide-react';

/**
 * Conciencia: qué sabe el portal, cómo lo aprende y qué se le escapa.
 *
 * **La pantalla va de lo general a lo particular, y ese orden es el argumento.**
 *
 *   1. EL MAPA       ¿De qué sabe la planta y de qué no?
 *   2. LA TUBERÍA    ¿Está entrando conocimiento nuevo, o se atascó?
 *   3. LAS CONSULTAS ¿Qué se preguntó, y qué se encontró para cada una?
 *
 * Leído al revés —que es como se llega normalmente, desde una queja concreta—
 * el diagnóstico sale mal. Una respuesta mala del asistente parece un problema
 * del modelo, y casi siempre es que no había nada que recuperar. Empezando por
 * el mapa, eso se ve antes de tocar un umbral.
 *
 * El caso que motivó esta pantalla: tres entradas en toda la base de
 * conocimiento, las tres etiquetadas "impresora", y una de ellas hablando en
 * realidad de una cuenta bloqueada. Ningún ajuste del modelo arregla eso, y
 * ninguna de las pantallas que ya existían lo enseñaba.
 */

const ORIGEN_ICONO = {
  directo: Library,
  ollama: Cpu,
  gemini: Cloud,
  extractos: FileText,
  sin_fundamento: XCircle,
  // Los cuatro del catálogo visual. Comparten icono a propósito: lo que los
  // distingue no es de dónde salieron sino cómo acabaron, y eso ya lo dice el
  // rótulo de al lado.
  visual: Camera,
  visual_sin_foto: Camera,
  visual_ninguna: Camera,
  visual_no_arreglo: Camera,
};

/** Los orígenes que significan "no se pudo contestar".
 *
 *  Los tres visuales son el mismo hueco por otro camino: alguien describió un
 *  defecto que se ve y el portal no tenía la foto, o la tenía mal elegida, o la
 *  solución atada a ella no le funcionó. Piden el mismo trabajo que los otros
 *  dos —documentar—, sólo que con una cámara en la mano.
 *
 *  Tiene que coincidir con `ORIGENES_FALLIDOS` del backend. */
const FALLIDOS = [
  'sin_fundamento', 'extractos',
  'visual_sin_foto', 'visual_ninguna', 'visual_no_arreglo',
];

/** Los cuatro estados de una categoría y su color, en orden de gravedad. */
const LEYENDA = [
  ['cubierto', 'var(--cgr-verde)'],
  ['flojo', 'var(--status-espera-proveedor-text)'],
  ['hueco', 'var(--peligro)'],
  ['vacio', 'var(--text-muted)'],
];

const Conciencia = () => {
  const { t } = useTranslation();
  const [panorama, setPanorama] = useState(null);
  const [aprendizaje, setAprendizaje] = useState(null);
  const [consultas, setConsultas] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  // Lo que el usuario está mirando: una categoría del mapa, y si quiere ver
  // solo lo que falló. Los dos filtran el nivel 3.
  const [categoria, setCategoria] = useState(null);
  const [soloFallidas, setSoloFallidas] = useState(false);

  const cargarGeneral = useCallback(async () => {
    try {
      // En paralelo: son dos agregaciones independientes y encadenarlas solo
      // sumaría el ida y vuelta de la más lenta a la de la otra.
      const [pan, apr] = await Promise.all([
        api.get('/admin/conciencia/panorama'),
        api.get('/admin/conciencia/aprendizaje'),
      ]);
      setPanorama(pan.data);
      setAprendizaje(apr.data);
      setError('');
    } catch {
      setError(t('conciencia.error_cargar'));
    } finally {
      setCargando(false);
    }
  }, [t]);

  const cargarConsultas = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (soloFallidas) params.set('solo_fallidas', 'true');
      if (categoria) params.set('categoria', categoria);
      const res = await api.get(`/admin/conciencia/consultas?${params}`);
      setConsultas(res.data);
    } catch {
      setConsultas(null);
    }
  }, [soloFallidas, categoria]);

  useEffect(() => { cargarGeneral(); }, [cargarGeneral]);
  // El nivel 3 se recarga solo cuando cambian sus filtros; el panorama no, que
  // es mucho más caro de calcular y no depende de ellos.
  useEffect(() => { cargarConsultas(); }, [cargarConsultas]);

  if (cargando) return <div className="page-container"><EsqueletoLista /></div>;

  const total = panorama?.total || {};
  const categorias = panorama?.categorias || [];
  const huecos = categorias.filter((c) => c.estado === 'hueco');
  // Qué estados aparecen de verdad en el mapa, para no explicar de más.
  const presentes = new Set(categorias.map((c) => c.estado));
  const fallo = aprendizaje?.consultas || {};

  return (
    <div className="page-container animate-fade-in conciencia-pagina">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <Brain size={26} style={{ verticalAlign: '-4px', marginRight: '8px' }} />
            {t('conciencia.title')}
          </h1>
          <p>{t('conciencia.subtitle')}</p>
        </div>
      </div>

      {error && <Aviso texto={error} tono="peligro" />}

      {/* ---------- NIVEL 1 · EL MAPA ---------- */}
      <GlassCard>
        <Encabezado
          numero="1"
          titulo={t('conciencia.nivel1_titulo')}
          ayuda={t('conciencia.nivel1_ayuda')}
        />

        {/* Dos columnas en cuanto hay ancho: el dibujo a la izquierda y lo que
            hay que leer a la derecha.

            Apilado, este bloque medía 708 px — más alto que el viewport de un
            portátil— y no se podía ver el mapa y su leyenda a la vez, mientras
            460 px de ancho quedaban vacíos al lado. Repartirlo no es una
            preferencia estética: es lo que hace que la tarjeta entre entera en
            una pantalla, que era el punto de tenerla. */}
        <div className="conciencia-nivel1">
          <MapaConocimiento
            panorama={panorama}
            seleccionada={categoria}
            onSeleccionar={setCategoria}
          />

          <div className="conciencia-resumen">
            <div className="conciencia-titular">
              {total.conocimiento === 0
                ? t('conciencia.titular_vacio')
                : t('conciencia.titular', {
                    piezas: total.conocimiento,
                    vacias: total.categorias_vacias,
                  })}
            </div>

            {/* De qué está hecho ese total. Los tres números ya venían en la
                respuesta y no se enseñaban en ninguna parte: no es lo mismo
                saber diez cosas porque hay diez tickets resueltos que porque
                alguien escribió diez procedimientos. */}
            <div className="conciencia-desglose">
              <Cifra n={total.kb} texto={t('conciencia.de_tickets')} />
              <Cifra n={total.soluciones} texto={t('conciencia.de_procedimientos')} />
              <Cifra n={total.documentos} texto={t('conciencia.de_documentacion')} />
            </div>

            {/* Cómo se lee el dibujo. Va pegado al mapa y a su leyenda, no en
                la cabecera de la tarjeta: es lo que hace falta para descifrarlo.
                Y solo cuando hay algo que descifrar — con todo en cero los
                nodos miden igual y las líneas pesan igual, así que la frase
                describiría algo que no se ve. */}
            {total.conocimiento > 0 && (
              <p className="conciencia-como-leer">{t('conciencia.como_leer')}</p>
            )}

            {/* Solo los colores que hay en el dibujo.
                
                Explicar cuatro estados cuando en pantalla solo existe uno es
                ruido, y el primer dia —cuando todo esta vacio y la persona
                menos contexto tiene— es justo cuando mas estorba. */}
            <div className="conciencia-leyenda">
              {LEYENDA.filter(([clave]) => presentes.has(clave)).map(([clave, color]) => (
                <Leyenda key={clave} color={color} texto={t(`conciencia.estado_cat.${clave}`)} />
              ))}
            </div>

            {huecos.length > 0 && (
              <div className="conciencia-huecos">
                {t('conciencia.huecos_aviso', {
                  lista: huecos
                    .map((h) => t(`conciencia.cat.${h.categoria}`, h.categoria))
                    .join(', '),
                })}
              </div>
            )}
          </div>
        </div>
      </GlassCard>

      {/* ---------- NIVEL 2 · LA TUBERÍA ---------- */}
      <GlassCard>
        <Encabezado
          numero="2"
          titulo={t('conciencia.nivel2_titulo')}
          ayuda={t('conciencia.nivel2_ayuda')}
        />
        <TuberiaAprendizaje aprendizaje={aprendizaje} />
        <Realimentacion aprendizaje={aprendizaje} />

        <div className="conciencia-subtitulo">{t('conciencia.por_atender')}</div>
        <AvisosAprendizaje
          aprendizaje={aprendizaje}
          hayConocimiento={total.conocimiento > 0}
        />
      </GlassCard>

      {/* ---------- NIVEL 3 · LAS CONSULTAS ---------- */}
      <GlassCard>
        {/* La ayuda dice la cifra, no una generalidad.
            
            `ratio_fallo` se calculaba en el backend y no se enseñaba en ningún
            sitio — el mismo descuido que ya tenían el desglose y los votos. Y
            es probablemente el número más importante de esta pantalla: qué
            fracción de lo que se pregunta no se puede contestar.
            
            Va aquí, en el sitio del texto de ayuda que ya existía, en vez de
            en un recuadro nuevo: la pantalla ya tiene bastantes bloques. */}
        <Encabezado
          numero="3"
          titulo={t('conciencia.nivel3_titulo')}
          ayuda={
            fallo.total
              ? t('conciencia.nivel3_cifra', {
                  fallidas: fallo.fallidas,
                  total: fallo.total,
                  pct: Math.round((fallo.ratio_fallo || 0) * 100),
                })
              : t('conciencia.nivel3_ayuda')
          }
          alerta={fallo.total > 0 && (fallo.ratio_fallo || 0) >= 0.4}
        />

        <div className="conciencia-filtros">
          <button
            type="button"
            className={`conciencia-filtro${soloFallidas ? ' activo' : ''}`}
            onClick={() => setSoloFallidas((v) => !v)}
          >
            <Filter size={13} aria-hidden="true" />
            {t('conciencia.solo_fallidas')}
          </button>
          {categoria && (
            <button
              type="button"
              className="conciencia-filtro activo"
              onClick={() => setCategoria(null)}
            >
              {t(`conciencia.cat.${categoria}`, categoria)} ✕
            </button>
          )}
        </div>

        <ListaConsultas consultas={consultas} t={t} />
      </GlassCard>
    </div>
  );
};

const Encabezado = ({ numero, titulo, ayuda, alerta = false }) => (
  <div className="conciencia-encabezado">
    <span className="conciencia-numero">{numero}</span>
    <div>
      <h2>{titulo}</h2>
      {/* `alerta` tiñe la ayuda cuando la cifra que lleva es mala. Sin eso,
          "20 de 47 no se pudieron contestar" se lee con el mismo gris que
          cualquier explicación y pasa desapercibido. */}
      <p data-alerta={alerta ? 'si' : undefined}>{ayuda}</p>
    </div>
  </div>
);

const Leyenda = ({ color, texto }) => (
  <span className="conciencia-leyenda-item">
    <span className="conciencia-punto" style={{ background: color }} />
    {texto}
  </span>
);

/** Una cifra del desglose. En cero se atenúa: es una ausencia, no un dato. */
const Cifra = ({ n, texto }) => (
  <div className="conciencia-cifra" data-vacia={!n ? 'si' : undefined}>
    <strong>{n ?? 0}</strong>
    <span>{texto}</span>
  </div>
);

const ListaConsultas = ({ consultas, t }) => {
  if (!consultas) return null;
  const filas = consultas.consultas || [];

  if (!filas.length) {
    return <div className="conciencia-vacio">{t('conciencia.sin_consultas')}</div>;
  }

  return (
    <>
      <div className="conciencia-resumen-origen">
        {Object.entries(consultas.por_origen || {}).map(([origen, n]) => (
          <span key={origen} className={`conciencia-pastilla${FALLIDOS.includes(origen) ? ' fallida' : ''}`}>
            {t(`conciencia.origen.${origen}`, origen)}: <strong>{n}</strong>
          </span>
        ))}
      </div>

      <div className="conciencia-tabla-envoltorio">
        <table className="conciencia-tabla">
          {/* Los anchos van aquí y no en los `th`: con `table-layout: fixed`
              el navegador toma la medida de la primera fila, y ésa es la de
              las columnas, no la de los encabezados. */}
          <colgroup>
            <col className="col-pregunta" />
            <col className="col-encontrado" />
            <col className="col-resultado" />
            <col className="col-tiempo" />
          </colgroup>
          <thead>
            <tr>
              <th>{t('conciencia.col_pregunta')}</th>
              <th>{t('conciencia.col_encontrado')}</th>
              <th>{t('conciencia.col_resultado')}</th>
              <th>{t('conciencia.col_tiempo')}</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((c) => {
              const Icono = ORIGEN_ICONO[c.origen] || MessageSquareText;
              const fallida = FALLIDOS.includes(c.origen);
              return (
                <tr key={c.id} className={fallida ? 'fallida' : undefined}>
                  <td>
                    <div className="conciencia-pregunta">{c.pregunta}</div>
                    {c.categoria && (
                      <div className="conciencia-meta">
                        {t(`conciencia.cat.${c.categoria}`, c.categoria)}
                      </div>
                    )}
                  </td>
                  <td>
                    {c.pasajes === 0 ? (
                      <span className="conciencia-meta">{t('conciencia.nada')}</span>
                    ) : (
                      <>
                        {c.pasajes} ·{' '}
                        {c.mejor_similitud != null
                          ? `${Math.round(c.mejor_similitud * 100)}%`
                          : '—'}
                        {c.mejor_fuente && (
                          <div className="conciencia-meta">
                            {t(`conciencia.fuente.${c.mejor_fuente}`, c.mejor_fuente)}
                          </div>
                        )}
                      </>
                    )}
                  </td>
                  <td>
                    <span className={`conciencia-origen${fallida ? ' fallida' : ''}`}>
                      <Icono size={13} aria-hidden="true" />
                      {t(`conciencia.origen.${c.origen}`, c.origen)}
                    </span>
                  </td>
                  <td className="conciencia-tiempo">
                    {c.duracion_ms != null ? `${(c.duracion_ms / 1000).toFixed(1)} s` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
};

export default Conciencia;
