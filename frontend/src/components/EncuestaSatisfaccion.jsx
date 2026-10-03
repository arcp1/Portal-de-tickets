import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Star, Send } from 'lucide-react';
import api from '../api/client';
import Aviso from './Aviso';
import { avisar, mensajeDeError } from '../lib/avisos';

/** Los canales en que no hubo atención de TI: no se califican. Los mismos que el backend. */
const AUTOSERVICIO = ['checklist', 'kb', 'ia', 'visual'];
const CIERRE = ['resuelto', 'cerrado'];

/**
 * La encuesta al quedar resuelto: de 1 a 5 estrellas y, si quiere, por qué.
 *
 * Solo la contesta quien reportó, una vez, y solo si lo resolvió alguien de
 * TI. Ya contestada, la ven los dos —quien reportó y TI— en solo lectura.
 *
 * Las estrellas son un grupo de radios de verdad: se eligen con las flechas
 * y el lector de pantalla dice "3 de 5", no "botón, botón, botón".
 */
export default function EncuestaSatisfaccion({ ticket, usuario, onCalificado }) {
  const { t } = useTranslation();
  const [estrellas, setEstrellas] = useState(0);
  const [encima, setEncima] = useState(0);
  const [comentario, setComentario] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState('');

  const esDueno = ticket.usuario_id === usuario.id;
  const calificado = ticket.satisfaccion != null;
  const sePuede = esDueno && CIERRE.includes(ticket.estado)
    && !AUTOSERVICIO.includes(ticket.canal_resolucion);

  if (!calificado && !sePuede) return null;

  if (calificado) {
    return (
      <section className="encuesta encuesta--hecha" aria-label={t('encuesta.titulo')}>
        <h3 className="encuesta-titulo">
          {esDueno ? t('encuesta.su_calificacion') : t('encuesta.calificacion_de_quien_reporto')}
        </h3>
        <div className="estrellas estrellas--fijas" role="img"
          aria-label={t('encuesta.n_de_5', { n: ticket.satisfaccion })}>
          {[1, 2, 3, 4, 5].map((n) => (
            <Star key={n} size={24} aria-hidden="true"
              className={n <= ticket.satisfaccion ? 'estrella estrella--llena' : 'estrella'} />
          ))}
          <span className="estrellas-texto">{t(`encuesta.nivel_${ticket.satisfaccion}`)}</span>
        </div>
        {ticket.satisfaccion_comentario && (
          <blockquote className="encuesta-comentario">{ticket.satisfaccion_comentario}</blockquote>
        )}
      </section>
    );
  }

  const enviar = async (e) => {
    e.preventDefault();
    if (!estrellas || enviando) return;
    setEnviando(true);
    setAviso('');
    try {
      const res = await api.post(`/tickets/${ticket.id}/satisfaccion`, {
        estrellas, comentario: comentario.trim() || null,
      });
      avisar(t('encuesta.gracias'), { tono: 'exito' });
      onCalificado?.(res.data);
    } catch (err) {
      setAviso(mensajeDeError(err, t('encuesta.error')));
    } finally {
      setEnviando(false);
    }
  };

  const mostrada = encima || estrellas;

  return (
    <form className="encuesta" onSubmit={enviar} aria-label={t('encuesta.titulo')}>
      <h3 className="encuesta-titulo">{t('encuesta.pregunta')}</h3>
      <div
        className="estrellas"
        role="radiogroup"
        aria-label={t('encuesta.titulo')}
        onMouseLeave={() => setEncima(0)}
      >
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className="estrella-opcion" onMouseEnter={() => setEncima(n)}>
            <input
              type="radio"
              name={`estrellas-${ticket.id}`}
              value={n}
              checked={estrellas === n}
              onChange={() => setEstrellas(n)}
              className="solo-lectores"
            />
            <Star size={30} aria-hidden="true"
              className={n <= mostrada ? 'estrella estrella--llena' : 'estrella'} />
            <span className="solo-lectores">{t('encuesta.n_de_5', { n })}</span>
          </label>
        ))}
        <span className="estrellas-texto" aria-live="polite">
          {mostrada ? t(`encuesta.nivel_${mostrada}`) : t('encuesta.elija')}
        </span>
      </div>
      {estrellas > 0 && (
        <textarea
          className="form-textarea animate-fade-in"
          rows={2}
          maxLength={1000}
          placeholder={estrellas <= 2 ? t('encuesta.que_fallo') : t('encuesta.comentario_opcional')}
          value={comentario}
          onChange={(e) => setComentario(e.target.value)}
          aria-label={t('encuesta.comentario_opcional')}
        />
      )}
      <Aviso texto={aviso} />
      <button type="submit" className="btn-primary" disabled={!estrellas || enviando}>
        <Send size={16} /> {enviando ? t('encuesta.enviando') : t('encuesta.enviar')}
      </button>
    </form>
  );
}
