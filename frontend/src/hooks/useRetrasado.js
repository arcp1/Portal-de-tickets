import { useEffect, useState } from 'react';

/**
 * El valor, pero solo cuando lleva `ms` sin cambiar.
 *
 * Para lo que reacciona a lo que se escribe y es caro de pintar: no tiene
 * caso redibujarlo en cada tecla si de todas formas espera a que la persona
 * haga una pausa para hacer algo.
 */
export default function useRetrasado(valor, ms) {
  const [retrasado, setRetrasado] = useState(valor);
  useEffect(() => {
    const reloj = setTimeout(() => setRetrasado(valor), ms);
    return () => clearTimeout(reloj);
  }, [valor, ms]);
  return retrasado;
}
