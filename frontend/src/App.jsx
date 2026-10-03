import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import useTituloPagina from './hooks/useTituloPagina';
import useAtajoBusqueda from './hooks/useAtajoBusqueda';
import Navbar from './components/Navbar';
import PaletaComandos from './components/PaletaComandos';
// **El fondo se carga aparte.** El login es lo primero que abre todo el
// mundo, y el fondo no hace falta para poder teclear el número de empleado.
// En diferido, la gente ve los campos de inmediato y el fondo llega por
// detrás. Sin `fallback` visible: mientras no está, se ve el color de CSS.
//
// Hay otros dos fondos escritos y sin montar —`FondoShader`, la onda
// cromática, y `MallaGeometrica`, el alambre con el resorte—. Para volver a
// cualquiera de ellos basta cambiar este `import` y el JSX de abajo; mientras
// nadie los importe no entran en el paquete y no cuestan nada.
const FondoBurbujas = lazy(() => import('./components/FondoBurbujas'));
import ChatFlotante from './components/ChatFlotante';
import Avisos from './components/Avisos';
import Cargando from './components/Cargando';
import LimiteDeError from './components/LimiteDeError';
import { ProveedorHorario } from './components/AvisoHorario';
import { ProveedorEventos } from './context/Eventos';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import NewTicket from './pages/NewTicket';
import TicketDetail from './pages/TicketDetail';
import Inventory from './pages/Inventory';
import FiltrosSVG from './components/FiltrosSVG';

/**
 * **Lo que no usa todo el mundo, se descarga cuando se usa.** Todo iba en un
 * solo paquete de 760 KB: quien solo levanta tickets descargaba, parseaba y
 * compilaba en cada carga las trece pantallas de administración —en las
 * computadoras de planta, que no son nuevas, eso son segundos—. Ahora esas
 * pantallas, la de activación y el expediente se piden al entrar en ellas.
 *
 * Tras una actualización, una pestaña abierta con la versión anterior pide
 * trozos que ya no existen en el servidor, y la importación falla. Se recarga
 * una vez para traer la versión nueva —`index.html` nunca se cachea—; si
 * falla también después de recargar, ya no es eso y el error sigue su curso
 * hasta `LimiteDeError`.
 */
const RECARGADO = 'portal_recargado_por_version';
const diferida = (importar) => lazy(() => importar()
  .then((modulo) => {
    try { sessionStorage.removeItem(RECARGADO); } catch { /* nada */ }
    return modulo;
  })
  .catch((error) => {
    let yaRecargo = true;
    try {
      yaRecargo = Boolean(sessionStorage.getItem(RECARGADO));
      if (!yaRecargo) sessionStorage.setItem(RECARGADO, '1');
    } catch { /* sin almacenamiento: mejor no arriesgar un bucle */ }
    if (!yaRecargo) {
      window.location.reload();
      return new Promise(() => {});
    }
    throw error;
  }));

const Activar = diferida(() => import('./pages/Activar'));
const Usuarios = diferida(() => import('./pages/Usuarios'));
const Importar = diferida(() => import('./pages/Importar'));
const EstadoSistema = diferida(() => import('./pages/EstadoSistema'));
const Conciencia = diferida(() => import('./pages/Conciencia'));
const Soluciones = diferida(() => import('./pages/Soluciones'));
const DocumentacionTI = diferida(() => import('./pages/DocumentacionTI'));
const CatalogoVisual = diferida(() => import('./pages/CatalogoVisual'));
const RulesAdmin = diferida(() => import('./pages/RulesAdmin'));
const Metricas = diferida(() => import('./pages/Metricas'));
const Temas = diferida(() => import('./pages/Temas'));
const Expediente = diferida(() => import('./pages/Expediente'));
const Resguardos = diferida(() => import('./pages/Resguardos'));
const Monitoreo = diferida(() => import('./pages/Monitoreo'));
const Plantas = diferida(() => import('./pages/Plantas'));

const ProtectedRoute = ({ children, adminOnly = false }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Cargando />;

  if (!user) {
    // Se recuerda a dónde iba para devolverlo ahí después de autenticarse.
    // Con la consulta: el QR de un equipo trae `?equipo=…&categoria=…`, y
    // quien lo escanea sin sesión tiene que volver a ese formulario ya lleno
    // después de entrar, no a uno vacío.
    return <Navigate to="/login" replace state={{ desde: location.pathname + location.search }} />;
  }

  if (adminOnly && user.rol !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return children;
};

/**
 * El login no se muestra a quien ya inició sesión.
 *
 * Sin esto, volver atrás desde el portal dejaba la barra superior arriba y el
 * formulario de login flotando en medio de la pantalla: dos pantallas a la vez.
 */
const RutaPublica = ({ children }) => {
  const { user, loading } = useAuth();

  if (loading) return <Cargando />;
  if (user) return <Navigate to="/" replace />;

  return children;
};

function AppRoutes() {
  useTituloPagina();
  useAtajoBusqueda();
  const { user, loading } = useAuth();
  const { pathname } = useLocation();

  // Los resortes solo se mueven en las pantallas de puerta. Dentro del portal
  // el fondo se queda quieto: cada fotograma obligaria a recalcular el fondo
  // que leen todos los `backdrop-filter` de la pagina, y ahi hay quince
  // tarjetas. Ver el comentario de `.lienzo--animado` en index.css.
  const enLaPuerta = pathname === '/login' || pathname === '/activar';

  // La barra solo existe dentro del portal. Mientras se resuelve la sesión no
  // se pinta nada para no mostrar media interfaz.
  const enPortal = Boolean(user) && !loading;
  const esAdmin = user?.rol === 'admin';
  const fondoFlujo = esAdmin && !enLaPuerta;

  /* **El fondo se anuncia en la raíz, y no es cosmética.**

     La hoja de estilos es una para todos, pero desde que el administrador
     tiene un fondo distinto hay dos calibraciones posibles y son opuestas: el
     vidrio se oscureció hasta `brightness(0.58)` para sobrevivir a esferas de
     color a plena intensidad, y sobre una retícula casi negra ese mismo ajuste
     deja de ser vidrio y pasa a ser una lámina gris —no hay nada detrás que
     dejar pasar—.

     Marcando cuál está puesto, cada uno puede tener el suyo sin que el
     trabajador herede los ajustes del administrador ni al revés. */
  React.useEffect(() => {
    document.documentElement.dataset.fondo = fondoFlujo ? 'flujo' : 'burbujas';
  }, [fondoFlujo]);

  return (
    <>
      {/* Un solo fondo para todo el portal. Lo que cambia entre la puerta y
          las pantallas de trabajo no es el dibujo, es si se mueve: ver el
          comentario de `FondoBurbujas`.

          Va dentro del Router para poder mirar la ruta, pero fuera de
          `Routes`, así no se vuelve a montar al navegar y las esferas no
          saltan de sitio al cambiar de pantalla. */}
      {/* Los filtros SVG que consumen el fondo y los botones. Una vez para
          todo el portal: `filter: url(#...)` necesita que el destino exista
          en el documento, y antes solo existía dentro del login. */}
      <FiltrosSVG />
      <Suspense fallback={null}>
        {/* **Un solo fondo para todo.** El vórtice se retira: la plantilla
            que ahora manda en la vista de administrador es la misma de la que
            salió el login, y su fondo son estas esferas. Tener dos lenguajes
            —retícula de shader dentro, esferas líquidas en la puerta— era la
            incoherencia que quedaba.

            Se mueven en la puerta y también para el administrador, que es lo
            que hace la plantilla. Para el trabajador siguen quietas: cada
            fotograma obliga a recalcular el fondo que leen todos los
            `backdrop-filter` de la página. */}
        <FondoBurbujas animado={enLaPuerta || fondoFlujo} />
      </Suspense>
      {enPortal && <Navbar />}
      {/* La paleta solo dentro del portal: en la puerta no hay nada a donde
          ir, y el atajo se quedaría escuchando un `Ctrl+K` que no abre nada.
          Se dibuja ella misma en un portal del DOM, así que da igual dónde se
          monte mientras sea debajo del proveedor de sesión. */}
      {enPortal && <PaletaComandos />}
      {/* El respaldo de las pantallas diferidas: el mismo "cargando" de
          siempre mientras llega su trozo. */}
      <Suspense fallback={<Cargando />}>
      <Routes>
        <Route path="/login" element={<RutaPublica><Login /></RutaPublica>} />
        <Route path="/activar" element={<RutaPublica><Activar /></RutaPublica>} />
        <Route path="/" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
        <Route path="/new-ticket" element={<ProtectedRoute><NewTicket /></ProtectedRoute>} />
        <Route path="/tickets/:id" element={<ProtectedRoute><TicketDetail /></ProtectedRoute>} />
        <Route path="/inventory" element={<ProtectedRoute><Inventory /></ProtectedRoute>} />
        <Route path="/expediente" element={<ProtectedRoute><Expediente /></ProtectedRoute>} />
        <Route path="/expediente/:usuarioId" element={<ProtectedRoute adminOnly><Expediente /></ProtectedRoute>} />
        <Route path="/resguardos" element={<ProtectedRoute adminOnly><Resguardos /></ProtectedRoute>} />
        <Route path="/usuarios" element={<ProtectedRoute adminOnly><Usuarios /></ProtectedRoute>} />
        <Route path="/importar" element={<ProtectedRoute adminOnly><Importar /></ProtectedRoute>} />
        <Route path="/estado" element={<ProtectedRoute adminOnly><EstadoSistema /></ProtectedRoute>} />
        <Route path="/conciencia" element={<ProtectedRoute adminOnly><Conciencia /></ProtectedRoute>} />
        <Route path="/soluciones" element={<ProtectedRoute adminOnly><Soluciones /></ProtectedRoute>} />
        <Route path="/documentacion" element={<ProtectedRoute adminOnly><DocumentacionTI /></ProtectedRoute>} />
        <Route path="/catalogo-visual" element={<ProtectedRoute adminOnly><CatalogoVisual /></ProtectedRoute>} />
        <Route path="/rules" element={<ProtectedRoute adminOnly><RulesAdmin /></ProtectedRoute>} />
        <Route path="/temas" element={<ProtectedRoute adminOnly><Temas /></ProtectedRoute>} />
        <Route path="/metricas" element={<ProtectedRoute adminOnly><Metricas /></ProtectedRoute>} />
        <Route path="/monitoreo" element={<ProtectedRoute adminOnly><Monitoreo /></ProtectedRoute>} />
        <Route path="/plantas" element={<ProtectedRoute adminOnly><Plantas /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
      {/* Visible desde que el usuario entra al portal. Se oculta solo si
          Ollama no está disponible. */}
      {enPortal && <ChatFlotante />}
      {/* Fuera de las rutas: un aviso tiene que sobrevivir al cambio de
          pantalla que muchas veces lo provoca. */}
      <Avisos />
    </>
  );
}

function App() {
  return (
    <LimiteDeError>
      <AuthProvider>
        <ProveedorEventos>
          <ProveedorHorario>
            <Router>
              <AppRoutes />
            </Router>
          </ProveedorHorario>
        </ProveedorEventos>
      </AuthProvider>
    </LimiteDeError>
  );
}

export default App;
