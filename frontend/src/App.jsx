import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Navbar from './components/Navbar';
import ChatFlotante from './components/ChatFlotante';
import Cargando from './components/Cargando';
import LimiteDeError from './components/LimiteDeError';
import { ProveedorHorario } from './components/AvisoHorario';
import Login from './pages/Login';
import Activar from './pages/Activar';
import Usuarios from './pages/Usuarios';
import Importar from './pages/Importar';
import EstadoSistema from './pages/EstadoSistema';
import Soluciones from './pages/Soluciones';
import DocumentacionTI from './pages/DocumentacionTI';
import Dashboard from './pages/Dashboard';
import NewTicket from './pages/NewTicket';
import TicketDetail from './pages/TicketDetail';
import Inventory from './pages/Inventory';
import RulesAdmin from './pages/RulesAdmin';
import Metricas from './pages/Metricas';
import Temas from './pages/Temas';
import Expediente from './pages/Expediente';
import Resguardos from './pages/Resguardos';

const ProtectedRoute = ({ children, adminOnly = false }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Cargando />;

  if (!user) {
    // Se recuerda a dónde iba para devolverlo ahí después de autenticarse.
    return <Navigate to="/login" replace state={{ desde: location.pathname }} />;
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
  const { user, loading } = useAuth();

  // La barra solo existe dentro del portal. Mientras se resuelve la sesión no
  // se pinta nada para no mostrar media interfaz.
  const enPortal = Boolean(user) && !loading;

  return (
    <>
      {enPortal && <Navbar />}
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
        <Route path="/soluciones" element={<ProtectedRoute adminOnly><Soluciones /></ProtectedRoute>} />
        <Route path="/documentacion" element={<ProtectedRoute adminOnly><DocumentacionTI /></ProtectedRoute>} />
        <Route path="/rules" element={<ProtectedRoute adminOnly><RulesAdmin /></ProtectedRoute>} />
        <Route path="/temas" element={<ProtectedRoute adminOnly><Temas /></ProtectedRoute>} />
        <Route path="/metricas" element={<ProtectedRoute adminOnly><Metricas /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* Visible desde que el usuario entra al portal. Se oculta solo si
          Ollama no está disponible. */}
      {enPortal && <ChatFlotante />}
    </>
  );
}

function App() {
  return (
    <LimiteDeError>
      <AuthProvider>
        <ProveedorHorario>
          <Router>
            <AppRoutes />
          </Router>
        </ProveedorHorario>
      </AuthProvider>
    </LimiteDeError>
  );
}

export default App;
