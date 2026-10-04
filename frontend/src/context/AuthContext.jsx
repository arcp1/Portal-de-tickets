import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import api from '../api/client';
import { olvidarTodo as olvidarImagenes } from '../lib/blobs';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(() => {
    // Es solo lo que se pinta mientras `/auth/me` contesta: el usuario de
    // verdad lo trae el backend en el efecto de abajo. Si lo guardado está
    // corrupto se descarta en vez de dejar el portal en blanco al arrancar
    // —un `JSON.parse` que falla aquí revienta antes de cualquier límite de
    // error—.
    try {
      const saved = localStorage.getItem('portal_tickets_user');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);
  // El portal no pudo confirmar la sesión, pero el token sigue guardado.
  const [falloRed, setFalloRed] = useState(false);
  // Para el oyente de `storage`, que se registra una vez y no ve el estado nuevo.
  const usuarioActual = useRef(user);
  useEffect(() => { usuarioActual.current = user; }, [user]);

  // **Una sola sesión por navegador, y todas las pestañas se enteran.**
  //
  // El token vive en `localStorage`, que comparten todas las pestañas del
  // mismo origen, y `api/client.js` lo lee en cada petición. Pero esta
  // pestaña solo lo miraba al cargar: si en otra se entraba con otra cuenta,
  // ésta seguía pintando el panel de la primera —el menú de admin, sus
  // listas— mientras cada petición salía ya con el token de la segunda. Un
  // admin veía su panel y lo que pulsaba lo hacía otra persona (o fallaba con
  // 403 sin explicación). Y al cerrar sesión en una pestaña, las demás
  // seguían "dentro" hasta su siguiente 401.
  //
  // `storage` solo llega a las *otras* pestañas, nunca a la que hizo el cambio.
  useEffect(() => {
    const alCambiarEnOtraPestana = (evento) => {
      if (evento.key !== null && evento.key !== 'portal_tickets_token'
          && evento.key !== 'portal_tickets_user') return;
      if (!localStorage.getItem('portal_tickets_token')) {
        setUser(null);
        return;
      }
      let otro = null;
      try {
        otro = JSON.parse(localStorage.getItem('portal_tickets_user') || 'null');
      } catch { /* ilegible: se trata como otra persona */ }
      const actual = usuarioActual.current;
      if (actual && otro && actual.id === otro.id && actual.rol === otro.rol) {
        setUser(otro);
        return;
      }
      // Otra persona, o esta pestaña estaba fuera: lo que hay en pantalla se
      // pidió con la sesión anterior y no se puede rescatar a pedazos.
      window.location.assign('/');
    };
    window.addEventListener('storage', alCambiarEnOtraPestana);
    return () => window.removeEventListener('storage', alCambiarEnOtraPestana);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('portal_tickets_token');
    if (token) {
      api.get('/auth/me')
        .then((res) => {
          setUser(res.data);
          localStorage.setItem('portal_tickets_user', JSON.stringify(res.data));
        })
        .catch((err) => {
          // **Solo se cierra la sesión si el token no vale.** Antes cualquier
          // fallo la borraba, y eso incluye que el backend no conteste: se
          // probó parándolo y el portal echaba fuera a quien ya estaba dentro
          // con la sesión intacta. Un reinicio de treinta segundos del backend
          // habría desconectado a toda la planta y obligado a cada persona a
          // volver a escribir su contraseña.
          //
          // Un 401 o un 403 sí dicen que el token caducó o no sirve. Un 502,
          // un tiempo agotado o un corte de red no dicen nada sobre el token:
          // se conserva lo que hay guardado y se sigue, que además permite
          // leer lo que ya estaba en pantalla.
          const codigo = err.response?.status;
          if (codigo === 401 || codigo === 403) logout();
          else setFalloRed(true);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (identificador, password) => {
    // El backend acepta número de empleado o correo en el mismo campo.
    const res = await api.post('/auth/login', { email: identificador, password });
    const { access_token, user: userData } = res.data;
    localStorage.setItem('portal_tickets_token', access_token);
    localStorage.setItem('portal_tickets_user', JSON.stringify(userData));
    setUser(userData);
    return userData;
  };

  /**
   * Guarda una sesión ya emitida por el backend.
   *
   * La usa la activación de cuenta: el backend devuelve token al activar, así
   * que no tiene sentido pedirle a la persona que inicie sesión otra vez con
   * la contraseña que acaba de escribir.
   */
  const aplicarSesion = (token, datosUsuario) => {
    localStorage.setItem('portal_tickets_token', token);
    localStorage.setItem('portal_tickets_user', JSON.stringify(datosUsuario));
    setUser(datosUsuario);
  };

  const logout = () => {
    // **Cerrar sesión de verdad.** Con Redis, el backend anota la sesión como
    // revocada y ninguna copia del token —otra pestaña olvidada, la terminal
    // compartida de la planta— vuelve a entrar con ella. Sin esperar la
    // respuesta: salir no puede depender de que el servidor conteste. El
    // token va escrito aquí porque se borra en la línea siguiente.
    const token = localStorage.getItem('portal_tickets_token');
    if (token) {
      api.post('/auth/logout', null, { headers: { Authorization: `Bearer ${token}` } })
        .catch(() => { /* sin red o ya caducada: da igual, se sale igual */ });
    }
    localStorage.removeItem('portal_tickets_token');
    localStorage.removeItem('portal_tickets_user');
    // Las imágenes descargadas eran de esta cuenta (lib/blobs.js).
    olvidarImagenes();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, falloRed, login, logout, aplicarSesion }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
