import React from 'react';

/**
 * El logotipo de Microsoft: cuatro cuadros con sus colores de marca. Dibujado
 * aquí y no traído de fuera: la política de contenido solo deja cargar
 * imágenes del propio portal.
 */
export default function LogoMicrosoft({ tamano = 20 }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 21 21" aria-hidden="true" focusable="false">
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}
