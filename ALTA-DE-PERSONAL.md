# Dar de alta a los 300

Guía de la carga inicial de personal. No es documentación de código: es el
procedimiento para el día que se le abra el portal a la planta.

---

## El problema, en una línea

Crear 300 cuentas es una consulta. **Que 300 personas se pongan su contraseña sin
que TI toque ninguna** es el problema de verdad.

Dos cosas lo complican, y las dos son de planta, no de software:

- **La mayoría no tiene correo corporativo.** Por eso la llave de acceso es el
  número de empleado y el correo es opcional. Nada del portal da por hecho que
  una persona tiene correo.
- **Buena parte de la plantilla lleva años aquí y no recuerda cuándo entró.** Por
  eso los datos de verificación son el **número de EPP** y la **fecha de
  nacimiento**, no la fecha de ingreso. Los cuatro dígitos con los que saca su
  equipo de protección los usa seguido; su cumpleaños se lo sabe todo el mundo. La
  fecha de ingreso **nunca se pide como segundo dato**: sería repetir el error.

---

## Las tres salidas

Ninguna sirve para todos. Están pensadas para usarse juntas, en este orden.

### A · Se activa sola, con dos datos que ya se sabe

**Para quien puede solo.** Entra al portal, pone su número de empleado, su número
de EPP y su fecha de nacimiento, y crea su contraseña. No hay nada que repartir ni
que recordar.

Es la que resuelve el grueso de los 300. Requisito: que los dos datos vengan en el
archivo de RH.

> **Por qué dos y no uno.** Con un solo dato, cualquiera que viera la lista de RH
> podría activar cuentas ajenas. Con dos, tiene que conocer dos cosas distintas de
> esa persona en concreto. No hay crédito parcial: acertar uno de dos no sirve de
> nada.
>
> Aun así, no es tan fuerte como un código entregado en mano, y conviene saberlo.
> Lo que lo contiene: sirve **una sola vez**, solo mientras la cuenta está
> pendiente, solo dentro de la ventana de activación, y hay freno de 6 intentos
> por cada 10 minutos.
>
> Si a alguien solo se le capturó un dato, el portal se lo pide y ya —no se puede
> exigir lo que nadie registró—, pero esa cuenta sale **marcada en amarillo** en el
> panel para que TI le pida a RH el número de EPP que falta.

### B · Con código, repartido por el supervisor

**Para cuando se quiere algo más fuerte, o para altas sueltas.** Se genera un
código de un solo uso por persona.

Lo que hace esto viable es que **los códigos se bajan por área**: TI no entrega
300 papelitos, le pasa a cada supervisor los diez o veinte de su gente. El
reparto se vuelve ~20 sobres.

### C · En mostrador, con la persona enfrente

**Para quien no recuerda nada y para quien nunca va a recibir un papelito.**
En el panel de Personas, botón **«Activar aquí»**: TI comprueba el gafete, abre
la activación y **le gira la pantalla para que la persona teclee su contraseña**.
TI no la ve ni la puede recuperar después.

Es la más segura de las tres, porque la identidad la comprueba un humano. Y es la
que hay que tener lista el día del arranque: siempre va a haber gente para la que
A y B no funcionen.

> **Recomendación:** una estación en el comedor durante la semana de arranque, en
> los cambios de turno. Con eso se resuelve en tres días lo que por correo no se
> resolvería en un mes.

---

## El procedimiento

### 1. Pedirle el archivo a RH

Lo que traiga. No hace falta que lo reformateen.

Lo mínimo: **número de empleado** y **nombre**. Muy recomendable: **número de
EPP** y **fecha de nacimiento** (habilitan la salida A, y juntos la vuelven
razonablemente segura) y **área** (habilita el reparto por supervisor de la salida
B). El correo, quien lo tenga.

El portal lee CSV separado por comas o por punto y coma, en UTF-8 o en la
codificación que exporta Excel en Windows, con fechas `15/07/2022` o `2022-07-15`.

### 2. Revisar antes de importar

**Personas → Importar desde archivo → Revisar archivo.**

Si los encabezados no se reconocen —"CLAVE_TRAB", "F_NAC", lo que sea— el portal
**no rechaza el archivo**: enseña una pantalla para decirle qué columna es cuál,
ya precargada con lo que dedujo. Se revisa y se confirma.

La vista previa dice cuántas filas entran, cuáles chocan con alguien ya
registrado, cuántas no traen correo y cuántas no traen fecha de nacimiento. **Las
filas con problema se omiten; las demás sí entran.**

### 3. Elegir cómo va a entrar la gente

- **Modo verificación** (salida A) para la carga grande. Ahí se elige qué dato
  **no puede faltarle a nadie**; si a alguna fila le falta, **el archivo se
  rechaza completo** — a propósito: importar a medias dejaría gente sin poder
  entrar y nadie se enteraría hasta que reclame.
- **Modo código** (salida B) cuando se prefiere repartir.

### 4. Repartir, si aplica

Si se eligió código: **descargar los códigos ahora**. Se muestran una sola vez;
después hay que regenerarlos uno por uno. Con la descarga por área, cada
supervisor recibe solo lo suyo.

### 5. Poner el mostrador

Para el resto. En el panel, las cuentas sin ningún dato registrado salen marcadas
**«Sin fecha registrada»**: esa es la lista de quién va a necesitar mostrador. Las
que quedaron con uno solo salen marcadas **«Un solo dato»**.

---

## Antes de anunciar el portal

- [ ] **TLS activado y el certificado instalado en los equipos.** Si el navegador
      avisa el primer día, las 300 personas concluyen que el portal no sirve.
      Ver `DESPLIEGUE.md` §2.8.
- [ ] **`JWT_SECRET` propio** en el `.env`. Cambiarlo cierra las sesiones, así que
      va antes de la carga, no después.
- [ ] **Respaldo probado.** `./scripts/respaldo.sh` y una restauración de prueba.
      Un respaldo que nunca se restauró no se sabe si sirve.
- [ ] **Los números provisionales corregidos.** Las cuentas que existían antes del
      cambio se quedaron con un `TMP-xxxxx`; salen marcadas en amarillo en el
      panel y se corrigen con un clic.
- [ ] **Decidir la ventana de activación.** Pasado ese plazo, lo que siga sin
      activar necesita código o mostrador. Acota el riesgo de la salida A.

---

## Lo que TI nunca hace

**Conocer la contraseña de alguien más.** Ni al dar de alta, ni al restablecer,
ni en el mostrador. En los tres caminos la escribe la persona.

Si alguien pide "ponme una y me la dices", la respuesta es restablecer y que la
ponga la persona. No es burocracia: es lo que hace que un acceso en la bitácora
signifique algo.
