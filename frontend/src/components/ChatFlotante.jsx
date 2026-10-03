import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import ReconocimientoVisual, { PasosVisuales } from './ReconocimientoVisual';
import { MessageCircle, X, Send, Headset } from 'lucide-react';

/**
 * Chatbot flotante: entrada alternativa al formulario, no un reemplazo.
 *
 * El chat solo sustituye el paso de elegir categoría. En cuanto hay una
 * categoría, se va al formulario de siempre con el flujo de siempre.
 *
 * Si Ollama no está disponible el widget no se dibuja: queda el formulario con
 * dropdown, que nunca deja de funcionar.
 *
 * **Lo único que puede interrumpir ese camino son las fotos.** Cuando lo que
 * la persona describe es un defecto que se ve —"la copia sale borrosa"— el
 * portal enseña las fotos que TI documentó y pregunta cuál es la suya antes de
 * clasificar nada. Si dice que ninguna, el mismo mensaje vuelve a salir con
 * `omitir_visual` y la conversación sigue exactamente como si esto no
 * existiera. Ver `ReconocimientoVisual` y `visual_service.py`.
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

  /* Un turno del hilo que no es texto: las fotos para elegir, o los pasos
     señalados sobre una captura. Van en el hilo y no en una barra aparte
     porque son parte de la conversación —se leen después de lo que se dijo
     antes y antes de lo que venga— y sacarlas de ahí rompía ese orden. */
  const agregarBloque = (bloque) =>
    setMensajes((previos) => [...previos, { ...bloque, id: Date.now() + Math.random() }]);

  const quitarFichas = () =>
    setMensajes((previos) => previos.filter((m) => m.tipo !== 'fichas'));

  const quitarDesenlace = () =>
    setMensajes((previos) => previos.filter((m) => m.tipo !== 'desenlace'));

  const irAlFormulario = (categoria, descripcion) => {
    setAbierto(false);
    navigate('/new-ticket', { state: { categoria, descripcion, sesionId } });
  };

  const manejarRespuesta = (datos) => {
    setSesionId(datos.sesion_id);
    setCategorias(datos.categorias || []);

    switch (datos.accion) {
      // Antes que nada: si lo que describe se puede reconocer mirándolo, se
      // enseñan las fotos y decide la persona. Nada se clasifica todavía.
      case 'reconocer_imagen':
        agregar('asistente', t('visual.se_ve_asi'));
        agregarBloque({
          rol: 'asistente',
          tipo: 'fichas',
          fichas: datos.fichas || [],
          // Lo que escribió, para poder reenviarlo si dice que no es ninguna.
          consulta: datos.descripcion_sugerida
        });
        break;

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

  /* "Sí, es ésta." Lo que llega es la solución atada a la foto que la persona
     reconoció, con sus pasos señalados si TI los subió. */
  const elegirFicha = async (ficha, consulta) => {
    quitarFichas();
    agregar('usuario', ficha.titulo);
    setEnviando(true);
    try {
      const res = await api.post('/visual/confirmar', { ficha_id: ficha.ficha_id });
      agregar('asistente', res.data.solucion);
      if (res.data.pasos?.length) {
        agregarBloque({
          rol: 'asistente', tipo: 'pasos',
          fichaId: ficha.ficha_id, pasos: res.data.pasos
        });
      }
      // Lo que ya se probó y no era. Se enseña siempre y al final: es lo que
      // evita que alguien repita media hora de trabajo que ya se descartó.
      if (res.data.descartado) {
        agregar('asistente', t('visual.ya_se_probo', { texto: res.data.descartado }));
      }
      // **La pregunta que cierra el ciclo.** Reconocer la foto no es arreglar
      // el problema: sin preguntarlo, una ficha con la foto perfecta y la
      // solución equivocada sale en el tablero como la mejor del catálogo.
      agregarBloque({
        rol: 'asistente', tipo: 'desenlace',
        ficha: { ...ficha, ...res.data }, consulta: consulta || ficha.titulo
      });
    } catch (err) {
      // Si la ficha ya no está, no se deja a nadie mirando el hueco: al
      // formulario, con lo que escribió —no con el título de la ficha, que lo
      // redactó TI y no describe su caso—.
      irAlFormulario(ficha.categoria || null, consulta || ficha.titulo);
    } finally {
      setEnviando(false);
    }
  };

  /* "¿Se arregló?" — el desenlace.

     Si sí, se acabó: ni ticket ni formulario, que es exactamente el punto de
     todo esto. Si no, se levanta el ticket **diciendo qué se probó ya**: TI no
     tiene por qué gastar media hora repitiendo lo que esta persona acaba de
     hacer. */
  const desenlaceVisual = async (bloque, resuelto) => {
    quitarDesenlace();
    setEnviando(true);
    try {
      await api.post('/visual/resultado', {
        ficha_id: bloque.ficha.ficha_id,
        resuelto,
        consulta: bloque.consulta
      });
    } catch {
      // Una métrica perdida no le corta la conversación a nadie.
    } finally {
      setEnviando(false);
    }

    if (resuelto) {
      agregar('usuario', t('visual.si_se_arreglo'));
      agregar('asistente', t('visual.cerrado_sin_ticket'));
      return;
    }

    agregar('usuario', t('visual.sigue_igual'));
    agregar('asistente', t('chat.escalando'));
    const nota = t('visual.nota_no_arreglo', { titulo: bloque.ficha.titulo });
    setTimeout(
      () => irAlFormulario(bloque.ficha.categoria || null,
                          `${bloque.consulta}\n\n${nota}`),
      900
    );
  };

  /* "No es ninguna de éstas." Se anota —una ficha que se enseña mucho y no
     confirma nadie está emparejando con lo que no debe— y el mismo mensaje
     sigue su camino de siempre, ya sin la parte visual. */
  const ningunaFicha = async (bloque) => {
    quitarFichas();
    agregar('usuario', t('visual.ninguna'));
    setEnviando(true);
    try {
      await api.post('/visual/descartar', {
        ficha_ids: (bloque.fichas || []).map((f) => f.ficha_id),
        consulta: bloque.consulta
      });
    } catch {
      // Que no se pueda anotar el descarte no es motivo para cortarle la
      // conversación a nadie: es una métrica, no el flujo.
    }
    try {
      const res = await api.post('/chat/mensaje', {
        mensaje: bloque.consulta,
        sesion_id: sesionId,
        omitir_visual: true
      });
      manejarRespuesta(res.data);
    } catch (err) {
      setDisponible(false);
      irAlFormulario(null, bloque.consulta);
    } finally {
      setEnviando(false);
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
      // **Demasiado seguido no es una falla del chat.** El cupo de consultas
      // por persona (`IA_PETICIONES_POR_MINUTO`) responde 429: se dice aquí
      // mismo y se le devuelve su texto, en vez de cerrar la conversación y
      // mandarla al formulario como si el asistente se hubiera caído.
      if (err.response?.status === 429) {
        agregar('asistente', err.response.data?.detail || t('chat.demasiado_seguido'));
        setBorrador(texto);
        return;
      }
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
          className="boton-chat animate-scale-in"
          aria-label={t('chat.abrir')}
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

            {mensajes.map((m) => {
              /* Las fotos y los pasos ocupan el ancho del panel: una burbuja
                 al 85% con una imagen dentro deja la foto en 250 px, y a ese
                 tamaño no se distingue una copia borrosa de una con sombra,
                 que es justo lo que hay que distinguir. */
              if (m.tipo === 'fichas') {
                return (
                  <div key={m.id} style={{ alignSelf: 'stretch' }}>
                    <ReconocimientoVisual
                      fichas={m.fichas}
                      trabajando={enviando}
                      onElegir={(f) => elegirFicha(f, m.consulta)}
                      onNinguna={() => ningunaFicha(m)}
                    />
                  </div>
                );
              }
              if (m.tipo === 'desenlace') {
                return (
                  <div key={m.id} style={{ alignSelf: 'stretch', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                      {t('visual.se_arreglo')}
                    </span>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button type="button" className="btn-secondary btn-secondary--exito"
                        onClick={() => desenlaceVisual(m, true)} disabled={enviando}
                        style={{ flex: 1, justifyContent: 'center', padding: '8px', fontSize: '0.85rem' }}>
                        {t('visual.si_se_arreglo')}
                      </button>
                      <button type="button" className="btn-secondary"
                        onClick={() => desenlaceVisual(m, false)} disabled={enviando}
                        style={{ flex: 1, justifyContent: 'center', padding: '8px', fontSize: '0.85rem' }}>
                        {t('visual.sigue_igual')}
                      </button>
                    </div>
                  </div>
                );
              }
              if (m.tipo === 'pasos') {
                return (
                  <div key={m.id} style={{ alignSelf: 'stretch' }}>
                    <PasosVisuales fichaId={m.fichaId} pasos={m.pasos} />
                  </div>
                );
              }
              return (
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
                    // Las soluciones vienen con saltos de línea y sin esto se
                    // leían como un solo párrafo corrido.
                    whiteSpace: 'pre-wrap',
                    background: m.rol === 'usuario' ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                    color: m.rol === 'usuario' ? '#fff' : 'var(--text-primary)'
                  }}
                >
                  {m.texto}
                </div>
              );
            })}

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
            {/* `maxLength` es el mismo tope que exige el backend, puesto aquí
                para que quien pegue un texto largo lo note al escribir en vez
                de recibir un 422 tras esperar. El que cuenta es el del
                servidor: éste se quita con las herramientas del navegador. */}
            <input
              className="form-input"
              value={borrador}
              onChange={(e) => setBorrador(e.target.value)}
              placeholder={t('chat.placeholder')}
              disabled={enviando}
              maxLength={2000}
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
