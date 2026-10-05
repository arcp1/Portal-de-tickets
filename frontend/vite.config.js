import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    // **Sin mapas de fuente en producción, dicho expresamente.** Es el valor
    // por defecto de Vite, pero el portal se publica en internet: un `true`
    // puesto para depurar entregaría el código fuente completo —comentarios
    // incluidos— a cualquiera que abra las herramientas del navegador.
    sourcemap: false,
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Sin esto, el proxy de Vite contesta el apretón de manos del
        // WebSocket del grafo con un 200 normal y la conexión muere ahí: en
        // desarrollo el grafo se queda gris y no dice por qué. La ruta HTTP
        // funciona igual con o sin esta línea, así que el fallo solo aparece
        // en la parte que va por WebSocket.
        ws: true,
      }
    }
  }
});
