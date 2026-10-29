# Prototipo: pregunta diaria

Experiencia progresiva con una sola pregunta visible. Los controles «Suave», «Un poco más» y «Profundizar» cambian su profundidad sobre un mismo tema, sin desplegables. «Otra pregunta» cambia a otro tema ficticio.

El flujo tiene cuatro vistas: invitación, respuesta, cierre y feedback opcional. Al avanzar, la vista anterior se oculta. Volver a la pregunta o cambiar de profundidad conserva el borrador. La captura usa un único botón contextual: micrófono sin texto, enviar con texto.

Desde la raíz de `mirror-core`:

```sh
python3 -m http.server 5181 --bind 127.0.0.1 --directory prototypes
```

Abrir `http://127.0.0.1:5181/pregunta-diaria/`. También se puede abrir `index.html` directamente.

No usa API, IA, sesión, almacenamiento ni notas reales. La voz no se ejecuta y el envío y feedback son simulados. Texto y selecciones solo viven en memoria hasta cerrar o recargar la página. La PWA real requiere sesión y conexión; sus notas pueden quedar pendientes de sincronizar según su flujo existente. El prototipo no implementa reactivación de temas.
