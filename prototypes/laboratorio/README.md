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

- **Inicio:** crear un eje, continuar un borrador local y explorar un eje aceptado.
- **Tu mirada:** título y finalidad, con ejemplos de valores personales e ideas
  para podcast. No se expone ni se edita un prompt técnico.
- **Tus notas:** búsqueda, lectura y selección de exactamente cinco notas. La
  selección no cambia al refinar, salvo una acción explícita del usuario.
- **Prueba:** preparación y avance por nota, sin porcentajes inventados.
- **Resultados:** selector «Por etiquetas / Por hallazgos / Etiquetas y hallazgos» sobre los mismos
  resultados; expansión, zoom, detalle, citas y lectura del original resaltado. La vista
  Lista permite recorrer todos los resultados, incluyendo notas sin hallazgos.
- **Refinamiento:** comentario, nueva prueba, comparación con la anterior y
  bloqueo de aceptación si cambió la finalidad o la muestra sin volver a probar.
- **Aceptación:** confirmación, registro simulado de versión y eje listo para
  notas nuevas. Las notas de muestra no se incorporan a los resultados activos.
- **Eje aceptado:** exploración de resultados de ejemplo, pausa/activación y
  edición mediante un nuevo circuito de prueba y aprobación.

## Comparar los tres grafos

Entrar en **Explorar** del eje de ejemplo o completar una prueba. En la vista
**Grafo**, el selector permite alternar entre estas tres proyecciones:

- **Por etiquetas:** nodos de nota y etiqueta. Cada conexión guarda la colección
  de hallazgos de esa nota bajo esa etiqueta. Al tocarla se muestran por separado
  los títulos, contenidos y citas; el hallazgo completo no desaparece al agrupar.
- **Por hallazgos:** nodos de nota y hallazgo. La conexión nota–hallazgo contiene
  la cita de origen. Las conexiones entre hallazgos muestran las etiquetas que
  comparten; no se introducen nodos de etiqueta en esta vista ni se afirma que
  compartir una etiqueta signifique expresar la misma idea.
- **Etiquetas y hallazgos:** nodos de nota, hallazgo y etiqueta. El recorrido
  nota → hallazgo → etiqueta conserva la cita en la primera conexión. Cada etiqueta
  es un nodo compartido por sus hallazgos; al tocarla se puede explorar el grupo.
  Tocar la conexión hallazgo–etiqueta permite leer el hallazgo y su evidencia.

Las tres usan la misma muestra y los mismos hallazgos. Cambiar la vista no genera
otra prueba, no modifica el borrador y no acepta el eje. Se empieza por un grupo
para mantener legibilidad; **Más conexiones** permite abrir el conjunto.

Se reutilizan Cytoscape y la iluminación vectorial de nodos de la constelación
existente, con arrastre de nodos, desplazamiento y zoom reales. Seleccionar una
conexión actualiza el detalle sin reconstruir el grafo ni cambiar su cámara.
**Elementos y conexiones** ofrece las mismas selecciones con controles de teclado.

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
- La intención completa se consulta a demanda para dar espacio a los resultados.
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
comprueba tipos de nodos, agrupación sin perder hallazgos, citas en las conexiones,
etiquetas compartidas, recorrido nota–hallazgo–etiqueta, cambio de vista sin modificar datos, selección por canvas,
conservación de cámara y controles de al menos 44 px entre 320 y 1440 px.
No se verificó en un teléfono físico ni como PWA
instalada; no se afirma una integración con el backend.

## Capturas

- [Inicio · escritorio](screenshots/inicio-desktop.png)
- [Inicio · móvil](screenshots/inicio-mobile-viewport.png)
- [Describir la mirada · móvil](screenshots/intencion-mobile.png)
- [Elegir las notas · móvil](screenshots/muestra-mobile.png)
- [Resultados · escritorio](screenshots/resultados-desktop.png)
- [Resultados · móvil](screenshots/resultados-mobile.png)
- [Ideas de podcast · escritorio](screenshots/podcast-desktop.png)
- [Grafo por etiquetas](screenshots/grafo-etiquetas-desktop.png)
- [Grafo por hallazgos](screenshots/grafo-hallazgos-desktop.png)
- [Grafo con etiquetas y hallazgos](screenshots/grafo-completo-desktop.png)
- [Grafo por etiquetas · móvil](screenshots/grafo-etiquetas-mobile.png)
- [Grafo por hallazgos · móvil](screenshots/grafo-hallazgos-mobile.png)
- [Grafo con etiquetas y hallazgos · móvil](screenshots/grafo-completo-mobile.png)

El alcance funcional de referencia está en el
[diseño del backend](../../docs/personal-axes-backend-design.md) y el
[plan de implementación](../../docs/personal-axes-backend-implementation-plan.md).
