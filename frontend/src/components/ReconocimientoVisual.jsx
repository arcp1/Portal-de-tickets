import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import ImagenApi from './ImagenApi';
import { ImageOff, Check } from 'lucide-react';

/**
 * "¿Se ve así su problema?"
 *
 * **Es la única parte del portal que pregunta en vez de contestar**, y esa
 * diferencia es el motivo de que exista.
 *
 * Una copia borrosa, una con sombra doble y una con una raya fina se escriben
 * las tres igual —"sale mal"— y se arreglan de tres maneras distintas. Ningún
 * parecido de texto separa eso; quien tiene la hoja en la mano lo separa de una
 * mirada. Así que el portal enseña las fotos que TI documentó y deja que la
 * persona señale la suya; lo que se entrega después es la solución atada a
 * **esa** foto, no a la que el buscador puso primera.
 *
 * Por eso el botón de "ninguna se parece" pesa lo mismo que los otros y está
 * siempre a la vista: si estas tres no son, seguir insistiendo con ellas es
 * peor que no haberlas enseñado.
 */
const ReconocimientoVisual = ({ fichas = [], onElegir, onNinguna, trabajando = false }) => {
  const { t } = useTranslation();
  // La foto que se está mirando de cerca. Ampliar en el sitio evita un modal
  // encima del chat, que en un panel de 380 px tapa la conversación entera.
  const [ampliada, setAmpliada] = useState(null);

  if (!fichas.length) return null;

  return (
    <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {fichas.map((f) => (
        <div
          key={f.ficha_id}
          className="apple-card"
          style={{ padding: 0, overflow: 'hidden', border: '1px solid var(--border-color)' }}
        >
          {f.imagen_id && (
            <ImagenApi
              ruta={`/visual/fichas/${f.ficha_id}/imagenes/${f.imagen_id}`}
              alt={f.titulo}
              ancho="100%"
              alto={ampliada === f.ficha_id ? 'auto' : '124px'}
              ajuste={ampliada === f.ficha_id ? 'contain' : 'cover'}
              onClick={() => setAmpliada(ampliada === f.ficha_id ? null : f.ficha_id)}
            />
          )}
          <div style={{ padding: '10px 12px 12px' }}>
            <div style={{
              fontWeight: '600', fontSize: '0.9rem',
              color: 'var(--text-primary)', lineHeight: 1.35
            }}>
              {f.titulo}
            </div>
            {f.pie && (
              <div style={{
                fontSize: '0.8rem', color: 'var(--text-secondary)',
                marginTop: '3px', lineHeight: 1.4
              }}>
                {f.pie}
              </div>
            )}
            <button
              type="button"
              className="btn-secondary btn-secondary--exito"
              onClick={() => onElegir(f)}
              disabled={trabajando}
              style={{ marginTop: '10px', width: '100%', justifyContent: 'center', padding: '8px', fontSize: '0.85rem' }}
            >
              <Check size={15} /> {t('visual.es_este')}
            </button>
          </div>
        </div>
      ))}

      <button
        type="button"
        className="btn-secondary"
        onClick={onNinguna}
        disabled={trabajando}
        style={{ justifyContent: 'center', padding: '9px', fontSize: '0.85rem' }}
      >
        <ImageOff size={15} /> {t('visual.ninguna')}
      </button>
    </div>
  );
};

/**
 * Los pasos que no se pueden explicar por escrito.
 *
 * Hay problemas que se arreglan con dos clics, y contar dónde están esos dos
 * clics cuesta un párrafo que nadie sigue: "abra propiedades, pestaña
 * avanzado, el tercer bloque, la casilla de abajo". Señalado sobre la captura,
 * cuesta una mirada. Cuando TI subió esas capturas, van aquí.
 */
export const PasosVisuales = ({ fichaId, pasos = [] }) => {
  const { t } = useTranslation();
  if (!pasos.length) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <div style={{ fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-secondary)' }}>
        {t('visual.donde_picar')}
      </div>
      {pasos.map((paso, i) => (
        <div key={paso.imagen_id}>
          <div style={{
            display: 'flex', alignItems: 'baseline', gap: '7px',
            fontSize: '0.85rem', color: 'var(--text-primary)', marginBottom: '6px', lineHeight: 1.4
          }}>
            <span style={{ fontWeight: '700', color: 'var(--accent-primary)' }}>{i + 1}.</span>
            <span>{paso.pie || t('visual.paso_sin_pie')}</span>
          </div>
          <ImagenApi
            ruta={`/visual/fichas/${fichaId}/imagenes/${paso.imagen_id}`}
            alt={paso.pie || t('visual.paso_sin_pie')}
            ancho="100%"
            alto="auto"
            ajuste="contain"
            estilo={{ borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}
          />
        </div>
      ))}
    </div>
  );
};

export default ReconocimientoVisual;
