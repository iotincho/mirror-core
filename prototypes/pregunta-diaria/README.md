# Prototipo: pregunta diaria

Experiencia progresiva con una sola pregunta visible. Los controles «Suave», «Un poco más» y «Profundizar» cambian su profundidad sobre un mismo tema, sin desplegables. «Otra pregunta» cambia a otro tema ficticio.

El flujo pasa de la invitación a la respuesta y vuelve al inicio. Después de responder, aparece un panel inferior de feedback opcional sobre el inicio, sin pantalla de felicitación o cierre. Se puede cerrar con la cruz, «En otro momento», Escape o tocando fuera. «Sobre este tema…» despliega opciones dentro del mismo panel. Si se elige «Hoy paso», se vuelve al inicio sin pedir feedback. Al avanzar, la vista anterior se oculta. Volver a la pregunta o cambiar de profundidad conserva el borrador. La captura usa un único botón contextual: micrófono sin texto, enviar con texto. El inicio permite abrir escritura libre o volver a la pregunta diaria; ambos borradores se conservan por separado en memoria. El feedback queda vinculado a la pregunta respondida, aunque luego se escriba una nota libre.

Desde la raíz de `mirror-core`:

```sh
python3 -m http.server 5181 --bind 127.0.0.1 --directory prototypes
```

Abrir `http://127.0.0.1:5181/pregunta-diaria/`. También se puede abrir `index.html` directamente.

No usa API, IA, sesión, almacenamiento ni notas reales. La voz no se ejecuta y el envío y feedback son simulados. Texto y selecciones solo viven en memoria hasta cerrar o recargar la página. La PWA real requiere sesión y conexión; sus notas pueden quedar pendientes de sincronizar según su flujo existente. El prototipo no implementa reactivación de temas.
