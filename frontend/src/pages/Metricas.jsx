import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import forma from '../lib/forma';
import lista from '../lib/lista';
import { TrendingUp, Database, MessageCircle, Cpu, Star } from 'lucide-react';
import { usePlantas, SelectorPlanta } from '../lib/plantas';
import NumeroQueSube from '../components/NumeroQueSube';
import GlassCard from '../components/GlassCard';
import Aviso from '../components/Aviso';

/**
 * Tablero del admin.
 *
 * Regla de lectura: cuando una tasa vale `null` es que todavía no hay datos
 * para calcularla, y se muestra "—", no un 0%. Un cero falso se lee como mal
 * resultado y lleva a decisiones equivocadas.
 */

const Tarjeta = ({ etiqueta, valor, sufijo = '', ayuda }) => (
  <div className="casilla-metrica">
    <div className="casilla-metrica-etiqueta">{etiqueta}</div>
    <div className="casilla-metrica-valor">
      <NumeroQueSube valor={valor} sufijo={sufijo} />
    </div>
    {ayuda && <div className="casilla-metrica-ayuda">{ayuda}</div>}
  </div>
);

const Seccion = ({ icono, titulo, children }) => (
  // La tarjeta de cristal envuelve cada bloque de métricas. El borde separa
  // una sección de la siguiente mejor que el espacio en blanco: aquí abajo hay
  // muchas cifras seguidas y sin un canto que las agrupe se leen como una
  // lista larga en vez de como tres temas distintos.
  <GlassCard relleno="28px" style={{ marginBottom: '24px' }}>
    <h2 className="titulo-bloque">
      {icono}
      {titulo}
    </h2>
    {children}
  </GlassCard>
);

const Metricas = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(false);
  // TI ve todas las plantas juntas; puede quedarse con una.
  const [plantas] = usePlantas();
  const [plantaId, setPlantaId] = useState(null);

  useEffect(() => {
    api.get('/metricas', { params: plantaId ? { sitio_id: plantaId } : {} })
      .then((res) => { setDatos(res.data); setError(false); })
      .catch(() => setError(true))
      .finally(() => setCargando(false));
  }, [plantaId]);

  if (cargando) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('metricas.cargando')}</div>;
  }
  // Se comprueban los cuatro bloques, no solo que `datos` no sea nulo. Con un
  // cuerpo de otra forma, `tickets` salía `undefined` y la línea de abajo
  // —`tickets.por_canal`— tumbaba la pantalla entera con «Algo se rompió».
  // Enseñar el aviso de error es cierto y deja la pantalla en pie.
  if (error || !forma(datos, ['tickets', 'base_conocimiento', 'chatbot', 'ollama'], 'las métricas')) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('metricas.error')}</div>;
  }

  const { tickets, base_conocimiento: kb, chatbot, ollama } = datos;
  const canales = Object.entries(tickets.por_canal || {});
  // `forma` comprueba los cuatro bloques de primer nivel, no lo que hay dentro
  // de cada uno. Ésta se recorre con `.map`, así que se guarda aparte: son las
  // dos mitades del mismo cuidado, y la segunda hace falta porque estas dos
  // claves vecinas **no tienen la misma forma** —`por_canal` es un diccionario
  // y `por_categoria` una lista—, que es precisamente lo fácil de confundir.
  const categorias = lista(tickets.por_categoria, 'las categorías de tickets');
  const totalCanales = canales.reduce((suma, [, n]) => suma + n, 0);
  const satisfaccion = tickets.satisfaccion || null;
  const distribucion = satisfaccion?.distribucion || {};
  const maxEstrellas = Math.max(1, ...Object.values(distribucion).map(Number).filter(Number.isFinite));
  const plantaElegida = plantas.find((p) => p.id === plantaId);

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {t('metricas.title')}
          </h1>
          <p>
              {/* La planta sale de la sesión: las cifras son de la planta de
                  quien mira, y el nombre estaba escrito en la traducción. */}
              {t('metricas.subtitle', { dias: tickets.periodo_dias })}
              {' · '}
              {plantaElegida ? plantaElegida.nombre : t('plantas.todas')}
          </p>
        </div>
        {plantas.length > 1 && (
          <SelectorPlanta todas plantas={plantas} value={plantaId} onChange={setPlantaId}
            style={{ minWidth: '230px' }} />
        )}
      </div>

      <Seccion icono={<TrendingUp size={20} color="var(--accent-primary)" />} titulo={t('metricas.tickets')}>
        <div className="rejilla-metricas">
          <Tarjeta
            etiqueta={t('metricas.deflexion')}
            valor={tickets.tasa_deflexion}
            sufijo="%"
            ayuda={t('metricas.deflexion_ayuda')}
          />
          <Tarjeta etiqueta={t('metricas.total')} valor={tickets.tickets_total} />
          <Tarjeta etiqueta={t('metricas.semana')} valor={tickets.tickets_ultima_semana} />
          <Tarjeta etiqueta={t('metricas.abiertos')} valor={tickets.tickets_abiertos} />
          <Tarjeta
            etiqueta={t('metricas.tiempo_promedio')}
            valor={tickets.tiempo_resolucion_promedio_min}
            sufijo=" min"
            ayuda={t('metricas.tiempo_ayuda')}
          />
          <Tarjeta
            etiqueta={t('metricas.normalizados')}
            valor={tickets.tasa_normalizacion}
            sufijo="%"
            ayuda={t('metricas.normalizados_ayuda')}
          />
          {/* Aparte y con su propia explicación: ninguna de las cifras de
              arriba los cuenta, y sin decirlo el total parecería no cuadrar
              con el tablero. */}
          <Tarjeta
            etiqueta={t('metricas.cancelados')}
            valor={tickets.tickets_cancelados}
            ayuda={t('metricas.cancelados_ayuda')}
          />
        </div>

        {/* Distribución por canal: la métrica más importante de la spec */}
        <h3 className="rotulo-seccion" style={{ margin: '28px 0 14px' }}>
          {t('metricas.por_canal')}
        </h3>
        {totalCanales === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{t('metricas.sin_datos')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {canales.sort((a, b) => b[1] - a[1]).map(([canal, n]) => (
              <div key={canal} className="fila-canal">
                <div className="fila-canal-nombre">
                  {t(`metricas.canal_${canal}`, { defaultValue: canal })}
                </div>
                <div className="fila-canal-pista">
                  <div className="fila-canal-relleno" style={{ width: `${(100 * n) / totalCanales}%` }} />
                </div>
                <div className="fila-canal-cifra">
                  {n} · {Math.round((100 * n) / totalCanales)}%
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Top de incidencias recurrentes: dice qué arreglar de raíz */}
        <h3 className="rotulo-seccion" style={{ margin: '28px 0 14px' }}>
          {t('metricas.top_categorias')}
        </h3>
        {categorias.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{t('metricas.sin_datos')}</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
            {categorias.map((c) => (
              <div key={c.categoria} className="chip-dato" style={{
                padding: '10px 16px',
                background: 'var(--bg-tertiary)',
                color: 'var(--text-primary)'
              }}>
                <strong>{c.total}</strong>{' '}
                {t(`new_ticket.category_${c.categoria}`, { defaultValue: c.categoria })}
              </div>
            ))}
          </div>
        )}
      </Seccion>

      {/* Lo que el tiempo de resolución no cuenta: rápido no es lo mismo
          que bien resuelto. La contestan quienes reportaron. */}
      {satisfaccion && (
        <Seccion icono={<Star size={20} color="var(--accent-primary)" />} titulo={t('encuesta.metricas_titulo')}>
          <div className="rejilla-metricas">
            <Tarjeta etiqueta={t('encuesta.promedio')} valor={satisfaccion.promedio} sufijo=" / 5" />
            <Tarjeta etiqueta={t('encuesta.respuestas')} valor={satisfaccion.respuestas} />
            <Tarjeta
              etiqueta={t('encuesta.tasa_respuesta')}
              valor={satisfaccion.tasa_respuesta}
              sufijo="%"
              ayuda={t('encuesta.tasa_respuesta_ayuda')}
            />
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
                    <div className="fila-canal-cifra">{cuantos}</div>
                  </div>
                );
              })}
            </div>
          )}
        </Seccion>
      )}

      <Seccion icono={<Database size={20} color="var(--accent-primary)" />} titulo={t('metricas.kb')}>
        <div className="rejilla-metricas">
          <Tarjeta
            etiqueta={t('metricas.utilidad')}
            valor={kb.tasa_utilidad}
            sufijo="%"
            ayuda={t('metricas.utilidad_ayuda')}
          />
          <Tarjeta etiqueta={t('metricas.entradas')} valor={kb.entradas_kb} />
          <Tarjeta etiqueta={t('metricas.mostradas_semana')} valor={kb.sugerencias_mostradas_semana} />
          <Tarjeta etiqueta={t('metricas.resueltas_kb')} valor={kb.incidencias_resueltas_por_kb} />
          <Tarjeta
            etiqueta={t('metricas.umbral')}
            valor={kb.umbral_actual}
            ayuda={t('metricas.umbral_ayuda')}
          />
          <Tarjeta
            etiqueta={t('metricas.pendientes')}
            valor={kb.tickets_pendientes_indexar}
            ayuda={t('metricas.pendientes_ayuda')}
          />
        </div>
      </Seccion>

      <Seccion icono={<MessageCircle size={20} color="var(--accent-primary)" />} titulo={t('metricas.chatbot')}>
        <div className="rejilla-metricas">
          <Tarjeta etiqueta={t('metricas.sesiones')} valor={chatbot.sesiones_iniciadas} />
          <Tarjeta
            etiqueta={t('metricas.termino_ticket')}
            valor={chatbot.porcentaje_termino_en_ticket}
            sufijo="%"
          />
          <Tarjeta
            etiqueta={t('metricas.precision')}
            valor={chatbot.precision_clasificacion}
            sufijo="%"
            ayuda={t('metricas.precision_ayuda', { count: chatbot.clasificaciones_comparables })}
          />
          <Tarjeta etiqueta={t('metricas.umbral_confianza')} valor={chatbot.umbral_confianza} />
        </div>
      </Seccion>

      <Seccion icono={<Cpu size={20} color="var(--accent-primary)" />} titulo={t('metricas.ollama')}>
        {!ollama.disponible && <Aviso texto={t('metricas.ollama_caido')} />}
        <div className="rejilla-metricas">
          <Tarjeta
            etiqueta={t('metricas.estado')}
            valor={ollama.disponible ? t('metricas.en_linea') : t('metricas.fuera_linea')}
          />
          <Tarjeta etiqueta={t('metricas.lat_embedding')} valor={ollama.latencias_ms.embedding} sufijo=" ms" />
          <Tarjeta etiqueta={t('metricas.lat_normalizacion')} valor={ollama.latencias_ms.normalizacion} sufijo=" ms" />
          <Tarjeta etiqueta={t('metricas.lat_clasificacion')} valor={ollama.latencias_ms.clasificacion} sufijo=" ms" />
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '14px' }}>
          {t('metricas.latencia_nota')}
        </div>
      </Seccion>
    </div>
  );
};

export default Metricas;
