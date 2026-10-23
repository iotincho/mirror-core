# Recuperar un audio que falló por falta de ffmpeg

Ubicaciones vigentes: puertos en `src/core/audio/ports.py`, coordinación en
`src/use_cases/audio/`, originales/preparación en `src/adapters/storage/filesystem/`
y cliente de transcripción en `src/adapters/providers/openai/transcription.py`.
`src/bootstrap/audio.py` conecta configuración, preparación y artefactos; los
imports operativos anteriores siguen disponibles. La conversión usa temporales,
conserva el original y no vuelve a transcribir si ya existe un checkpoint válido.

La imagen publicada por CI se construye con `Dockerfile.prod`. Tanto esa imagen
como la de desarrollo requieren ffmpeg con libmp3lame para normalizar WebM a MP3.

Antes de reintentar, publicar y desplegar la imagen corregida en **todas** las
réplicas de `processing-worker`. Comprobar cada réplica desde el servidor:

```bash
for worker_id in $(docker compose ps -q processing-worker); do
  docker exec "$worker_id" ffmpeg -version
done
```

El error nuevo `transcription_configuration` permite reintentar mediante el
endpoint habitual o `RequestProcessing.retry`, después de corregir la imagen.

Los fallos anteriores por falta de ffmpeg quedaron registrados como
`transcription_invalid_response` con `retryable=false`. Si el traceback confirmó
`WebM transcription requires ffmpeg`, se puede rehabilitar **esa tarea concreta**
y reencolarla con este comando administrativo. Reemplazar `PROCESSING_ID` y
`AUDIO_ID` por los UUID del log; los valores siguientes son marcadores de posición.
No usar para otros errores de audio inválido.

```bash
docker compose exec -T processing-worker python - <<'PY'
import asyncio
import subprocess
from uuid import UUID, uuid4

from src.processing.models import ProcessingRecord
from src.processing.runtime import get_repository
from src.processing.workflows import worker_runtime
from src.use_cases.request_processing import RequestProcessing
from src.bootstrap.database import close_database, get_session_maker

PROCESSING_ID = UUID("00000000-0000-0000-0000-000000000001")
AUDIO_ID = UUID("00000000-0000-0000-0000-000000000002")

async def main():
    try:
        subprocess.run(
            ["ffmpeg", "-version"], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
        async with get_session_maker()() as session:
            record = await session.get(ProcessingRecord, PROCESSING_ID)
            if record is None:
                raise SystemExit("Tarea no encontrada.")
            user_id, resource_id = record.user_id, record.resource_id

        async with worker_runtime(user_id) as runtime:
            request = RequestProcessing(get_repository(), runtime)

            async def recover(session, now):
                current = await session.get(
                    ProcessingRecord, PROCESSING_ID, with_for_update=True
                )
                if (current.workflow != "audio"
                    or current.resource_kind != "audio"
                    or current.resource_id != AUDIO_ID
                    or current.user_id != user_id
                    or current.resource_deleted):
                    raise SystemExit("La tarea no corresponde al audio esperado.")
                if current.status != "failed":
                    return current
                if (current.stage != "transcription"
                    or current.error_code not in {
                        "transcription_invalid_response", "transcription_configuration"
                    }):
                    raise SystemExit("El error actual no corresponde a este procedimiento.")
                await request.repository.assert_inactive(
                    user_id, AUDIO_ID, exclude=[current.id]
                )
                current.retryable = True
                await request.retry_record(session, current, now)
                await request.resume_ancestors(session, current, now)
                return current

            result = await request.mutate(
                "retry", uuid4(), {"processing_id": str(PROCESSING_ID)},
                resource_id, recover,
            )
            print(f"processing_id={result.id} status={result.status}")
    finally:
        await close_database()

asyncio.run(main())
PY
```

La rehabilitación, el reset de intentos, el evento y el outbox se guardan en una
misma transacción, bajo el bloqueo habitual del recurso. No se cambia el audio,
su identidad ni la configuración del procesamiento. Si la tarea ya está activa
o completa, el comando muestra su estado sin reiniciarla. El dispatcher y los
workers deben estar en ejecución.

```bash
docker compose logs --since 2m -f processing-worker processing-dispatcher
```
