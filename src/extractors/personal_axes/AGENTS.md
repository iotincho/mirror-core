# Compatibilidad de fixtures de ejes

- Implementación vigente: `../../core/extractors/personal_axes/`,
  `../../use_cases/personal_axes/` y sus adaptadores. Consultar el
  [mapa](../../../docs/development/repository-map.md) y el
  [contrato](../../../docs/personal-axes-api.md).
- Esta carpeta conserva sólo fachadas de errores/diccionarios consumidas por
  fixtures y `../../bootstrap/personal_axes_compat.py`. No agregar lógica ni SQL.
- Migrar esos consumidores y retirar las fachadas en la etapa 5 del
  [plan](../../../docs/development/personal-axes-migration-plan.md).
