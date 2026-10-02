# Publicación de imágenes de producción

El workflow `Publish production image` se ejecuta únicamente cuando un pull request
queda mergeado en `main`. Construye `Dockerfile.prod`, publica la imagen en Docker
Hub y crea un tag Git apuntando al commit de merge.

## Configuración requerida

En GitHub, abrir **Settings → Secrets and variables → Actions** y definir:

| Tipo | Nombre | Valor |
| --- | --- | --- |
| Variable | `DOCKERHUB_IMAGE` | Repositorio completo, por ejemplo `iotincho/el-espejo-core` |
| Secret | `DOCKERHUB_USERNAME` | Usuario de Docker Hub que posee o puede publicar en el repositorio |
| Secret | `DOCKERHUB_TOKEN` | Access token de Docker Hub con permiso de lectura y escritura |

El token reemplaza la contraseña de Docker Hub y no debe guardarse como variable ni
en el repositorio.

## Versionado

Las imágenes se publican con un tag inmutable `YYYY.MM.DD-NNN`, por ejemplo
`2026.10.02-001`, y el mismo tag se crea en Git. También se actualiza `latest` como
referencia de conveniencia. Un despliegue de producción debe indicar siempre el tag
versionado, nunca `latest`.

La PWA se publica como estáticos compilados. El runtime que la despliegue debe
enrutar `/api/*` al backend: la imagen de la PWA no contiene ni conoce las
credenciales del backend.
