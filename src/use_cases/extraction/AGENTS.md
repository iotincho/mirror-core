# Extracción

- Leer [trabajos por extractor](../../../docs/extractor-jobs.md) y el contrato de
  la capa afectada. Modelos y puertos viven en `../../core/extractors/`;
  proveedores y proyecciones, en adaptadores; su registro, en `../../bootstrap/`.
- Un extractor define su perfil y artefactos y reemplaza sólo su propia proyección.
  Cuando produce citas, validar evidencia y offsets contra el original sin
  modificar el material fuente.
- Separar extracción y persistencia: recuperar el artefacto sin instanciar ni
  volver a llamar al proveedor. Mantener identidad, versión y configuración del job.
- No agregar lógica de una familia al ejecutor genérico. Ejes es un extractor con
  instancias y versiones propias; consultar [su contrato](../../../docs/personal-axes-api.md).
- Probar recuperación sin proveedor, duplicados y aislamiento de capas; usar
  servicios aislados si cambia la atomicidad de una proyección.
