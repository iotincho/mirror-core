# Laboratorio · Prototipo navegable

Propuesta visual de la sección experimental de El Espejo. Está aislada de la PWA
y del backend. Usa únicamente notas, hallazgos y tiempos de procesamiento ficticios.

## Abrir

Desde la raíz de `mirror-core`:

```sh
python3 -m http.server 5181 --bind 127.0.0.1 --directory prototypes
```

Abrir [Laboratorio](http://localhost:5181/laboratorio/).

No requiere instalar dependencias ni compilar. Hay que servir el directorio
`prototypes` completo: el logo y los enlaces a las demás secciones utilizan el
prototipo existente de `app-refresh`.

## Recorridos

- **Inicio:** encabezado compacto, ayuda a demanda, borrador resumido y ejes
  existentes. «Crear un eje» permanece accesible junto a «Tus ejes».
- **Tu mirada:** título y finalidad, con ejemplos de valores personales e ideas
  para podcast. No se expone ni se edita un prompt técnico.
- **Tus notas:** búsqueda, lectura y selección de exactamente cinco notas. La
  selección no cambia al refinar, salvo una acción explícita del usuario.
- **Prueba:** preparación y avance por nota, sin porcentajes inventados.
- **Resultados:** un grafo con interruptores independientes para notas, hallazgos
  y etiquetas sobre los mismos resultados; exploración progresiva al tocar nodos, zoom, detalle, citas y lectura del original resaltado. La vista
  Lista permite recorrer todos los resultados, incluyendo notas sin hallazgos.
- **Refinamiento:** comentario, nueva prueba, comparación con la anterior y
  bloqueo de aceptación si cambió la finalidad o la muestra sin volver a probar.
- **Aceptación:** confirmación, registro simulado de versión y eje listo para
  notas nuevas. Las notas de muestra no se incorporan a los resultados activos.
- **Eje aceptado:** exploración de resultados de ejemplo, pausa/activación y
  edición mediante un nuevo circuito de prueba y aprobación.

## Bienvenida y ayuda

La pantalla habitual empieza con «Laboratorio» y el acceso «Cómo funciona».
Se retiraron la presentación grande, la ilustración y los tres pasos permanentes.
Si hay un borrador, una tarjeta compacta permite continuarlo antes de los ejes.

Sólo si no hay ejes ni borradores y la bienvenida no se descartó, aparece una
introducción breve con «Crear mi primer eje» y «Ahora no». Empezar la creación o
posponerla guarda la decisión. Consultar ayuda no la descarta. Una visita sin
acciones tampoco la marca como completada. En este prototipo se recuerda en
`localStorage` del dispositivo; con almacenamiento bloqueado, sólo en la pestaña.
La implementación real deberá recordar la decisión por usuario.

«Cómo funciona» abre un panel desde abajo en móvil y un diálogo centrado en
escritorio. Tiene tres apartados desplegables: «Qué es un eje», «Probar y ajustar»
y «Explorar los resultados». Se puede abrir en cualquier visita y cerrar con
Escape, el botón de cierre o «Entendido», restaurando el foco al acceso de ayuda.

Para comparar los estados, abrir el botón de escenarios junto a «PROTOTIPO»:
**Primera visita** restablece la bienvenida sin ejes ni borradores;
**Un Laboratorio vacío** muestra el regreso con la bienvenida ya descartada;
**Restablecer la demostración** recupera el eje y el borrador del ejemplo.

## Un grafo con tipos de nodo que se pueden encender y apagar

Entrar en **Explorar** del eje de ejemplo o completar una prueba. La vista
**Grafo** empieza con los tres tipos encendidos. Los controles **Notas**,
**Hallazgos** y **Etiquetas** permiten combinar las capas sobre el mismo mapa.
Las referencias debajo del gráfico también son los controles: punto de color y
nombre, sin tarjetas ni contadores. El punto lleno indica un tipo visible; el
punto vacío y el texto atenuado indican un tipo oculto. Mantienen una zona táctil
de 44 px y siempre queda al menos un tipo encendido.

Los interruptores conservan la instancia de Cytoscape, las posiciones (también
las modificadas por arrastre), el zoom y el desplazamiento. El detalle de una
selección que se oculta sigue disponible, con una indicación breve. **Ordenar**
y **Ajustar a la pantalla** son acciones explícitas.

- **Todos encendidos:** nota → hallazgo → etiqueta; la primera conexión guarda
  la cita de origen y las etiquetas reúnen hallazgos de distintas notas.
- **Sin hallazgos:** las conexiones nota–etiqueta agrupan los hallazgos ocultos,
  conservando sus títulos, contenidos y citas en el detalle.
- **Sin etiquetas:** se conservan las citas entre nota y hallazgo; las conexiones
  entre hallazgos muestran las etiquetas compartidas.
- **Sin notas:** hallazgos conectados a sus etiquetas, con citas y nota de origen
  disponibles al seleccionar cada hallazgo.
- **Sólo hallazgos:** conexiones por etiquetas compartidas.
- **Sólo notas:** conexiones por etiquetas compartidas en sus hallazgos, con las
  evidencias separadas por nota.
- **Sólo etiquetas:** conexiones entre etiquetas que aparecen juntas en un mismo
  hallazgo, con acceso a ese hallazgo y su cita.

Las conexiones resumidas se dibujan con líneas punteadas y conservan referencias
exactas a los hallazgos que las justifican. Compartir una etiqueta no implica
expresar la misma idea. Cambiar lo visible no genera otra prueba, no modifica el
borrador y no acepta el eje. Tocar una nota agrega sus hallazgos; tocar una
etiqueta agrega los hallazgos asociados a ella. Las ramas abiertas se conservan,
sin duplicar nodos ni mover los existentes ni cambiar la cámara. No hay un botón
para expandir todo. En este prototipo la expansión usa los datos de ejemplo.

Se reutilizan Cytoscape y la iluminación vectorial de la constelación existente.
La vista **Lista** permite leer con teclado todos los hallazgos y las citas,
incluidas las notas sin resultados. Se retiró el listado auxiliar «Elementos y
conexiones» del pie del grafo.

El botón de escenarios, junto a «PROTOTIPO», permite abrir el espacio vacío,
simular una nota pendiente recuperable, vencer una prueba y restablecer el ejemplo.

## Qué se conserva

El borrador, los ejes aceptados y su pausa se guardan en `localStorage`, con una
clave exclusiva de esta demostración. El historial de pruebas vive en memoria;
al recargar se retoma el borrador y se puede volver a probar. Si el almacenamiento
local está bloqueado, el recorrido sigue funcionando durante la sesión y se
informa que el borrador permanece en la pestaña.

No se leen datos de usuario, no hay solicitudes a una API ni servicios externos,
y no se implementa generación o extracción real. Los comentarios producen
variaciones predeterminadas de los hallazgos para evaluar el recorrido visual.

## Dirección visual

- Conserva los colores y tipografías actuales: petróleo, marfil, salvia y ámbar;
  serif editorial en títulos y sistema en formularios y navegación.
- Diseño desde 320 px: navegación inferior con cuatro secciones, columnas
  apiladas, campos de 16 px y controles de al menos 44 px. En escritorio utiliza
  barra lateral, formularios con ayuda lateral y grafo con detalle al costado.
- En un eje aceptado, «Sobre este eje» empieza cerrado y despliega la finalidad
  y los datos de aplicación; el título sigue siempre visible. La intención
  completa se consulta a demanda para dar espacio a los resultados.
  Los detalles técnicos del backend quedan fuera del recorrido.
- Diálogos con altura restringida y scroll propio, cierre con Escape, foco
  contenido y restauración al cerrar; evidencia disponible sin depender del grafo.
- Respeta `prefers-reduced-motion`. La navegación y el foco permanecen disponibles
  al usar teclado. Los gráficos tienen nombres accesibles y alternativa en Lista.

## Validación

`verify.cjs` recorre el prototipo con Playwright/Chromium. Se puede ejecutar con
un servidor ya levantado y Playwright disponible:

```sh
node prototypes/laboratorio/verify.cjs
node prototypes/laboratorio/verify-graphs.cjs
```

Si Playwright o Chromium están en otra ubicación, se pueden indicar
`PLAYWRIGHT_MODULE`, `CHROME_PATH` y `PROTOTYPE_URL`. Estas dependencias son sólo
para revisión; no forman parte del prototipo.

La revisión automatizada comprueba navegación, límites de selección, citas
literales, lectura, grafo/lista, refinamiento, pruebas anteriores, bloqueo de
aceptación desactualizada, aceptación, pausa y recarga, nueva versión, fallo
parcial, vencimiento, espacio vacío, ausencia de solicitudes externas y de errores
JavaScript. También comprueba overflow y tamaño de controles en varios anchos.

Las capturas se inspeccionan visualmente y se guardan en `screenshots/`, junto con
los reportes `validation.json` y `graph-validation.json`. La revisión de grafos
comprueba las siete combinaciones, procedencia de cada relación, citas literales,
lectura del original, protección del último tipo activo, teclado, arrastre y
conservación de posiciones y cámara sobre una misma instancia del grafo. También
verifica controles de al menos 44 px entre 320 y 1440 px.
No se verificó en un teléfono físico ni como PWA
instalada; no se afirma una integración con el backend.

## Capturas

- [Inicio · escritorio](screenshots/inicio-desktop.png)
- [Inicio · móvil](screenshots/inicio-mobile-viewport.png)
- [Bienvenida · móvil](screenshots/bienvenida-mobile.png)
- [Bienvenida · escritorio](screenshots/bienvenida-desktop.png)
- [Ayuda desplegable · móvil](screenshots/ayuda-mobile.png)
- [Regreso sin ejes · móvil](screenshots/regreso-vacio-mobile.png)
- [Describir la mirada · móvil](screenshots/intencion-mobile.png)
- [Elegir las notas · móvil](screenshots/muestra-mobile.png)
- [Resultados · escritorio](screenshots/resultados-desktop.png)
- [Resultados · móvil](screenshots/resultados-mobile.png)
- [Ideas de podcast · escritorio](screenshots/podcast-desktop.png)
- [Grafo con controles de tipos · escritorio](screenshots/grafo-capas-desktop.png)
- [Grafo con controles de tipos · móvil](screenshots/grafo-capas-mobile.png)
- [Hallazgos ocultos · escritorio](screenshots/grafo-capas-sin-hallazgos-desktop.png)
- [Hallazgos ocultos · móvil](screenshots/grafo-capas-sin-hallazgos-mobile.png)

El alcance funcional de referencia está en el
[diseño del backend](../../docs/personal-axes-backend-design.md) y el
[plan de implementación](../../docs/personal-axes-backend-implementation-plan.md).
