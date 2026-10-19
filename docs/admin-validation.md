# Validación de administración — 2026-10-16

Registro por entrega. Las primeras validaciones usaron datos aislados; la puesta
en marcha del workspace, documentada al final, sí migró la base local respaldada.

- Core, suite sin integración: 272 pruebas aprobadas, 6 omitidas por sus condiciones existentes. Avisos deprecados de Sentry sin errores.
- Integración PostgreSQL 17 aislada: 7 pruebas aprobadas, incluyendo migración desde 20261015_10, conservación de sesiones y fechas históricas null.
- Mirror-admin: lint, tipos, 12 pruebas, build y comprobación de ausencia de fixtures en bundle correctos.
- Mirror-pwa: lint, build y suite completa de 24 archivos de pruebas correctos; incluye foreground, frecuencia, limpieza de listeners y fallos de actividad silenciosos.
- Ruff y git diff --check correctos para los cambios de esta entrega.
- Chrome headless: panel consumiendo por HTTP datos persistidos en PostgreSQL de prueba, cobertura y fecha de inventario, búsqueda, detalle y Dashboard móvil sin desbordamiento ni errores JavaScript. No se interceptaron respuestas de la API ni se usaron fixtures del frontend en esa prueba.
- La API usa transacciones PostgreSQL de lectura y la serie diaria se agrega en SQL, con hasta 30 filas. No se le montó el directorio de originales en la prueba.
- La base configurada en el checkout no era alcanzable y WORKSPACES_PATH no existía. La conexión a datos de la plataforma requiere configurar el destino según admin-lan.md.
- Se detuvieron los procesos HTTP/Vite de prueba y se eliminó el contenedor PostgreSQL desechable al finalizar.

Capturas de la población de prueba (no usuarios reales): `/tmp/mirror-admin-stage2-dashboard.png`, `/tmp/mirror-admin-stage2-account.png`, `/tmp/mirror-admin-stage2-mobile.png`.

Las métricas de incorporación derivan de los originales indexados y sus receipts; no reconstruyen notas históricas eliminadas antes del primer inventario sin evidencia durable. La actividad de acceso empieza en la primera observación con medición habilitada. No hay verificación de dispositivos físicos, DNS/TLS/LAN de destino, publicación de imágenes o producción.

## Tercera entrega — 2026-10-17

- Construcción real de Dockerfile.prod de core y admin correcta. El frontend se compila dentro de la imagen y se comprueba la ausencia de fixtures.
- Runtime de mirror-admin sin root, con raíz de solo lectura y temporales en tmpfs, sirviendo UI y proxy HTTP.
- Integración Docker desechable: migración SQL, usuario/documento de prueba, sincronización desde originales y dashboard/listado servidos por la API real.
- Gateway Nginx real con upstreams públicos simulados: bloqueo de rutas administrativas (incluido segmento codificado), preservación de API y entrega SSE. Hosts administrativos desconocidos rechazados.
- Verificados puertos, redes separadas, ausencia de montaje de contenido en admin-api y montaje de solo lectura en admin-sync.
- Suite de mirror-deploy: 9 pruebas aprobadas de composición, herencia de imagen/configuración, aislamiento y orden de despliegue.
- Workflows de mirror-admin validados con actionlint. Publicación preparada para PRs fusionados a main; no se ejecutó publicación ni configuración remota.
- El proyecto Docker de integración y sus volúmenes se eliminan al finalizar. No se usaron datos ni contenedores existentes de la plataforma.

La integración es local y usa hosts permitidos por HTTP. No demuestra acceso desde otro dispositivo, DNS/firewall del destino ni publicación/despliegue real. La imagen administrativa del Compose principal conserva un placeholder explícito hasta contar con un tag publicado y revisado.

## Aceptación del destino LAN — preparación 2026-10-17

- Comando `mirror-deploy/scripts/check_admin_lan.py` validado contra UI compilada, API real, sincronizador y PostgreSQL desechables, además del gateway público con upstreams simulados.
- Suite de mirror-deploy ampliada a 17 pruebas: incluye inventario incompleto/vencido, campos privados inesperados, caché faltante, bloqueo público, redirects y orígenes inválidos. Solo se realizan GET y no se imprimen cuerpos ni identidades de cuentas.
- La actividad deshabilitada y los datos históricos parciales siguen siendo válidos; si se omite el origen público se informa que su verificación está pendiente.
- No hubo conexiones a datos reales. El destino LAN no está definido y el workspace no tiene servicios Docker en ejecución ni `.env` de despliegue.
- Variables/secrets de publicación siguen sin verificar: las consultas GitHub disponibles devolvieron 403/404. No se interpretó esto como prueba de que falten las credenciales de CI.

## Puesta en marcha autorizada en esta máquina — 2026-10-17

- Configuración privada `.env` (0600, ignorada por Git/Docker), servicios administrativos en `docker-compose.yml` y helper `admin-local.sh` que selecciona únicamente servicios administrativos/PostgreSQL.
- Imágenes `mirror-core:admin-workspace` y `mirror-admin:admin-workspace` construidas desde el workspace; build del frontend y ausencia de fixtures verificados dentro de Docker.
- Respaldo SQL en `data/administration-backups/20261017T224729Z-before-administration.dump`, verificado con `pg_restore --list`; migración local de `20261015_10` a `20261016_11` correcta.
- Inventario completo: 3 cuentas, 22 documentos, cero fallos; repetido por el sincronizador sin duplicados.
- Checks HTTP por 127.0.0.1:8081 y 192.168.0.17:8081 correctos. Host desconocido rechazado; PostgreSQL publicado únicamente en 127.0.0.1:5432.
- Runtime inspeccionado: admin-api sin montaje de originales ni puerto al host; admin-sync con datos en solo lectura; servicios administrativos sin secretos de proveedores/túnel.
- Chrome headless: dashboard compilado con inventario local, listado/detalle de usuarios, móvil 390 px sin desbordamiento, foco de teclado y cero errores JavaScript. Capturas desktop/móvil inspeccionadas. Navegador integrado no disponible.
- Suite mirror-deploy ampliada a 19 pruebas, incluidas herencia/configuración mínima del Compose local, reutilización de volúmenes y bindings privados.
- Quedan en ejecución exclusivamente PostgreSQL y los tres servicios administrativos. PWA/API pública, workers, proveedores y Cloudflare siguen detenidos. No se tocaron originales ni configuración externa de DNS/túnel/registry.

No se comprobó acceso desde otro dispositivo ni firewall de la LAN. La actividad
sigue deshabilitada y el histórico de llegadas de notas es parcial; se muestran
valores desconocidos donde corresponde. No se verificó un origen público activo
en este arranque porque gateway/túnel permanecen detenidos.


## Integración en el Compose principal

A pedido del usuario, los servicios administrativos se integraron en
`docker-compose.yml` tanto del workspace como de mirror-deploy, bajo el perfil
`admin-lan`. Se eliminaron los archivos Compose administrativos separados. El
workspace usa un único `.env` para la interpolación y mantiene PostgreSQL y los
volúmenes existentes del proyecto `mirror-core`. El despliegue detiene también
los lectores/sincronizador administrativos antes de migrar, incluso si el perfil
no se incluyó en esa invocación. El perfil se habilita explícitamente para volver
a arrancarlos durante una actualización completa.
