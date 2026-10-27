# Persistencia PostgreSQL

- Implementar puertos y transacciones del área; devolver hechos y estados tipados,
  no modelos ORM vinculados a la sesión hacia los casos de uso.
- Conservar ownership, atomicidad, orden de locks y límites transaccionales. En
  procesamiento, job, eventos y outbox se coordinan según el contrato vigente;
  no trasladar decisiones de retry al broker.
- Ante cambios de esquema crear una revisión nueva siguiendo
  [migraciones](../../../../migrations/AGENTS.md). Probar carreras, rollback y
  recuperación relevantes con PostgreSQL desechable; mocks no validan locks.
- Leer [runtime](../../../../docs/processing-runtime.md) o el contrato específico
  antes de cambiar sus garantías; no registrar datos personales ni credenciales.
