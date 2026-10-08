# Respaldo e importación de documentos

El respaldo JSON contiene todos los documentos originales guardados para el
usuario autenticado. Conserva `id`, `title`, `content`, `source`, `metadata`,
`created_at` y `authored_at`. Incluye textos transcritos que ya tienen documento.
No contiene identidades de cuentas, contraseñas, extracciones, archivos de audio,
estado de procesamiento ni notas que siguen sólo en el dispositivo.

## Uso desde la PWA

En **Tu material**, sincronizar primero las notas pendientes y elegir
**Descargar documentos JSON**. Guardar el archivo antes de recrear las bases.
Después de registrar/iniciar sesión en la cuenta nueva, elegir
**Importar documentos JSON** y seleccionar el respaldo. Los documentos se asignan
a esa cuenta, aunque su UUID de usuario sea diferente del anterior.

El archivo tiene un contrato `format: "el-espejo-documents"`, `version: 1`,
`exported_at` y `documents`. Límite: 25 MiB y 10.000 documentos por archivo.
El JSON descargado puede abrirse para comprobar el número de documentos y el
contenido antes del corte. El importador valida todo el archivo antes de escribir,
conserva las fechas originales y encola para cada documento el workflow durable
vigente: persistencia en el grafo y extracción de emociones y embeddings en paralelo.
La respuesta confirma la restauración de originales y la programación del pipeline;
los workers completan la extracción de forma asíncrona.

UUID idéntico con contenido/campos idénticos: se conserva, sin duplicar.
UUID idéntico con datos distintos: rechaza el archivo sin sobrescribir.
Se detectan conflictos previamente y nuevamente al adquirir el lock del documento;
se rechazan procesos activos ajenos a esta importación. No hay una transacción global
entre archivos y PostgreSQL: una interrupción puede dejar parte de los documentos ya
restaurados. Se puede reintentar el mismo archivo, incluso mientras sus trabajos
siguen activos: reutiliza la misma recepción por usuario/documento y no duplica
extracciones. Los documentos idénticos existentes también se encolan la primera vez
que se importan. El dispatcher recupera recepciones pendientes si el original ya
se guardó. Los trabajos fallidos se reintentan mediante la API de procesamiento.

API autenticada:

- `GET /documents/export`: JSON adjunto, con `Cache-Control: no-store`.
- `POST /documents/import`: multipart con campo `file`.
- Respuesta: `imported`, `existing`, `total`.

En el gateway productivo las URLs tienen prefijo `/api`. Exportar no requiere
un grafo operativo ni un workspace activo; usa los archivos originales y verifica
la pertenencia a la instancia configurada. Importar requiere un workspace activo.

## Exportación administrativa antes de recrear bases

Si no se puede iniciar la API por una migración fallida, el script
`scripts/export_document_archives.py` genera un archivo por usuario desde el
volumen de originales. Es independiente de PostgreSQL, ArcadeDB y del código
instalado en la imagen vieja. No elimina ni modifica originales.

Desde el checkout de `mirror-core`, usando el Compose productivo:

```sh
mkdir -p ./document-exports
docker compose -f ../mirror-deploy/docker-compose.yml \
  --env-file ../mirror-deploy/.env run --rm --no-deps \
  -v "$PWD/scripts/export_document_archives.py:/tmp/export_document_archives.py:ro" \
  -v "$PWD/document-exports:/exports" \
  --entrypoint python api /tmp/export_document_archives.py \
  --output /exports/antes-del-reset
```

El directorio de salida debe ser nuevo. La herramienta informa UUID de usuario
y cantidad de documentos, sin imprimir sus textos. Los archivos quedan con
permisos `600`, dentro de un directorio `700`, en
`./document-exports/antes-del-reset` del host gracias al bind mount. Con una
imagen que ejecuta como root, pueden requerir permisos administrativos para
copiarlos. Entregar a cada usuario únicamente su archivo y conservar otra copia
fuera del servidor antes de eliminar cualquier volumen/base. No se usa el
volumen original para almacenar el respaldo.

Para un directorio de originales ya copiado al host:

```sh
python scripts/export_document_archives.py \
  --root /ruta/a/workspaces --output /ruta/a/respaldos-nuevos
```

Cada archivo resultante es importable desde la PWA. Los JSON no restauran cuentas
ni archivos de audio; respaldar esos archivos aparte si se van a eliminar sus
volúmenes. No se ejecutó exportación de usuarios ni recreación de bases durante
la implementación.
