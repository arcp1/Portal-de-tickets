import React, {
  createContext, useContext, useEffect, useRef, useState, useCallback
} from 'react';
import { useAuth } from './AuthContext';

/**
 * La conexión en vivo con el portal.
 *
 * **Por qué `fetch` y no `EventSource`.** `EventSource` no deja poner
 * cabeceras, así que con él el token tendría que viajar en la URL — y una URL
 * acaba en los registros de nginx, en el historial y en cualquier traza. Ese
 * mismo error ya nos costó una llave de Gemini en claro. `fetch` con
 * `ReadableStream` lee el mismo formato `text/event-stream` y sí acepta la
 * cabecera `Authorization`.
 *
 * **Una conexión para todo el portal.** Es un contexto y no un hook suelto
 * porque si cada pantalla abriera la suya, un usuario con el tablero y un
 * ticket abiertos gastaría dos, y sesenta empleados serían ciento veinte
 * conexiones sostenidas contra un solo proceso de uvicorn.
 *
 * **Reconexión con espera creciente.** Si el backend se reinicia, sesenta
 * pantallas intentando reconectar a la vez cada segundo son una tormenta que
 * le impide arrancar. La espera se duplica hasta medio minuto y lleva un
 * desajuste aleatorio para que no vuelvan todas en el mismo instante. Y el
 * freno solo se suelta cuando la conexión **duró**, no cuando el servidor
 * contestó: un 200 que se cierra al instante no es una conexión.
 */

const ContextoEventos = createContext({ conectado: false, suscribir: () => () => {} });

const ESPERA_INICIAL_MS = 1000;
const ESPERA_MAXIMA_MS = 30000;
//: Cuánto tiene que durar una conexión para contarla como buena.
//:
//: El backend manda un latido cada 20 s y la pestaña suele estar abierta
//: horas, así que una conexión de verdad pasa esto de sobra. Lo que no lo pasa
//: es un 200 que se cierra en el acto —ver `espera` más abajo—.
const CONEXION_BUENA_MS = 5000;

export function ProveedorEventos({ children }) {
  // **Atado a la sesión, no al montaje.** La primera versión leía el token una
  // sola vez al montarse el proveedor — y como vive por encima del Router, eso
  // ocurre en el login, cuando todavía no hay token. El efecto salía por la
  // rama vacía y no se reintentaba nunca: el indicador se quedaba en ámbar
  // toda la sesión y el tablero seguía siendo una foto. Depender del `id` del
  // usuario y no del objeto evita además reconectar en cada render.
  const { user } = useAuth();
  const usuarioId = user?.id ?? null;
  const [conectado, setConectado] = useState(false);
  // Los oyentes viven en una ref y no en el estado: cambian a menudo —cada
  // pantalla se apunta al montarse— y meterlos en el estado reabriría la
  // conexión en cada montaje.
  const oyentes = useRef(new Map());
  const contador = useRef(0);

  const suscribir = useCallback((tipo, fn) => {
    const id = ++contador.current;
    oyentes.current.set(id, { tipo, fn });
    return () => oyentes.current.delete(id);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('portal_tickets_token');
    if (!usuarioId || !token) { setConectado(false); return undefined; }

    let cancelado = false;
    let espera = ESPERA_INICIAL_MS;
    // Cuándo se abrió la conexión en curso; 0 si no hay ninguna abierta.
    let abierta = 0;
    const abortar = new AbortController();

    const avisar = (tipo) => {
      oyentes.current.forEach(({ tipo: t, fn }) => { if (t === tipo) fn(); });
    };

    const conectar = async () => {
      while (!cancelado) {
        try {
          const res = await fetch('/api/eventos/flujo', {
            headers: { Authorization: `Bearer ${token}` },
            signal: abortar.signal,
          });
          if (!res.ok || !res.body) throw new Error(`estado ${res.status}`);

          setConectado(true);
          abierta = Date.now();

          const lector = res.body.getReader();
          const decodificador = new TextDecoder();
          let resto = '';

          // El flujo llega en trozos arbitrarios, no en mensajes: un evento
          // puede partirse entre dos lecturas. Se acumula y solo se procesa lo
          // que ya está cerrado por la línea en blanco del protocolo.
          while (!cancelado) {
            const { value, done } = await lector.read();
            if (done) break;
            resto += decodificador.decode(value, { stream: true });
            const bloques = resto.split('\n\n');
            resto = bloques.pop();
            bloques.forEach((bloque) => {
              const linea = bloque.split('\n').find((l) => l.startsWith('event:'));
              if (linea) avisar(linea.slice(6).trim());
            });
          }
        } catch (err) {
          if (cancelado || err.name === 'AbortError') return;
        }

        setConectado(false);
        if (cancelado) return;

        // **El freno se reinicia por lo que duró, no por haber conectado.**
        //
        // Antes esto se reiniciaba arriba, nada más recibir un 200. Pero un
        // 200 no significa que haya un flujo al otro lado: un proxy que
        // devuelve su propia página, o un despliegue a medias, contestan 200 y
        // cierran en el acto. Cada intento se daba entonces por bueno, el
        // freno volvía a un segundo, y el portal quedaba pidiendo esa ruta una
        // vez por segundo para siempre —sesenta pantallas, sesenta peticiones
        // por segundo contra el backend que justamente está mal—, con el
        // indicador parpadeando en verde mientras tanto.
        //
        // Medir la duración lo arregla sin adivinar: una conexión que vivió
        // gana el reintento rápido, una que murió al nacer espera cada vez
        // más. Una caída real de la red sigue reconectando en un segundo,
        // que es lo que se quería conservar.
        if (abierta && Date.now() - abierta >= CONEXION_BUENA_MS) {
          espera = ESPERA_INICIAL_MS;
        }
        abierta = 0;

        // Desajuste aleatorio: sin él, todas las pantallas que perdieron la
        // conexión a la vez vuelven a la vez.
        const pausa = espera + Math.random() * 400;
        await new Promise((r) => setTimeout(r, pausa));
        espera = Math.min(espera * 2, ESPERA_MAXIMA_MS);
      }
    };

    conectar();
    return () => { cancelado = true; abortar.abort(); };
  }, [usuarioId]);

  return (
    <ContextoEventos.Provider value={{ conectado, suscribir }}>
      {children}
    </ContextoEventos.Provider>
  );
}

/** Ejecuta `fn` cuando el portal avisa de un cambio del tipo dado. */
export function useEventoPortal(tipo, fn) {
  const { suscribir } = useContext(ContextoEventos);
  // La función se guarda en una ref para que la suscripción no se rehaga en
  // cada render solo porque el componente redefinió su callback.
  const guardada = useRef(fn);
  guardada.current = fn;
  useEffect(() => suscribir(tipo, () => guardada.current()), [tipo, suscribir]);
}

export function useConexionPortal() {
  return useContext(ContextoEventos).conectado;
}
