import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { urlDe } from '../lib/blobs';
import { AlertTriangle } from 'lucide-react';

/**
 * Una imagen que vive detrás del token.
 *
 * **Por qué no basta con `<img src="/api/...">`.** El navegador no manda la
 * cabecera de autorización en las peticiones de imagen: pide la URL a pelo, el
 * endpoint responde 401 y en pantalla queda el icono de imagen rota. Hay que
 * descargarla con el cliente autenticado y enseñarla desde un blob.
 *
 * Esto estaba escrito dentro de `AdjuntosTicket` y sirve igual para las fotos
 * del catálogo visual. Copiarlo habría dejado dos sitios donde acordarse de
 * revocar el blob —y el que se olvide retiene la imagen en memoria mientras
 * viva la pestaña, sin que nada lo diga—.
 */
const ImagenApi = ({
  ruta,
  alt = '',
  ancho = '100%',
  alto = 'auto',
  ajuste = 'cover',
  estilo = {},
  onClick,
}) => {
  const { t } = useTranslation();
  const [url, setUrl] = useState(null);
  const [fallo, setFallo] = useState(false);

  useEffect(() => {
    let cancelado = false;
    setUrl(null);
    setFallo(false);

    // Del caché compartido (lib/blobs.js): una descarga por imagen aunque el
    // componente se vuelva a montar, y el caché es quien revoca las URL.
    urlDe(ruta)
      .then((creada) => { if (!cancelado) setUrl(creada); })
      .catch(() => { if (!cancelado) setFallo(true); });

    return () => { cancelado = true; };
  }, [ruta]);

  const marco = { width: ancho, height: alto, ...estilo };

  if (fallo) {
    return (
      <div
        role="img"
        aria-label={t('visual.imagen_no_disponible')}
        title={t('visual.imagen_no_disponible')}
        style={{
          ...marco,
          minHeight: alto === 'auto' ? '80px' : alto,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'var(--bg-tertiary)'
        }}
      >
        <AlertTriangle size={22} color="var(--text-muted)" />
      </div>
    );
  }

  if (!url) {
    return (
      <div
        className="esqueleto"
        style={{ ...marco, minHeight: alto === 'auto' ? '80px' : alto, borderRadius: 0 }}
      />
    );
  }

  return (
    <img
      src={url}
      alt={alt}
      onClick={onClick}
      style={{
        ...marco,
        objectFit: ajuste,
        display: 'block',
        cursor: onClick ? 'zoom-in' : 'default'
      }}
    />
  );
};

export default ImagenApi;
