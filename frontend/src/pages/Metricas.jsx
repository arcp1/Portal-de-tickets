import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { TrendingUp, Database, MessageCircle, Cpu, AlertTriangle } from 'lucide-react';

/**
 * Tablero del admin.
 *
 * Regla de lectura: cuando una tasa vale `null` es que todavía no hay datos
 * para calcularla, y se muestra "—", no un 0%. Un cero falso se lee como mal
 * resultado y lleva a decisiones equivocadas.
 */

const Tarjeta = ({ etiqueta, valor, sufijo = '', ayuda }) => (
  <div style={{
    padding: '20px',
    background: 'var(--bg-secondary)',
    borderRadius: 'var(--radius-md)',
    border: '1px solid var(--border-color)',
    boxShadow: 'var(--shadow-sm)'
  }}>
    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: '500', marginBottom: '8px' }}>
      {etiqueta}
    </div>
    <div style={{ fontSize: '1.9rem', fontWeight: '700', color: 'var(--text-primary)', lineHeight: 1.1 }}>
      {valor === null || valor === undefined ? '—' : `${valor}${sufijo}`}
    </div>
    {ayuda && (
      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px', lineHeight: 1.4 }}>
        {ayuda}
      </div>
    )}
  </div>
);

const Seccion = ({ icono, titulo, children }) => (
  <div className="apple-card" style={{ padding: '28px', marginBottom: '24px' }}>
    <h2 style={{ fontSize: '1.2rem', fontWeight: '700', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-primary)' }}>
      {icono}
      {titulo}
    </h2>
    {children}
  </div>
);

const rejilla = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
  gap: '16px'
};

const Metricas = () => {
  const { t } = useTranslation();
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.get('/metricas')
      .then((res) => setDatos(res.data))
      .catch(() => setError(true))
      .finally(() => setCargando(false));
  }, []);

  if (cargando) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('metricas.cargando')}</div>;
  }
  if (error || !datos) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('metricas.error')}</div>;
  }

  const { tickets, base_conocimiento: kb, chatbot, ollama } = datos;
  const canales = Object.entries(tickets.por_canal || {});
  const totalCanales = canales.reduce((suma, [, n]) => suma + n, 0);

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1100px' }}>
      <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-primary)' }}>
        {t('metricas.title')}
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '32px' }}>
        {t('metricas.subtitle', { dias: tickets.periodo_dias })}
      </p>

      <Seccion icono={<TrendingUp size={20} color="var(--accent-primary)" />} titulo={t('metricas.tickets')}>
        <div style={rejilla}>
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
        </div>

        {/* Distribución por canal: la métrica más importante de la spec */}
        <h3 style={{ fontSize: '0.95rem', fontWeight: '600', margin: '28px 0 14px', color: 'var(--text-primary)' }}>
          {t('metricas.por_canal')}
        </h3>
        {totalCanales === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{t('metricas.sin_datos')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {canales.sort((a, b) => b[1] - a[1]).map(([canal, n]) => (
              <div key={canal} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ width: '110px', fontSize: '0.88rem', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
                  {t(`metricas.canal_${canal}`, { defaultValue: canal })}
                </div>
                <div style={{ flex: 1, height: '10px', background: 'var(--bg-tertiary)', borderRadius: '5px', overflow: 'hidden' }}>
                  <div style={{ width: `${(100 * n) / totalCanales}%`, height: '100%', background: 'var(--accent-primary)' }} />
                </div>
                <div style={{ width: '72px', textAlign: 'right', fontSize: '0.88rem', color: 'var(--text-primary)', fontWeight: '600' }}>
                  {n} · {Math.round((100 * n) / totalCanales)}%
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Top de incidencias recurrentes: dice qué arreglar de raíz */}
        <h3 style={{ fontSize: '0.95rem', fontWeight: '600', margin: '28px 0 14px', color: 'var(--text-primary)' }}>
          {t('metricas.top_categorias')}
        </h3>
        {tickets.por_categoria.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{t('metricas.sin_datos')}</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
            {tickets.por_categoria.map((c) => (
              <div key={c.categoria} style={{
                padding: '10px 16px',
                background: 'var(--bg-tertiary)',
                borderRadius: 'var(--radius-md)',
                fontSize: '0.9rem',
                color: 'var(--text-primary)'
              }}>
                <strong>{c.total}</strong>{' '}
                {t(`new_ticket.category_${c.categoria}`, { defaultValue: c.categoria })}
              </div>
            ))}
          </div>
        )}
      </Seccion>

      <Seccion icono={<Database size={20} color="var(--accent-primary)" />} titulo={t('metricas.kb')}>
        <div style={rejilla}>
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
        <div style={rejilla}>
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
            ayuda={t('metricas.precision_ayuda', { n: chatbot.clasificaciones_comparables })}
          />
          <Tarjeta etiqueta={t('metricas.umbral_confianza')} valor={chatbot.umbral_confianza} />
        </div>
      </Seccion>

      <Seccion icono={<Cpu size={20} color="var(--accent-primary)" />} titulo={t('metricas.ollama')}>
        {!ollama.disponible && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '14px 18px',
            background: 'var(--status-espera-proveedor-bg)',
            color: 'var(--status-espera-proveedor-text)',
            borderRadius: 'var(--radius-md)',
            marginBottom: '18px',
            fontSize: '0.9rem'
          }}>
            <AlertTriangle size={18} />
            {t('metricas.ollama_caido')}
          </div>
        )}
        <div style={rejilla}>
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
