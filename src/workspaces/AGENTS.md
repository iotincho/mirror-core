# Workspaces

- `context.py` fija identidad; `dependencies.py` construye stores acotados al dueño.
  Workers reconstruyen el mismo límite desde el job, no desde payloads de clientes.
- Conservar máquina de estados, asignación estable y cifrado de credenciales.
  Un retry de provisión no debe crear otra identidad ni reactivar un suspendido.
- No exponer nombre de base, secretos o raíz del filesystem en respuestas públicas.
  No registrar el runtime o binding completo.
- Cerrar clientes y sesiones al terminar. El acceso a un workspace fallido o de
  otra instancia debe fallar explícitamente; no usar un store global de fallback.
- Verificar cuentas distintas, fallos de provisión, reintento y suspensión con
  `tests/test_workspace_dependencies.py`, `tests/test_workspaces.py` y, si cambia
  el alta, `tests/test_signup_flow.py`.
