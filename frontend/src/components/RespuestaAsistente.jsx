import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { Sparkles, FileText, Ticket, XCircle, Ban, Cpu, Cloud } from 'lucide-react';

/**
 * La respuesta del asistente, siempre con su procedencia a la vista.
 *
 * Dos decisiones de diseño que importan más que el estilo:
 *
 * 1. **Las fuentes se enseñan junto a la respuesta, no escondidas.** Quien lee
 *    tiene que poder abrir el ticket original y comprobar. Una respuesta sin
 *    fuente no se puede verificar, y en una planta eso no basta.
 *
 * 2. **Cuando no hay información se dice, y se dice claro.** No se rellena con
 *    algo parecido ni se deja el hueco en blanco: se avisa que de eso no hay
 *    nada escrito y que conviene levantar el ticket. Es la respuesta correcta
 *    más seguido de lo que parece.
 */
const RespuestaAsistente = ({ texto, categoria, minimo = 20 }) => {
  const { t } = useTranslation();
  const [datos, setDatos] = useState(null);
  const [consultando, setConsultando] = useState(false);

  useEffect(() => {
    if (!texto || texto.trim().length < minimo) {
      setDatos(null);
      return;
    }

    let cancelado = false;
    // Se espera a que deje de escribir: cada consulta cuesta una búsqueda
    // vectorial y, a veces, una llamada al modelo.
    const temporizador = setTimeout(async () => {
      setConsultando(true);
      try {
        const res = await api.post('/asistente/preguntar', { texto, categoria });
        if (!cancelado) setDatos(res.data);
      } catch {
        // Un fallo aquí no interrumpe el formulario. Simplemente no hay ayuda.
        if (!cancelado) setDatos(null);
      } finally {
        if (!cancelado) setConsultando(false);
      }
    }, 1200);

    return () => { cancelado = true; clearTimeout(temporizador); };
  }, [texto, categoria, minimo]);

  if (consultando) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: '9px', padding: '12px 14px',
        fontSize: '0.86rem', color: 'var(--text-muted)'
      }}>
        <Sparkles size={15} /> {t('asistente.buscando')}
      </div>
    );
  }

  if (!datos) return null;

  // Nada parecido en el conocimiento de la planta. Se dice tal cual.
  if (datos.origen === 'sin_fundamento') {
    return (
      <div className="animate-scale-in" style={{
        display: 'flex', alignItems: 'flex-start', gap: '10px',
        background: 'var(--bg-tertiary)', padding: '14px 16px',
        borderRadius: 'var(--radius-md)', marginTop: '14px',
        fontSize: '0.88rem', lineHeight: 1.55, color: 'var(--text-secondary)'
      }}>
        <XCircle size={17} style={{ flexShrink: 0, marginTop: '1px' }} />
        <div>
          <strong style={{ color: 'var(--text-primary)' }}>{t('asistente.sin_datos')}</strong>
          <div style={{ marginTop: '3px' }}>{t('asistente.sin_datos_detalle')}</div>
        </div>
      </div>
    );
  }

  const hayFuentes = datos.fuentes?.length > 0;
  if (!datos.respuesta && !hayFuentes) return null;

  return (
    <div className="apple-card animate-scale-in" style={{
      padding: '16px 18px', marginTop: '14px',
      borderLeft: '3px solid var(--accent-primary)'
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px',
        fontSize: '0.78rem', fontWeight: 600, color: 'var(--accent-primary)'
      }}>
        <Sparkles size={15} />
        {datos.respuesta ? t('asistente.titulo') : t('asistente.titulo_extractos')}
        <Origen origen={datos.origen} t={t} />
      </div>

      {datos.respuesta && (
        <div style={{
          fontSize: '0.92rem', lineHeight: 1.6, color: 'var(--text-primary)',
          whiteSpace: 'pre-wrap', marginBottom: hayFuentes ? '14px' : 0
        }}>
          {datos.respuesta}
        </div>
      )}

      {hayFuentes && (
        <div>
          <div style={{
            fontSize: '0.74rem', fontWeight: 600, letterSpacing: '0.04em',
            textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '7px'
          }}>
            {t('asistente.fuentes')}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {datos.fuentes.map((f, i) => <Fuente key={i} fuente={f} numero={i + 1} t={t} />)}
          </div>
        </div>
      )}
    </div>
  );
};

/** De dónde salió la redacción. Sirve para saber qué se está gastando. */
const Origen = ({ origen, t }) => {
  if (origen === 'gemini') {
    return (
      <span title={t('asistente.origen_gemini')} style={estiloOrigen}>
        <Cloud size={11} /> Gemini
      </span>
    );
  }
  if (origen === 'ollama') {
    return (
      <span title={t('asistente.origen_ollama')} style={estiloOrigen}>
        <Cpu size={11} /> {t('asistente.local')}
      </span>
    );
  }
  return null;
};

const estiloOrigen = {
  display: 'inline-flex', alignItems: 'center', gap: '4px',
  marginLeft: 'auto', fontSize: '0.7rem', fontWeight: 500,
  padding: '2px 8px', borderRadius: 'var(--radius-full)',
  background: 'var(--bg-tertiary)', color: 'var(--text-secondary)'
};

const Fuente = ({ fuente, numero, t }) => {
  const esTicket = fuente.fuente === 'ticket';
  const Icono = esTicket ? Ticket : FileText;

  return (
    <div style={{
      display: 'flex', gap: '9px', padding: '10px 12px',
      background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)',
      fontSize: '0.84rem'
    }}>
      <span style={{
        fontFamily: 'monospace', fontWeight: 600, color: 'var(--accent-primary)',
        flexShrink: 0
      }}>
        [{numero}]
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: '6px',
          color: 'var(--text-primary)', fontWeight: 600, marginBottom: '2px'
        }}>
          <Icono size={13} style={{ flexShrink: 0, color: 'var(--text-muted)' }} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{fuente.titulo}</span>
        </div>
        <div style={{ color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          {fuente.texto?.length > 240 ? fuente.texto.slice(0, 240) + '…' : fuente.texto}
        </div>

        {/* Lo que ya se probó y no era: le ahorra al técnico repetirlo. */}
        {fuente.descartado && (
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: '6px', marginTop: '7px',
            padding: '7px 9px', borderRadius: 'var(--radius-sm)',
            background: 'var(--status-espera-proveedor-bg)',
            color: 'var(--status-espera-proveedor-text)', fontSize: '0.8rem', lineHeight: 1.45
          }}>
            <Ban size={13} style={{ flexShrink: 0, marginTop: '1px' }} />
            <span><strong>{t('asistente.descartado')}</strong> {fuente.descartado}</span>
          </div>
        )}

        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '5px' }}>
          {esTicket ? t('asistente.de_ticket') : t('asistente.de_documentacion')}
          {' · '}{Math.round(fuente.similitud * 100)}% {t('asistente.parecido')}
        </div>
      </div>
    </div>
  );
};

export default RespuestaAsistente;
