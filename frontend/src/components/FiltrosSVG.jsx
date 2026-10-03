/**
 * Los filtros SVG que usa el portal, definidos una sola vez.
 *
 * Un `filter: url(#algo)` de CSS necesita que ese `#algo` exista en el
 * documento. Cuando el filtro vivía dentro del login, solo existía en el
 * login — y en cuanto los botones del resto del portal quisieron la misma
 * gota, se quedaron sin filtro y sin efecto.
 *
 * Se monta una vez en `App`, junto al fondo. El `<svg>` se esconde por tamaño
 * y no con `display: none`, que desactivaría los filtros de dentro.
 */
export default function FiltrosSVG() {
  return (
    <svg className="filtros-svg" aria-hidden="true" focusable="false">
      <defs>
        {/* La fusión. Desenfoca y sube el contraste del canal alfa: dos
            formas que se acercan comparten una zona de alfa intermedia, y la
            matriz la vuelve opaca. Ese sellado es lo que hace que la gota de
            un botón parezca líquido y no una caja que se estira.

            El mismo filtro con dos radios: uno corto para los botones y otro
            largo para las esferas del fondo, que son mucho más grandes y
            necesitan más difuminado para llegar a tocarse. */}
        {/* **La región importa.** Un filtro recorta a su región, y por defecto
            esa región es solo un 10 % mayor que el elemento. La gota crece un
            32 % de alto al pasar el ratón, así que con la región por defecto
            el abultamiento se cortaba justo donde empezaba a notarse — y eso
            hacía parecer que la animación casi no existía. Con margen de
            sobra, el bulto se ve entero y el desenfoque tiene sitio. */}
        <filter id="fundir-boton"
          x="-35%" y="-45%" width="170%" height="190%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="8" result="difuso" />
          <feColorMatrix
            in="difuso"
            mode="matrix"
            values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 19 -9"
            result="fundido"
          />
          <feComposite in="SourceGraphic" in2="fundido" operator="atop" />
        </filter>

        <filter id="fundir">
          <feGaussianBlur in="SourceGraphic" stdDeviation="12" result="difuso" />
          <feColorMatrix
            in="difuso"
            mode="matrix"
            values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 19 -9"
            result="fundido"
          />
          <feComposite in="SourceGraphic" in2="fundido" operator="atop" />
        </filter>
      </defs>
    </svg>
  );
}
