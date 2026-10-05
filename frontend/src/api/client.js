import axios from 'axios';
import i18n from '../i18n';
import { avisar } from '../lib/avisos';

// **Un tope de espera.** Sin él, una petición que se queda colgada —el Wi-Fi
// de planta que se cae a medio envío sin cerrar la conexión— no fallaba
// nunca: el botón se quedaba en "Generando..." indefinidamente y la persona
// no sabía si esperar o recargar. 90 s cubren lo más lento que hace el
// portal a propósito, una respuesta del asistente en CPU; las subidas de
// archivos piden más por su cuenta (`ESPERA_SUBIDA`).
export const ESPERA_SUBIDA = 5 * 60 * 1000;

const api = axios.create({
  baseURL: '/api',
  timeout: 90 * 1000,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('portal_tickets_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

/** La marca que deja el cierre por sesión caducada para que el login lo diga. */
export const SESION_CADUCADA = 'portal_sesion_caducada';
// El servidor pide aceptar los Términos y Condiciones (403 `terminos_pendientes`):
// pasa si se publicó una versión nueva con la sesión abierta. AuthContext lo
// escucha, vuelve a leer la sesión y la pantalla muestra la puerta.
export const TERMINOS_PENDIENTES = 'portal:terminos-pendientes';
/** A dónde volver después de entrar de nuevo. Ver el manejo del 401. */
export const VOLVER_A = 'portal_volver_a';

api.interceptors.response.use(
  (response) => {
    // **La sesión no caduca mientras se trabaja.** Pasada la mitad de su vida,
    // el backend manda un token nuevo en esta cabecera (ver
    // `_renovar_si_hace_falta` en backend/app/api/deps.py). Guardarlo en
    // `localStorage` lo comparte con las demás pestañas: `AuthContext` ve que
    // es la misma persona y no recarga nada.
    const renovado = response.headers?.['x-token-renovado'];
    if (renovado) {
      try { localStorage.setItem('portal_tickets_token', renovado); } catch { /* sin almacenamiento */ }
    }
    return response;
  },
  (error) => {
    // **Un `detail` que no es texto no llega a ninguna pantalla.** El backend
    // ya responde siempre `{ detail: texto, codigo }` (backend/app/core/
    // errores.py), pero no todo lo que contesta en /api es el backend: un
    // proxy caído devuelve su propia página, y un despliegue a medias puede
    // traer la forma vieja, con los 422 como lista de objetos. Una lista que
    // llega al `<span>` de un aviso tumba la pantalla entera ("Objects are
    // not valid as a React child"); sin `detail`, cada pantalla cae en su
    // propio mensaje traducido.
    const cuerpo = error.response?.data;
    if (cuerpo && typeof cuerpo === 'object' && 'detail' in cuerpo
        && typeof cuerpo.detail !== 'string') {
      delete cuerpo.detail;
    }

    // **Sin respuesta es que no hay red o no hay servidor.** Cada pantalla
    // dice lo suyo —"no se pudieron cargar los tickets"—, pero el tablero y
    // el detalle se refrescan solos y en silencio, así que un corte podía
    // pasar sin que nadie lo notara hasta pulsar algo. Un solo aviso, con
    // clave: seis peticiones caídas a la vez no son seis avisos.
    if (!error.response && error.code !== 'ERR_CANCELED') {
      avisar(i18n.t('comun.sin_conexion'), { tono: 'atencion', clave: 'sin-conexion' });
    }

    if (error.response?.status === 403 && cuerpo?.codigo === 'terminos_pendientes') {
      window.dispatchEvent(new Event(TERMINOS_PENDIENTES));
    }
    if (error.response && error.response.status === 401) {
      const habiaSesion = Boolean(localStorage.getItem('portal_tickets_token'));
      localStorage.removeItem('portal_tickets_token');
      let usuarioGuardado = null;
      try { usuarioGuardado = localStorage.getItem('portal_tickets_user'); } catch { /* nada */ }
      localStorage.removeItem('portal_tickets_user');
      if (window.location.pathname !== '/login') {
        // Antes se aterrizaba en el login sin una palabra, y la gente creía
        // que el portal la había echado por un fallo. El login lo lee y lo dice.
        if (habiaSesion) {
          try { sessionStorage.setItem(SESION_CADUCADA, '1'); } catch { /* sin almacenamiento, sin aviso */ }
        }
        // **Y se vuelve a donde se estaba.** La recarga completa se llevaba el
        // `state` con el que el login sabe de dónde venía la persona: entraba
        // de nuevo y aterrizaba en el inicio, lejos del ticket a medio
        // escribir —que el formulario guarda como borrador justo para esto—.
        // Con la cuenta: en una computadora compartida, quien entre después
        // no debe aterrizar en el ticket a medio escribir del anterior.
        try {
          const quien = JSON.parse(usuarioGuardado || 'null')?.id ?? null;
          sessionStorage.setItem(VOLVER_A, JSON.stringify({
            ruta: window.location.pathname + window.location.search, usuarioId: quien,
          }));
        } catch { /* sin almacenamiento: vuelve al inicio, como antes */ }
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
