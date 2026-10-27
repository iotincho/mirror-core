"""Connect the public mutation origin policy; administration has a separate policy."""

from src.adapters.access.api.public.origin import same_origin
from src.bootstrap.settings import get_settings

require_same_origin = same_origin(lambda: get_settings().web_push_allowed_origins)
