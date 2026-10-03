import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';
import './i18n.js';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// **PWA: solo en contexto seguro.** Los navegadores no registran un Service
// Worker por HTTP salvo en localhost; por la IP del tailnet se salta sin
// ruido y el portal funciona igual. Por la dirección HTTPS (la de
// PORTAL_URL) se registra y el portal se puede instalar. Ver public/sw.js.
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* sin PWA, igual funciona */ });
  });
}
