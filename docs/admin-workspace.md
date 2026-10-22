# Administración en esta máquina

El panel corre con imágenes compiladas localmente, sin publicación en registry
ni conexión a Cloudflare. Usa los volúmenes existentes `mirror-core_postgres_data`
y `mirror-core_core_data` del proyecto Docker `mirror-core`.

Acceso configurado el 2026-10-17:

- En esta máquina: <http://127.0.0.1:8081>.
- Desde la LAN: <http://192.168.0.17:8081>.

`admin.elespejo.lan` está permitido como Host, pero no se configuró DNS ni se
modificó el archivo hosts. Se puede resolver localmente hacia `192.168.0.17`;
mientras tanto, usar la IP. Si DHCP cambia la dirección, actualizar
`ADMIN_BIND_ADDRESS` y `ADMIN_ALLOWED_HOSTS` en `.env` y volver a iniciar.
El puerto 8081 está ligado solo a loopback y a esa IP privada.

## Operación

Desde mirror-core:

```sh
./admin-local.sh status
./admin-local.sh logs
./admin-local.sh check

./admin-local.sh stop
./admin-local.sh start
```

`stop` detiene únicamente los tres servicios administrativos y conserva la base,
originales y métricas. `start` espera a PostgreSQL, migraciones y healthchecks.
El helper selecciona servicios explícitos; no arranca la PWA, API pública,
workers, ArcadeDB, RabbitMQ ni Cloudflare Tunnel. No usar `down -v` sobre el
proyecto compartido ni retirar sus volúmenes.

Para recompilar cambios del panel/API:

```sh
./admin-local.sh stop
./admin-local.sh build
./admin-local.sh start
./admin-local.sh check
```

El Compose comparte la imagen local `mirror-core:admin-workspace` entre la
migración, API y sincronizador; el frontend usa `mirror-admin:admin-workspace`.
Estos tags identifican builds de desarrollo locales, no releases publicadas.
Para futuras migraciones del core completo, seguir el procedimiento del core y
detener también los servicios administrativos antes de migrar. No actualizar
esquemas mientras haya escritores públicos de una versión anterior en ejecución.

## Configuración y datos

`.env` contiene las credenciales ya existentes de PostgreSQL y los
hosts/puertos/intervalos del panel. Está ignorado por Git y Docker y tiene permisos
0600. `.env.example` es la plantilla sin secretos. El helper usa este mismo `.env`
para la interpolación del Compose principal;
no transmite su token de túnel ni el `.env.local` general a los servicios
administrativos.

Los tres servicios administrativos están integrados en `docker-compose.yml`,
junto con el resto de la plataforma, bajo el perfil `admin-lan`. No requieren
un segundo archivo Compose ni una base independiente. El despliegue
con imágenes publicadas continúa definido en
[mirror-deploy](../../mirror-deploy/ADMIN-LAN.md).

La API no monta originales. El sincronizador monta `core_data:/data:ro` y usa
`/data/users`, la ubicación real de este entorno. Solo persiste metadatos en SQL.
Los servicios públicos y administrativos usan el mismo servicio PostgreSQL y
los mismos volúmenes `core_data`/`postgres_data` del proyecto `mirror-core`. Se
conservan los volúmenes y datos existentes; no se creó otra base. PostgreSQL
conserva su puerto 5432 para herramientas
locales, ligado únicamente a 127.0.0.1.

Antes del primer arranque se guardó y verificó el respaldo PostgreSQL:
`data/administration-backups/20261017T224729Z-before-administration.dump`.
El directorio es privado, está ignorado por Git y queda fuera del contexto Docker.
Se aplicó únicamente `20261015_10 → 20261016_11`, que agrega fecha de alta y tablas
de metadatos. No se reprocesaron notas ni se alteraron originales, contraseñas,
estados o sesiones de usuarios. Las fechas de alta históricas permanecen null.

## Alcance verificado

PostgreSQL y los tres servicios administrativos están iniciados; el inventario
inicial es de 3 cuentas y 22 documentos, con sincronización cada 30 segundos.
Los checks HTTP pasaron por loopback y por la IP privada desde esta máquina.
La actividad de accesos sigue deshabilitada y el histórico de incorporaciones
es parcial: esos indicadores muestran «Sin datos» cuando corresponde.

No hay autenticación administrativa en esta entrega. El gateway y el túnel
públicos siguen detenidos, por lo que no se verificó aislamiento contra un origen
público activo durante este arranque. Las pruebas Docker desechables anteriores
sí verificaron el proxy público. El acceso desde otro dispositivo de la LAN y sus
reglas de firewall siguen pendientes; no se modificó el firewall del sistema.


## Actualización local del 2026-10-21: Laboratorio

El panel que respondía en `127.0.0.1:8081` todavía ejecutaba imágenes del 17 de
octubre, aunque los cambios y los builds recientes ya estaban disponibles.
Se recompilaron y recrearon únicamente `admin-api` y `admin-web` con los tags
locales `mirror-core:admin-workspace` y `mirror-admin:admin-workspace`. Ambos
quedaron saludables. Se conservaron los bindings existentes de 8081 a loopback
y a la IP LAN y no se reiniciaron PostgreSQL, API pública, workers, dispatcher ni
admin-sync. No se modificaron permisos de cuentas ni se publicaron imágenes.

La base ya estaba en `20261021_16`; no fue necesario migrarla. El flag global
estaba encendido en la API pública mediante `.env.local`, pero faltaba en `.env`,
que usa el Compose administrativo. Se añadió exclusivamente
`PERSONAL_AXES_ENABLED=true` a este último para mantener el mismo valor.

Verificación sobre el servicio activo: la lista/detalle devuelve
`laboratory_enabled` y `laboratory_global_enabled=true`; Chrome recorrió
Usuarios → Ver cuenta y mostró **Laboratorio → Habilitar para esta cuenta**,
también tras recargar y en mobile, sin errores de página ni solicitudes de escritura.
Para ver el control actualizado, recargar <http://127.0.0.1:8081/#/users> y abrir
**Ver cuenta**. La habilitación se decide por cuenta desde ese interruptor.
