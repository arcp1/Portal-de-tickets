import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import forma from '../lib/forma';
import lista from '../lib/lista';
import { TrendingUp, Database, MessageCircle, Cpu, Star, Radio, ArrowRight, Bell } from 'lucide-react';
import { usePlantas, SelectorPlanta } from '../lib/plantas';
import NumeroQueSube from '../components/NumeroQueSube';
import GlassCard from '../components/GlassCard';
import Aviso from '../components/Aviso';
import Selector from '../components/Selector';
import { entero, porcentaje, proporcion, duracion, milisegundos, sobreCinco, deTotal } from '../lib/cifras';

/**
 * Tablero del admin.
 *
 * Regla de lectura: cuando una tasa vale `null` es que todavía no hay datos
 * para calcularla, y se muestra "—", no un 0%. Un cero falso se lee como mal
 * resultado y lleva a decisiones equivocadas.
 *
 * **Cada casilla dice de cuándo es** (rediseño del 2026-10-05). Convivían
 * cifras de los últimos treinta días, de la última semana, de siempre y de
 * este instante sin que nada las distinguiera: «Total» y «Sin cerrar» uno
 * al lado del otro parecían la misma ventana de tiempo. Ahora cada una lleva
 * su ámbito —«30 d», «histórico», «ahora»— y el selector de periodo mueve
 * solo las que dependen de él.
 *
 * **La IA no reescribe lo que escribe el usuario.** Lo que aquí se mide como
 * «Resumen para TI» es un texto aparte que la IA escribe para el técnico; la
 * descripción original queda intacta y es la que se enseña primero en el
 * ticket. Los nombres de las casillas lo dicen así a propósito.
 */

const Tarjeta = ({ etiqueta, valor, formatear, ambito, ayuda, sinAnimar = false }) => (
  <div className="casilla-metrica">
    <div className="casilla-metrica-cabeza">
      <div className="casilla-metrica-etiqueta">{etiqueta}</div>
      {ambito && <span className="casilla-metrica-ambito">{ambito}</span>}
    </div>
    <div className="casilla-metrica-valor">
      {sinAnimar ? valor : <NumeroQueSube valor={valor} formatear={formatear} />}
    </div>
    {ayuda && <div className="casilla-metrica-ayuda">{ayuda}</div>}
  </div>
);

const Seccion = ({ icono, titulo, children, accion }) => (
  // La tarjeta de cristal envuelve cada bloque de métricas. El borde separa
  // una sección de la siguiente mejor que el espacio en blanco: aquí abajo hay
  // muchas cifras seguidas y sin un canto que las agrupe se leen como una
  // lista larga en vez de como tres temas distintos.
  <GlassCard relleno="28px" style={{ marginBottom: '24px' }}>
    <div className="titulo-bloque-fila">
      <h2 className="titulo-bloque">
        {icono}
        {titulo}
      </h2>
      {accion}
    </div>
    {children}
  </GlassCard>
);

/** Barras horizontales con cifra y porcentaje: canales y categorías. */
const Reparto = ({ filas, total, nombre, idioma }) => (
  <div className="reparto">
    {filas.map(([clave, n]) => (
      <div key={clave} className="fila-canal">
        <div className="fila-canal-nombre">{nombre(clave)}</div>
        <div className="fila-canal-pista">
          <div className="fila-canal-relleno" style={{ width: `${(100 * n) / total}%` }} />
        </div>
        <div className="fila-canal-cifra">
          {entero(n, idioma)} · {porcentaje(Math.round((1000 * n) / total) / 10, idioma)}
        </div>
      </div>
    ))}
  </div>
);

const PERIODOS = [7, 30, 90];

const Metricas = () => {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(false);
  // TI ve todas las plantas juntas; puede quedarse con una.
  const [plantas] = usePlantas();
  const [plantaId, setPlantaId] = useState(null);
  const [dias, setDias] = useState(30);

  useEffect(() => {
    const params = { dias };
    if (plantaId) params.sitio_id = plantaId;
    api.get('/metricas', { params })
      .then((res) => { setDatos(res.data); setError(false); })
      .catch(() => setError(true))
      .finally(() => setCargando(false));
  }, [plantaId, dias]);

  if (cargando) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('metricas.cargando')}</div>;
  }
  // Se comprueban los bloques, no solo que `datos` no sea nulo. Con un cuerpo
  // de otra forma, `tickets` salía `undefined` y la línea de abajo
  // —`tickets.por_canal`— tumbaba la pantalla entera con «Algo se rompió».
  // Enseñar el aviso de error es cierto y deja la pantalla en pie.
  if (error || !forma(datos, ['tickets', 'base_conocimiento', 'chatbot', 'ollama'], 'las métricas')) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('metricas.error')}</div>;
  }

  const { tickets, base_conocimiento: kb, chatbot, ollama } = datos;
  // Los sensores llegaron después: un backend anterior no los manda y la
  // pantalla sigue sin ese bloque en vez de caerse.
  const sensores = datos.sensores && typeof datos.sensores === 'object' ? datos.sensores : null;
  const canales = Object.entries(tickets.por_canal || {}).sort((a, b) => b[1] - a[1]);
  // `forma` comprueba los bloques de primer nivel, no lo que hay dentro de
  // cada uno. Ésta se recorre con `.map`, así que se guarda aparte: estas dos
  // claves vecinas **no tienen la misma forma** —`por_canal` es un
  // diccionario y `por_categoria` una lista—.
  const categorias = lista(tickets.por_categoria, 'las categorías de tickets').map((c) => [c.categoria, c.total]);
  const totalCanales = canales.reduce((suma, [, n]) => suma + n, 0);
  const totalCategorias = categorias.reduce((suma, [, n]) => suma + n, 0);
  const satisfaccion = tickets.satisfaccion || null;
  const distribucion = satisfaccion?.distribucion || {};
  const maxEstrellas = Math.max(1, ...Object.values(distribucion).map(Number).filter(Number.isFinite));
  const plantaElegida = plantas.find((p) => p.id === plantaId);
  const latencias = ollama.latencias_ms || {};

  const fmt = {
    entero: (v) => entero(v, idioma),
    pct: (v) => porcentaje(v, idioma),
    prop: (v) => proporcion(v, idioma),
    min: (v) => duracion(v, idioma),
    ms: (v) => milisegundos(v, idioma),
    cinco: (v) => sobreCinco(v, idioma),
  };
  const amb = {
    periodo: t('metricas.ambito_dias', { count: tickets.periodo_dias || dias }),
    semana: t('metricas.ambito_dias', { count: 7 }),
    historico: t('metricas.ambito_historico'),
    ahora: t('metricas.ambito_ahora'),
    ajuste: t('metricas.ambito_ajuste'),
    reinicio: t('metricas.ambito_reinicio'),
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {t('metricas.title')}
          </h1>
          <p>
            {t('metricas.subtitle', { dias: tickets.periodo_dias || dias })}
            {' · '}
            {plantaElegida ? plantaElegida.nombre : t('plantas.todas')}
          </p>
        </div>
        <div className="metricas-controles">
          <Selector className="form-select" value={String(dias)} onChange={(e) => setDias(Number(e.target.value))}
            aria-label={t('metricas.periodo_selector')}>
            {PERIODOS.map((d) => <option key={d} value={String(d)}>{t('comun.ultimos_dias', { count: d })}</option>)}
          </Selector>
          {plantas.length > 1 && (
            <SelectorPlanta todas plantas={plantas} value={plantaId} onChange={setPlantaId}
              style={{ minWidth: '230px' }} />
          )}
        </div>
      </div>

      <Seccion icono={<TrendingUp size={20} color="var(--accent-primary)" />} titulo={t('metricas.tickets')}>
        <h3 className="rotulo-seccion metricas-subtitulo">{t('metricas.grupo_volumen')}</h3>
        <div className="rejilla-metricas">
          <Tarjeta etiqueta={t('metricas.total')} valor={tickets.tickets_total} formatear={fmt.entero} ambito={amb.historico} />
          <Tarjeta etiqueta={t('metricas.periodo', { count: tickets.periodo_dias || dias })}
            valor={tickets.tickets_periodo} formatear={fmt.entero} ambito={amb.periodo} />
          <Tarjeta etiqueta={t('metricas.abiertos')} valor={tickets.tickets_abiertos} formatear={fmt.entero} ambito={amb.ahora} />
          {/* Aparte y con su propia explicación: ninguna de las otras cifras
              los cuenta, y sin decirlo el total parecería no cuadrar con el
              tablero. */}
          <Tarjeta etiqueta={t('metricas.cancelados')} valor={tickets.tickets_cancelados_periodo ?? tickets.tickets_cancelados}
            formatear={fmt.entero} ambito={tickets.tickets_cancelados_periodo != null ? amb.periodo : amb.historico}
            ayuda={t('metricas.cancelados_ayuda')} />
        </div>

        <h3 className="rotulo-seccion metricas-subtitulo">{t('metricas.grupo_desempeno')}</h3>
        <div className="rejilla-metricas">
          <Tarjeta etiqueta={t('metricas.deflexion')} valor={tickets.tasa_deflexion} formatear={fmt.pct}
            ambito={amb.historico} ayuda={t('metricas.deflexion_ayuda')} />
          <Tarjeta etiqueta={t('metricas.tiempo_promedio')} valor={tickets.tiempo_resolucion_promedio_min}
            formatear={fmt.min} ambito={amb.historico} ayuda={t('metricas.tiempo_ayuda')} />
          <Tarjeta etiqueta={t('metricas.normalizados')} valor={tickets.tasa_normalizacion} formatear={fmt.pct}
            ambito={amb.historico} ayuda={t('metricas.normalizados_ayuda')} />
        </div>

        {/* Distribución por canal: la métrica más importante de la spec */}
        <h3 className="rotulo-seccion metricas-subtitulo">
          {t('metricas.por_canal')} <span className="casilla-metrica-ambito">{amb.historico}</span>
        </h3>
        {totalCanales === 0 ? (
          <div className="metricas-vacio">{t('metricas.sin_datos')}</div>
        ) : (
          <Reparto filas={canales} total={totalCanales} idioma={idioma}
            nombre={(canal) => t(`metricas.canal_${canal}`, { defaultValue: canal })} />
        )}

        {/* Top de incidencias recurrentes: dice qué arreglar de raíz */}
        <h3 className="rotulo-seccion metricas-subtitulo">
          {t('metricas.top_categorias')} <span className="casilla-metrica-ambito">{amb.historico}</span>
        </h3>
        {totalCategorias === 0 ? (
          <div className="metricas-vacio">{t('metricas.sin_datos')}</div>
        ) : (
          <Reparto filas={categorias} total={totalCategorias} idioma={idioma}
            nombre={(c) => t(`new_ticket.category_${c}`, { defaultValue: c })} />
        )}
      </Seccion>

      {/* Lo que el tiempo de resolución no cuenta: rápido no es lo mismo
          que bien resuelto. La contestan quienes reportaron. */}
      {satisfaccion && (
        <Seccion icono={<Star size={20} color="var(--accent-primary)" />} titulo={t('encuesta.metricas_titulo')}>
          <div className="rejilla-metricas">
            <Tarjeta etiqueta={t('encuesta.promedio')} valor={satisfaccion.promedio} formatear={fmt.cinco} ambito={amb.periodo} />
            <Tarjeta etiqueta={t('encuesta.respuestas')} valor={satisfaccion.respuestas} formatear={fmt.entero} ambito={amb.periodo} />
            <Tarjeta etiqueta={t('encuesta.tasa_respuesta')} valor={satisfaccion.tasa_respuesta} formatear={fmt.pct}
              ambito={amb.periodo} ayuda={t('encuesta.tasa_respuesta_ayuda')} />
          </div>
          {satisfaccion.respuestas > 0 && (
            <div className="distribucion-estrellas" style={{ marginTop: '22px' }}>
              {[5, 4, 3, 2, 1].map((n) => {
                const cuantos = Number(distribucion[String(n)] || 0);
                return (
                  <div key={n} className="fila-canal">
                    <div className="fila-canal-nombre" aria-label={t('encuesta.n_de_5', { n })}>
                      {'★'.repeat(n)}<span style={{ opacity: 0.25 }}>{'★'.repeat(5 - n)}</span>
                    </div>
                    <div className="fila-canal-pista">
                      <div className={`fila-canal-relleno${n <= 2 ? ' fila-canal-relleno--baja' : ''}`}
                        style={{ width: `${(100 * cuantos) / maxEstrellas}%` }} />
                    </div>
                    <div className="fila-canal-cifra">{entero(cuantos, idioma)}</div>
                  </div>
                );
              })}
            </div>
          )}
        </Seccion>
      )}

      {/* Los ESP32, en resumen: el detalle está en Monitoreo. */}
      {sensores && (
        <Seccion
          icono={<Radio size={20} color="var(--accent-primary)" />}
          titulo={t('metricas.sensores')}
          accion={(
            <div className="metricas-enlaces">
              <Link to="/operacion/alertas" className="btn-secondary metricas-boton"><Bell size={15} /> {t('metricas.ver_alertas')}</Link>
              <Link to="/operacion/monitoreo" className="btn-acento metricas-boton">{t('metricas.ir_monitoreo')} <ArrowRight size={15} /></Link>
            </div>
          )}
        >
          {sensores.dispositivos === 0 ? (
            <div className="metricas-vacio">{t('metricas.sin_sensores')}</div>
          ) : (
            <div className="rejilla-metricas">
              <Tarjeta etiqueta={t('metricas.sensores_en_linea')}
                valor={deTotal(sensores.en_linea, sensores.dispositivos, idioma)} sinAnimar ambito={amb.ahora}
                ayuda={t('metricas.sensores_en_linea_ayuda', { minutos: sensores.sin_senal_minutos })} />
              <Tarjeta etiqueta={t('metricas.sensores_alertas')} valor={sensores.alertas_periodo} formatear={fmt.entero}
                ambito={amb.periodo}
                ayuda={t('metricas.sensores_alertas_ayuda', {
                  umbral: sensores.alertas_por_tipo?.iot_umbral ?? 0,
                  senal: sensores.alertas_por_tipo?.iot_sin_senal ?? 0,
                })} />
              <Tarjeta etiqueta={t('metricas.sensores_pendientes')} valor={sensores.alertas_pendientes}
                formatear={fmt.entero} ambito={amb.ahora} />
            </div>
          )}
        </Seccion>
      )}

      <Seccion icono={<Database size={20} color="var(--accent-primary)" />} titulo={t('metricas.kb')}>
        <div className="rejilla-metricas">
          <Tarjeta etiqueta={t('metricas.utilidad')} valor={kb.tasa_utilidad} formatear={fmt.pct}
            ambito={amb.historico} ayuda={t('metricas.utilidad_ayuda')} />
          <Tarjeta etiqueta={t('metricas.entradas')} valor={kb.entradas_kb} formatear={fmt.entero} ambito={amb.ahora} />
          <Tarjeta etiqueta={t('metricas.mostradas_semana')} valor={kb.sugerencias_mostradas_semana}
            formatear={fmt.entero} ambito={amb.semana} />
          <Tarjeta etiqueta={t('metricas.resueltas_kb')} valor={kb.incidencias_resueltas_por_kb}
            formatear={fmt.entero} ambito={amb.historico} />
          <Tarjeta etiqueta={t('metricas.umbral')} valor={kb.umbral_actual} formatear={fmt.prop}
            ambito={amb.ajuste} ayuda={t('metricas.umbral_ayuda')} />
          <Tarjeta etiqueta={t('metricas.pendientes')} valor={kb.tickets_pendientes_indexar} formatear={fmt.entero}
            ambito={amb.ahora} ayuda={t('metricas.pendientes_ayuda')} />
        </div>
      </Seccion>

      <Seccion icono={<MessageCircle size={20} color="var(--accent-primary)" />} titulo={t('metricas.chatbot')}>
        <div className="rejilla-metricas">
          <Tarjeta etiqueta={t('metricas.sesiones')} valor={chatbot.sesiones_iniciadas} formatear={fmt.entero} ambito={amb.historico} />
          <Tarjeta etiqueta={t('metricas.termino_ticket')} valor={chatbot.porcentaje_termino_en_ticket}
            formatear={fmt.pct} ambito={amb.historico} />
          <Tarjeta etiqueta={t('metricas.precision')} valor={chatbot.precision_clasificacion} formatear={fmt.pct}
            ambito={amb.historico} ayuda={t('metricas.precision_ayuda', { count: chatbot.clasificaciones_comparables })} />
          <Tarjeta etiqueta={t('metricas.umbral_confianza')} valor={chatbot.umbral_confianza} formatear={fmt.prop}
            ambito={amb.ajuste} ayuda={t('metricas.umbral_confianza_ayuda')} />
        </div>
      </Seccion>

      <Seccion icono={<Cpu size={20} color="var(--accent-primary)" />} titulo={t('metricas.ollama')}>
        {!ollama.disponible && <Aviso texto={t('metricas.ollama_caido')} />}
        <div className="rejilla-metricas">
          <Tarjeta etiqueta={t('metricas.estado')} sinAnimar ambito={amb.ahora}
            valor={ollama.disponible ? t('metricas.en_linea') : t('metricas.fuera_linea')} />
          <Tarjeta etiqueta={t('metricas.lat_embedding')} valor={latencias.embedding} formatear={fmt.ms}
            ambito={amb.reinicio} ayuda={t('metricas.lat_embedding_ayuda')} />
          <Tarjeta etiqueta={t('metricas.lat_normalizacion')} valor={latencias.normalizacion} formatear={fmt.ms}
            ambito={amb.reinicio} ayuda={t('metricas.lat_normalizacion_ayuda')} />
          <Tarjeta etiqueta={t('metricas.lat_clasificacion')} valor={latencias.clasificacion} formatear={fmt.ms}
            ambito={amb.reinicio} ayuda={t('metricas.lat_clasificacion_ayuda')} />
        </div>
        <div className="metricas-nota">
          {t('metricas.latencia_nota')}
        </div>
      </Seccion>
    </div>
  );
};

export default Metricas;
