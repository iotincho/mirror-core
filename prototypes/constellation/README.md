# Constelación: prototipo ejecutable

Vista previa aislada construida con React 19 y Cytoscape.js 3.33.1. Reutiliza
copias de `index.css`, `App.css` y la marca de la PWA actual. No modifica la PWA
ni llama a la API: los 200 documentos y sus conexiones son sintéticos, para
validar interacción y límites de visualización, no la calidad de los vínculos.

## Ejecutar

Las dependencias de React/Vite se resuelven mediante el enlace `node_modules`
al checkout local de `mirror-pwa`. Desde este directorio:

```sh
node_modules/.bin/vite build
python -m http.server 5174 --bind 127.0.0.1 --directory dist
```

Abrir http://localhost:5174. Cytoscape está incluido localmente para que la
vista previa no dependa de un CDN. Su código está bajo licencia MIT:
https://github.com/cytoscape/cytoscape.js/blob/v3.33.1/LICENSE

## Probar

1. Empezar desde una nota. La primera vista incluye hasta 10 vecinos directos.
2. Seleccionar una conexión para leer las citas de ambos documentos.
3. Seleccionar una nota y agregar hasta 10 vecinos por vez.
4. Al llegar a 40 notas, centrar el grafo en otra nota para seguir explorando.
5. Filtrar por relación. Cambiar a Lista, que expone los mismos vínculos.
6. Reducir la ventana a tamaño móvil y verificar scroll y controles.

Las métricas en pantalla miden creación/distribución, no FPS ni rendimiento
completo. No se validaron gestos táctiles ni capturas: el navegador integrado
no estuvo disponible durante la construcción. El build sí pasó, y un chequeo
headless del layout concentric produjo posiciones válidas para 40 nodos.

## Decisiones reales de librería

- Cytoscape dibuja el grafo en canvas y ofrece selección, zoom, desplazamiento,
  estilos de flechas y layouts integrados. Los nodos son figuras dibujadas, no
  componentes HTML/React; el detalle rico se muestra fuera del canvas.
- El layout concentric agrupa alrededor de la nota raíz. Al expandir se
  redistribuye el vecindario completo; preservar posiciones es una mejora
  pendiente. No se promete eliminar cruces automáticamente.
- Los datos del ejemplo están en memoria. En integración real, un endpoint de
  vecindario debe limitar y paginar en servidor. El límite visual de este
  prototipo no constituye una implementación de paginación backend.
- Las aristas de ida/vuelta se agruparán por link_id. Los vínculos temporales
  conservarán orientación; los simétricos se mostrarán sin flechas.
- El prototype cuenta vínculos conceptuales entre claims, no fusiona todos los
  vínculos de dos documentos: si tienen relaciones distintas, hay varias líneas.

React Flow también permite tarjetas HTML personalizadas e integra bien con
React, pero requiere otro motor para layout automático. Para esta exploración
de redes se eligió Cytoscape; no se realizó una comparativa de rendimiento.

Documentación consultada:
https://js.cytoscape.org/
https://reactflow.dev/learn/layouting/layouting
