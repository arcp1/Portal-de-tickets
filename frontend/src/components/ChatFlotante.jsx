import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { MessageCircle, X, Send, Headset } from 'lucide-react';

/**
 * Chatbot flotante: entrada alternativa al formulario, no un reemplazo.
 *
 * El chat solo sustituye el paso de elegir categoría. En cuanto hay una
 * categoría, se va al formulario de siempre con el flujo de siempre.
 *
 * Si Ollama no está disponible el widget no se dibuja: queda el formulario con
 * dropdown, que nunca deja de funcionar.
 */
const ChatFlotante = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [disponible, setDisponible] = useState(false);
  const [abierto, setAbierto] = useState(false);
  const [mensajes, setMensajes] = useState([]);
  const [borrador, setBorrador] = useState('');
  const [sesionId, setSesionId] = useState(null);
  const [categorias, setCategorias] = useState([]);
  const [enviando, setEnviando] = useState(false);

  const finDelHilo = useRef(null);

  useEffect(() => {
    let cancelado = false;
    api.get('/chat/estado')
      .then((res) => { if (!cancelado) setDisponible(res.data.disponible); })
      // Si ni siquiera se puede preguntar, el widget no aparece.
      .catch(() => { if (!cancelado) setDisponible(false); });
    return () => { cancelado = true; };
  }, []);

  useEffect(() => {
    finDelHilo.current?.scrollIntoView({ behavior: 'smooth' });
  }, [mensajes, abierto]);

  const agregar = (rol, texto) =>
    setMensajes((previos) => [...previos, { rol, texto, id: Date.now() + Math.random() }]);

  const irAlFormulario = (categoria, descripcion) => {
    setAbierto(false);
    navigate('/new-ticket', { state: { categoria, descripcion, sesionId } });
  };

  const manejarRespuesta = (datos) => {
    setSesionId(datos.sesion_id);
    setCategorias(datos.categorias || []);

    switch (datos.accion) {
      // Lo primero que se intenta: si esto ya se resolvió antes, se contesta
      // aquí mismo y no hay nada que clasificar ni ticket que levantar.
      case 'solucion':
        agregar('asistente', datos.respuesta);
        if (datos.fuentes?.length) {
          agregar('asistente', t('chat.segun_fuente', {
            titulo: datos.fuentes[0].titulo
          }));
        }
        agregar('asistente', t('chat.sirvio_pregunta'));
        break;

      case 'flujo_categoria':
        agregar('asistente', t('chat.clasificado', { categoria: t(`new_ticket.category_${datos.categoria}`) }));
        setTimeout(() => irAlFormulario(datos.categoria, datos.descripcion_sugerida), 900);
        break;

      case 'pedir_categoria':
        // Sin confianza no se adivina: se le pregunta.
        agregar('asistente', t('chat.pedir_categoria'));
        break;

      case 'crear_ticket':
        agregar('asistente', t('chat.escalando'));
        setTimeout(() => irAlFormulario(null, datos.descripcion_sugerida), 900);
        break;

      case 'no_disponible':
      default:
        // Ollama se cayó a media conversación: el widget desaparece y el
        // usuario sigue en el formulario. Sin mensajes de error.
        setDisponible(false);
        irAlFormulario(null, datos.descripcion_sugerida);
        break;
    }
  };

  const enviar = async (e) => {
    e.preventDefault();
    const texto = borrador.trim();
    if (!texto || enviando) return;

    agregar('usuario', texto);
    setBorrador('');
    setEnviando(true);
    try {
      const res = await api.post('/chat/mensaje', { mensaje: texto, sesion_id: sesionId });
      manejarRespuesta(res.data);
    } catch (err) {
      // Un fallo del chat nunca deja al usuario sin salida: al formulario.
      setDisponible(false);
      irAlFormulario(null, texto);
    } finally {
      setEnviando(false);
    }
  };

  const hablarConTecnico = async () => {
    try {
      const res = await api.post('/chat/escalar', { sesion_id: sesionId });
      irAlFormulario(res.data.categoria, res.data.descripcion_sugerida);
    } catch (err) {
      // Aunque falle el registro, el usuario llega al formulario igual.
      irAlFormulario(null, '');
    }
  };

  if (!disponible) return null;

  return (
    <>
      {/* Burbuja */}
      {!abierto && (
        <button
          onClick={() => setAbierto(true)}
          className="animate-scale-in"
          aria-label={t('chat.abrir')}
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            width: '56px',
            height: '56px',
            borderRadius: '50%',
            border: 'none',
            cursor: 'pointer',
            background: 'var(--accent-primary)',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: 'var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.2))',
            zIndex: 900
          }}
        >
          <MessageCircle size={26} />
        </button>
      )}

      {/* Panel */}
      {abierto && (
        <div
          className="apple-card animate-scale-in"
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            width: 'min(380px, calc(100vw - 32px))',
            maxHeight: 'min(560px, calc(100vh - 48px))',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            zIndex: 900
          }}
        >
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            padding: '16px 18px',
            borderBottom: '1px solid var(--border-color)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <MessageCircle size={20} color="var(--accent-primary)" />
              <span style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{t('chat.titulo')}</span>
            </div>
            <button
              onClick={() => setAbierto(false)}
              className="btn-secondary"
              style={{ padding: '6px 10px' }}
              aria-label={t('chat.cerrar')}
            >
              <X size={16} />
            </button>
          </div>

          {/* Hilo */}
          <div style={{
            flex: 1,
            overflowY: 'auto',
            padding: '18px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            minHeight: '180px'
          }}>
            {mensajes.length === 0 && (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: '1.5' }}>
                {t('chat.bienvenida')}
              </div>
            )}

            {mensajes.map((m) => (
              <div
                key={m.id}
                className="animate-scale-in"
                style={{
                  alignSelf: m.rol === 'usuario' ? 'flex-end' : 'flex-start',
                  maxWidth: '85%',
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-md)',
                  // La esquina que apunta a quien habla se recorta, como en
                  // cualquier mensajería: se lee de quién es sin leer nada.
                  borderBottomRightRadius: m.rol === 'usuario' ? '4px' : 'var(--radius-md)',
                  borderBottomLeftRadius: m.rol === 'usuario' ? 'var(--radius-md)' : '4px',
                  fontSize: '0.95rem',
                  lineHeight: '1.45',
                  background: m.rol === 'usuario' ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                  color: m.rol === 'usuario' ? '#fff' : 'var(--text-primary)'
                }}
              >
                {m.texto}
              </div>
            ))}

            {/* "Está escribiendo". Sin esto el chat se siente muerto mientras
                Ollama piensa, que puede ser un par de segundos. */}
            {enviando && (
              <div
                className="animate-scale-in"
                style={{
                  alignSelf: 'flex-start',
                  padding: '12px 16px',
                  borderRadius: 'var(--radius-md)',
                  borderBottomLeftRadius: '4px',
                  background: 'var(--bg-tertiary)'
                }}
                aria-live="polite"
                aria-label={t('chat.escribiendo')}
              >
                <span className="puntos-escribiendo">
                  <span /><span /><span />
                </span>
              </div>
            )}

            {/* Dropdown de categorías cuando no hubo confianza */}
            {categorias.length > 0 && !enviando && mensajes.length > 0 && (
              <div className="lista-escalonada" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '4px' }}>
                {categorias.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => irAlFormulario(c, mensajes.filter((m) => m.rol === 'usuario').map((m) => m.texto).join('\n'))}
                    className="btn-secondary"
                    style={{ padding: '7px 13px', fontSize: '0.85rem' }}
                  >
                    {t(`new_ticket.category_${c}`)}
                  </button>
                ))}
              </div>
            )}

            <div ref={finDelHilo} />
          </div>

          {/* Salida al humano, visible siempre */}
          <button
            type="button"
            onClick={hablarConTecnico}
            className="btn-secondary"
            style={{
              margin: '0 18px 12px',
              justifyContent: 'center',
              padding: '10px',
              fontSize: '0.88rem'
            }}
          >
            <Headset size={16} />
            {t('chat.hablar_tecnico')}
          </button>

          <form onSubmit={enviar} style={{ display: 'flex', gap: '8px', padding: '0 18px 18px' }}>
            <input
              className="form-input"
              value={borrador}
              onChange={(e) => setBorrador(e.target.value)}
              placeholder={t('chat.placeholder')}
              disabled={enviando}
              style={{ flex: 1, fontSize: '0.95rem' }}
            />
            <button
              type="submit"
              className="btn-primary"
              disabled={enviando || !borrador.trim()}
              style={{ padding: '0 16px' }}
              aria-label={t('chat.enviar')}
            >
              <Send size={16} />
            </button>
          </form>
        </div>
      )}
    </>
  );
};

export default ChatFlotante;
