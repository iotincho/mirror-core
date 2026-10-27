# Composición y procesos

- `bootstrap` construye, conecta y cierra recursos; las reglas y recorridos viven
  en core, casos de uso y adaptadores. Inyectar configuración tipada y reutilizar
  factories y registros existentes, sin añadir selectores paralelos.
- API pública, administración, worker y dispatcher tienen ciclos de vida propios.
  Conservar configuraciones compartidas y cierre de clientes por proceso.
- Un cambio de entrypoint afecta Compose, imagen, scripts y `mirror-deploy`.
  Revisar consumidores y compatibilidad de despliegue antes de retirar rutas;
  documentar orden de actualización y comprobar la imagen sin acceder a datos.
- No cambiar versiones de workflows ni configuración aceptada al mover código.
  Ver [chequeos e inventario](../../docs/development/architecture-checks.md).
