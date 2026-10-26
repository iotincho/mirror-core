# Migraciones SQL

- No editar revisiones ya aplicadas: crear otra revisión Alembic y comprobar un
  único head. Mantener nombres y estilo del directorio `versions/`.
- Alembic administra SQL; esquema ArcadeDB y migración de archivos/grafo pertenecen
  a `src/bootstrap/graph_schema.py` y `src/use_cases/maintenance/` respectivamente.
- Explicitar defaults/backfill/nullable para filas existentes y compatibilidad
  entre API, workers y dispatcher. No introducir llamadas a proveedores.
- Probar upgrade y recuperación en PostgreSQL aislado. Revisar downgrade y señalar
  pérdida de datos irreversible. No aplicar a un entorno con usuarios para validar.
- Si cambia el orden operativo actualizar [implementación](../docs/development/implementation.md)
  y el procedimiento específico; no modificar `deploy.sh` por conveniencia del test.
