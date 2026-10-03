import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext';

/**
 * La traza en vivo de las consultas propias, por WebSocket.
 *
 * Devuelve el estado de cada nodo del grafo y las líneas que se han recorrido,
 * agrupados por consulta. El componente que lo use solo dibuja lo que hay aquí.
 *
 * **El token va en el primer mensaje, nunca en la URL.** El navegador no deja
 * poner cabeceras al abrir un WebSocket, así que la tentación es mandarlo como
 * `?token=...`. No: una URL acaba en el registro de accesos de nginx, en el
 * historial y en cualquier traza — el mismo error que ya costó una llave de
 * Gemini en claro. El backend espera el token como primer mensaje y cierra la
 * conexión si no llega (ver `api/conciencia.py`).
 *
 * **Reconexión con espera creciente**, igual que el canal de eventos: si el
 * backend se reinicia, sesenta pantallas reintentando cada segundo son una
 * tormenta que le impide arrancar. La espera se duplica hasta medio minuto y
 * lleva un desajuste aleatorio para que no vuelvan todas en el mismo instante.
 *
 * **Y si nada de esto funciona, no pasa nada.** El grafo es una ventana a lo
 * que ocurre, no el camino por el que ocurre: la respuesta viaja por su POST
 * de siempre. Sin WebSocket se pierde la animación, nunca la respuesta.
 */

const ESPERA_INICIAL_MS = 1000;
const ESPERA_MAXIMA_MS = 30000;

/** Estado inicial: todos los nodos apagados. */
const NODOS_APAGADOS = {
  usuario: null,
  embedding: null,
  conocimiento: null,
  ia_local: null,
  gemini: null,
  respuesta: null,
};

function direccionFlujo() {
  // Mismo origen que la página. En HTTPS tiene que ser `wss:`: un `ws:` desde
  // una página segura lo bloquea el navegador por contenido mixto.
  const protocolo = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocolo}//${window.location.host}/api/conciencia/flujo`;
}

export default function useConciencia({ activo = true } = {}) {
  const { user } = useAuth();
  const usuarioId = user?.id ?? null;

  const [conectado, setConectado] = useState(false);
  const [traza, setTraza] = useState(null);
  const [nodos, setNodos] = useState(NODOS_APAGADOS);
  const [aristas, setAristas] = useState([]);

  // El id de la consulta que se está pintando. Va en una ref además de en el
  // estado porque el manejador del socket lo lee dentro de un `setState`, y
  // ahí el valor capturado por el cierre sería el del render anterior.
  const trazaActual = useRef(null);

  /** Vuelve a dejar el grafo en gris. Lo llama quien lanza una consulta nueva. */
  const reiniciar = useCallback(() => {
    trazaActual.current = null;
    setTraza(null);
    setNodos(NODOS_APAGADOS);
    setAristas([]);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('portal_tickets_token');
    if (!activo || !usuarioId || !token) { setConectado(false); return undefined; }

    let cancelado = false;
    let espera = ESPERA_INICIAL_MS;
    let socket = null;
    let reintento = null;

    const aplicar = (paso) => {
      // Una consulta nueva borra la anterior. Sin esto, dos preguntas seguidas
      // dejarían el grafo con nodos encendidos de las dos mezclados.
      if (paso.traza !== trazaActual.current) {
        trazaActual.current = paso.traza;
        setTraza(paso.traza);
        setNodos({ ...NODOS_APAGADOS, [paso.nodo]: paso });
        setAristas(paso.desde ? [{ desde: paso.desde, hasta: paso.nodo, ms: paso.ms }] : []);
        return;
      }

      setNodos((previos) => ({ ...previos, [paso.nodo]: paso }));

      if (!paso.desde) return;
      setAristas((previas) => {
        // Una línea ya recorrida no se vuelve a añadir: un nodo emite varios
        // pasos —`activo` y luego `listo`— y los dos traen el mismo origen.
        const repetida = previas.some(
          (a) => a.desde === paso.desde && a.hasta === paso.nodo
        );
        return repetida ? previas : [...previas, { desde: paso.desde, hasta: paso.nodo, ms: paso.ms }];
      });
    };

    const conectar = () => {
      if (cancelado) return;

      try {
        socket = new WebSocket(direccionFlujo());
      } catch {
        // Construir el WebSocket puede fallar de entrada (URL inválida tras un
        // despliegue raro). Se trata igual que una caída: se reintenta.
        programarReintento();
        return;
      }

      socket.onopen = () => {
        // Identificarse es lo primero: el backend cierra la conexión si el
        // token no llega dentro de su ventana.
        socket.send(JSON.stringify({ token }));
      };

      socket.onmessage = (evento) => {
        let mensaje;
        try {
          mensaje = JSON.parse(evento.data);
        } catch {
          return;    // basura en el canal: se ignora, no se cae la pantalla
        }

        if (mensaje.tipo === 'listo') {
          // El backend aceptó el token. Hasta aquí no se sabía: la conexión se
          // abre antes de autenticar, así que `onopen` no es señal de nada.
          setConectado(true);
          espera = ESPERA_INICIAL_MS;
          return;
        }
        if (mensaje.tipo === 'paso') aplicar(mensaje);
        // `latido` no necesita nada: su único trabajo es que haya tráfico.
      };

      socket.onclose = () => {
        setConectado(false);
        if (!cancelado) programarReintento();
      };

      // `onerror` siempre viene seguido de `onclose`, así que reintentar aquí
      // abriría dos conexiones por cada caída.
      socket.onerror = () => {};
    };

    const programarReintento = () => {
      if (cancelado) return;
      // Desajuste aleatorio: sin él, todas las pantallas que perdieron la
      // conexión a la vez vuelven a la vez.
      const pausa = espera + Math.random() * 400;
      espera = Math.min(espera * 2, ESPERA_MAXIMA_MS);
      reintento = setTimeout(conectar, pausa);
    };

    conectar();

    return () => {
      cancelado = true;
      if (reintento) clearTimeout(reintento);
      if (socket) {
        // Se quitan los manejadores antes de cerrar: si no, el `onclose` del
        // cierre voluntario programa un reintento contra un efecto que ya se
        // desmontó, y cada montaje deja atrás un temporizador vivo.
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
      }
    };
  }, [usuarioId, activo]);

  return { conectado, traza, nodos, aristas, reiniciar };
}
