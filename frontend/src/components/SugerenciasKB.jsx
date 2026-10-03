import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { avisar, mensajeDeError } from '../lib/avisos';
import { Lightbulb, ThumbsUp, ThumbsDown, Check } from 'lucide-react';

/**
 * Incidencias parecidas ya resueltas, con el botón de "¿te sirvió?".
 *
 * Degradación limpia: si Ollama no está disponible el backend responde
 * `degradado: true` y este componente no pinta nada. El usuario nunca ve un
 * error de IA, solo deja de aparecer la ayuda.
 */
const SugerenciasKB = ({ texto, categoria, sitioId, ticketId = null, onResuelto }) => {
  const { t } = useTranslation();

  const [sugerencias, setSugerencias] = useState([]);
  const [respuestas, setRespuestas] = useState({});
  const [buscando, setBuscando] = useState(false);

  useEffect(() => {
    // Sin texto suficiente no vale la pena consultar.
    if (!texto || texto.trim().length < 15 || !sitioId) {
      setSugerencias([]);
      return;
    }

    let cancelado = false;
    // Se espera a que el usuario deje de escribir antes de consultar.
    const temporizador = setTimeout(async () => {
      setBuscando(true);
      try {
        const res = await api.post('/ia/similares', {
          // Mismo tope que el API (5000): más largo, no salía ninguna sugerencia.
          texto: texto.slice(0, 5000),
          categoria,
          sitio_id: sitioId,
          ticket_id: ticketId
        });
        if (!cancelado) {
          // **Se obliga a que sea una lista, pase lo que pase.**
          //
          // El `catch` de abajo cubre los fallos de red y los códigos de error,
          // pero no una respuesta **200 con el cuerpo equivocado** — un proxy
          // que devuelve su propia página, un despliegue a medias donde el
          // backend todavía no tiene este endpoint, un cambio en su forma.
          //
          // Sin esta línea, `resultados` llegaba `undefined`, el estado se
          // quedaba `undefined` y el `sugerencias.length` de más abajo reventaba
          // **tumbando el formulario de tickets entero**: la pantalla se
          // sustituye por "Algo se rompió en esta pantalla" y ya no se puede
          // levantar el ticket. Es la pantalla más importante del portal y
          // caía por una sugerencia que sobra.
          //
          // Reproducible con `python3 scripts/vista-previa.py`: su API simulada
          // no implementa este endpoint y devuelve un objeto vacío, que es
          // exactamente el caso.
          const lista = res.data?.degradado ? [] : res.data?.resultados;
          setSugerencias(Array.isArray(lista) ? lista : []);
        }
      } catch (err) {
        // Un fallo aquí no interrumpe nada: el formulario sigue igual.
        if (!cancelado) setSugerencias([]);
      } finally {
        if (!cancelado) setBuscando(false);
      }
    }, 800);

    return () => {
      cancelado = true;
      clearTimeout(temporizador);
    };
  }, [texto, categoria, sitioId, ticketId]);

  const enviarFeedback = async (sugerencia, fueUtil) => {
    setRespuestas((previas) => ({ ...previas, [sugerencia.sugerencia_id]: fueUtil }));
    try {
      await api.post('/kb/feedback', { sugerencia_id: sugerencia.sugerencia_id, fue_util: fueUtil });
    } catch (err) {
      // Antes solo iba a la consola y la tarjeta seguía diciendo "Gracias.
      // Registrado": un voto perdido que se daba por contado. Se devuelven
      // los botones para poder repetirlo, y se dice. No se frena nada más:
      // si le sirvió, su problema sigue resuelto.
      setRespuestas((previas) => {
        const { [sugerencia.sugerencia_id]: _descartada, ...resto } = previas;
        return resto;
      });
      avisar(mensajeDeError(err, t('kb.error_feedback')), { tono: 'atencion' });
    }
    // Se pasa la sugerencia completa: su contenido es lo que queda como
    // solución del ticket auto-resuelto, y sin eso la deflección no se mide.
    if (fueUtil && onResuelto) onResuelto(sugerencia);
  };

  if (buscando && sugerencias.length === 0) return null;
  if (sugerencias.length === 0) return null;

  return (
    <div
      className="animate-fade-in"
      style={{
        padding: '24px',
        background: 'var(--bg-tertiary)',
        borderRadius: 'var(--radius-lg)',
        marginBottom: '24px'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', color: 'var(--accent-primary)' }}>
        <Lightbulb size={20} />
        <span style={{ fontWeight: '600', fontSize: '0.95rem' }}>{t('kb.titulo')}</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {sugerencias.map((s) => {
          const respuesta = respuestas[s.sugerencia_id];
          const yaRespondio = respuesta !== undefined;

          return (
            <div
              key={s.sugerencia_id}
              style={{
                padding: '18px',
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-color)',
                boxShadow: 'var(--shadow-sm)'
              }}
            >
              <div style={{ fontWeight: '600', color: 'var(--text-primary)', marginBottom: '8px' }}>
                {s.titulo}
              </div>
              <div style={{ fontSize: '0.95rem', color: 'var(--text-secondary)', lineHeight: '1.5', whiteSpace: 'pre-line' }}>
                {s.contenido}
              </div>

              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '12px',
                  marginTop: '16px',
                  paddingTop: '14px',
                  borderTop: '1px solid var(--border-color)',
                  flexWrap: 'wrap'
                }}
              >
                {yaRespondio ? (
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.9rem', color: 'var(--text-secondary)', fontWeight: '500' }}>
                    <Check size={16} color="var(--status-resuelto-text)" />
                    {respuesta ? t('kb.gracias_util') : t('kb.gracias_no_util')}
                  </span>
                ) : (
                  <>
                    <span style={{ fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: '500' }}>
                      {t('kb.te_sirvio')}
                    </span>
                    <div style={{ display: 'flex', gap: '10px' }}>
                      <button
                        type="button"
                        onClick={() => enviarFeedback(s, true)}
                        className="btn-secondary btn-secondary--exito"
                        style={{ padding: '8px 16px', fontSize: '0.9rem' }}
                      >
                        <ThumbsUp size={16} />
                        {t('kb.si_sirvio')}
                      </button>
                      <button
                        type="button"
                        onClick={() => enviarFeedback(s, false)}
                        className="btn-secondary"
                        style={{ padding: '8px 16px', fontSize: '0.9rem' }}
                      >
                        <ThumbsDown size={16} />
                        {t('kb.no_sirvio')}
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// `memo`: ver `textoParaAyudas` en pages/NewTicket.jsx.
export default React.memo(SugerenciasKB);
