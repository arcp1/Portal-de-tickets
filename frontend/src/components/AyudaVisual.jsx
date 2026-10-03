import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import ReconocimientoVisual, { PasosVisuales } from './ReconocimientoVisual';
import { Camera, ThumbsUp, ThumbsDown } from 'lucide-react';

/**
 * El catálogo visual dentro del formulario de ticket.
 *
 * **Por qué también aquí y no sólo en el chat.** Mucha gente no abre el chat:
 * va derecha al formulario y escribe "la copia sale borrosa" en la caja de
 * descripción. Si las fotos sólo viven en el chat, a esa persona el portal le
 * enseña sugerencias de texto sobre tres defectos que se describen igual y la
 * manda a levantar un ticket. El sitio donde alguien cuenta su problema es el
 * sitio donde hay que preguntarle si se ve así.
 *
 * Vive junto a `SugerenciasKB` y `RespuestaAsistente` y se comporta como
 * ellos: reacciona a lo que se escribe, se calla cuando no hay nada que
 * aportar y **nunca estorba al botón de enviar**.
 *
 * El ciclo completo es de tres pasos, y el tercero es el que suele faltar:
 *
 *   1. ¿Se ve así?  -> las fotos del catálogo
 *   2. Es ésta      -> la solución atada a esa foto, con sus pasos señalados
 *   3. ¿Se arregló? -> **sí** cierra la incidencia sin ticket; **no** deja
 *      dicho en la descripción qué se probó ya, para que TI no lo repita
 */
const AyudaVisual = ({ texto, categoria, onResuelto, onNoResolvio }) => {
  const { t } = useTranslation();

  const [fichas, setFichas] = useState([]);
  const [elegida, setElegida] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  // Una vez que la persona dijo que no era ninguna, o que no se arregló, este
  // bloque se calla para el resto del formulario: seguir ofreciendo fotos
  // mientras alguien termina de escribir su ticket es puro estorbo.
  const [callado, setCallado] = useState(false);

  useEffect(() => {
    if (callado || elegida) return;
    if (!texto || texto.trim().length < 15) {
      setFichas([]);
      return;
    }

    let cancelado = false;
    const temporizador = setTimeout(async () => {
      try {
        // Mismo tope que el API (2000): más largo, la ayuda no salía.
        const res = await api.post('/visual/reconocer', { texto: texto.slice(0, 2000), categoria });
        if (cancelado) return;
        // Se obliga a que sea una lista: un 200 con el cuerpo equivocado no lo
        // ve ningún `catch` y tumbaría el formulario entero al recorrerla.
        const candidatas = res.data?.activado ? res.data?.candidatas : [];
        setFichas(Array.isArray(candidatas) ? candidatas : []);
      } catch {
        // Un fallo aquí no interrumpe nada: el formulario sigue igual.
        if (!cancelado) setFichas([]);
      }
    }, 800);

    return () => {
      cancelado = true;
      clearTimeout(temporizador);
    };
  }, [texto, categoria, callado, elegida]);

  const elegir = async (ficha) => {
    setTrabajando(true);
    try {
      const res = await api.post('/visual/confirmar', { ficha_id: ficha.ficha_id });
      setElegida({ ...ficha, ...res.data });
      setFichas([]);
    } catch {
      setCallado(true);
    } finally {
      setTrabajando(false);
    }
  };

  const ninguna = async () => {
    setCallado(true);
    setFichas([]);
    try {
      await api.post('/visual/descartar', {
        ficha_ids: fichas.map((f) => f.ficha_id),
        consulta: texto
      });
    } catch {
      // Que no se pueda anotar es una métrica perdida, no un problema del
      // usuario: el formulario sigue igual.
    }
  };

  const desenlace = async (resuelto) => {
    const ficha = elegida;
    setTrabajando(true);
    try {
      await api.post('/visual/resultado', {
        ficha_id: ficha.ficha_id, resuelto, consulta: texto
      });
    } catch {
      /* igual que arriba */
    } finally {
      setTrabajando(false);
    }

    if (resuelto) {
      onResuelto?.(ficha);
      return;
    }
    setElegida(null);
    setCallado(true);
    onNoResolvio?.(ficha);
  };

  if (callado && !elegida) return null;
  if (!fichas.length && !elegida) return null;

  return (
    <div className="animate-scale-in" style={{
      margin: '20px 0',
      padding: '18px 20px',
      background: 'var(--bg-tertiary)',
      borderRadius: 'var(--radius-lg)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '9px', marginBottom: '12px' }}>
        <Camera size={18} color="var(--accent-primary)" />
        <strong style={{ fontSize: '0.95rem', color: 'var(--text-primary)' }}>
          {elegida ? elegida.titulo : t('visual.se_ve_asi')}
        </strong>
      </div>

      {!elegida && (
        <ReconocimientoVisual
          fichas={fichas}
          trabajando={trabajando}
          onElegir={elegir}
          onNinguna={ninguna}
        />
      )}

      {elegida && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <p style={{
            margin: 0, fontSize: '0.93rem', lineHeight: 1.55,
            color: 'var(--text-primary)', whiteSpace: 'pre-wrap'
          }}>
            {elegida.solucion}
          </p>

          {elegida.pasos?.length > 0 && (
            <PasosVisuales fichaId={elegida.ficha_id} pasos={elegida.pasos} />
          )}

          {/* Lo que ya se probó y no era, siempre a la vista y al final: es lo
              que evita que alguien repita media hora de trabajo ajeno. */}
          {elegida.descartado && (
            <p style={{
              margin: 0, fontSize: '0.87rem', lineHeight: 1.5,
              color: 'var(--status-espera-proveedor-text)'
            }}>
              {t('visual.ya_se_probo', { texto: elegida.descartado })}
            </p>
          )}

          <div style={{
            display: 'flex', gap: '10px', flexWrap: 'wrap',
            paddingTop: '12px', borderTop: '1px solid var(--border-color)'
          }}>
            <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', alignSelf: 'center' }}>
              {t('visual.se_arreglo')}
            </span>
            <button type="button" className="btn-secondary btn-secondary--exito"
              onClick={() => desenlace(true)} disabled={trabajando}
              style={{ padding: '8px 14px', fontSize: '0.85rem' }}>
              <ThumbsUp size={14} /> {t('visual.si_se_arreglo')}
            </button>
            <button type="button" className="btn-secondary"
              onClick={() => desenlace(false)} disabled={trabajando}
              style={{ padding: '8px 14px', fontSize: '0.85rem' }}>
              <ThumbsDown size={14} /> {t('visual.sigue_igual')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// `memo`: ver `textoParaAyudas` en pages/NewTicket.jsx.
export default React.memo(AyudaVisual);
