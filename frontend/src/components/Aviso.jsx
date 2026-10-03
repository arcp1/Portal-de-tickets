import React from 'react';
import { AlertTriangle } from 'lucide-react';

/**
 * La barra de aviso de una pantalla.
 *
 * Estaba copiada literalmente en seis páginas, con sus ocho líneas de estilo
 * en línea cada una. Al unificarla se gana algo más que quitar repetición:
 *
 * **Lleva `role="alert"`.** Sin eso, quien usa un lector de pantalla no se
 * entera de que la carga falló — el texto aparece en el documento sin que nada
 * lo anuncie, y la persona se queda mirando una lista vacía creyendo que no
 * hay nada. Es la diferencia entre "no hay tickets" y "no se pudieron traer
 * los tickets", que no es un matiz.
 */
export default function Aviso({ texto, tono = 'atencion' }) {
  if (!texto) return null;
  return (
    <div className={`aviso-barra aviso-barra--${tono} animate-scale-in`} role="alert">
      <AlertTriangle size={18} aria-hidden="true" />
      <span>{texto}</span>
    </div>
  );
}
