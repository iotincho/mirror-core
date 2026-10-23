"""Behavioral checks for architecture boundaries; no application or service imports."""

import json
from pathlib import Path

import pytest

from scripts.check_architecture import audit, imports_in, inventory, validate_policy


def write(root, source, text):
    path = root / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def policy(*exceptions, legacy=()):
    return {"version": 1, "legacy_files": list(legacy), "exceptions": list(exceptions)}


def exception(source, target):
    return {"source": source, "target": target,
            "reason": "Existing dependency pending migration", "remove_in": "1"}


def test_core_accepts_models_and_standard_library_without_importing_application(tmp_path):
    write(tmp_path, "src/core/documents.py", "from pydantic import BaseModel\nimport uuid\n")
    failures, edges, _, _ = audit(tmp_path, policy())
    assert not failures and len(edges) == 2


@pytest.mark.parametrize("source, text, forbidden", [
    ("src/core/model.py", "import sqlalchemy as sa", "sqlalchemy"),
    ("src/core/model.py", "def run():\n    from ..adapters import storage", "src.adapters"),
    ("src/core/model.py", "from src import use_cases", "src.use_cases"),
    ("src/use_cases/run.py", "from ..services import document_store", "src.services"),
    ("src/use_cases/run.py", "from src import adapters as storage", "src.adapters"),
    ("src/adapters/access/api/documents.py", "from sqlalchemy import select", "sqlalchemy"),
    ("src/adapters/access/api/documents.py", "import src.adapters.storage.postgres", "storage"),
    ("src/adapters/storage/postgres/documents.py", "from src.use_cases import run", "use_cases"),
    ("src/adapters/storage/postgres/one.py", "import src.adapters.storage.arcadedb", "arcadedb"),
    ("src/adapters/access/api/documents.py", "from src.bootstrap import dependencies", "bootstrap"),
])
def test_forbidden_dependencies_fail_including_relative_and_local_imports(
    tmp_path, source, text, forbidden
):
    write(tmp_path, source, text)
    failures, *_ = audit(tmp_path, policy())
    assert any(forbidden in failure for failure in failures)


def test_output_adapter_implements_core_port_and_can_use_its_sdk(tmp_path):
    write(tmp_path, "src/adapters/providers/openai/titles.py", """
from src.core.extractors.ports import TitleProvider
from src.adapters.providers.openai.client import Client
from openai import AsyncOpenAI
""")
    failures, *_ = audit(tmp_path, policy())
    assert not failures


def test_bootstrap_composes_layers_but_legacy_code_cannot_import_it(tmp_path):
    write(tmp_path, "src/bootstrap/api.py", "import src.adapters.access.api\nimport sqlalchemy")
    write(tmp_path, "src/main.py", "from src.bootstrap import api")
    failures, *_ = audit(tmp_path, policy(legacy=["src/main.py"]))
    assert len(failures) == 1 and "bootstrap" in failures[0]


def test_exact_exception_never_accepts_another_symbol_from_the_same_module(tmp_path):
    source = "src/use_cases/old.py"
    baseline = policy(exception(source, "sqlalchemy.select"))
    write(tmp_path, source, "from sqlalchemy import select")
    assert not audit(tmp_path, baseline)[0]
    write(tmp_path, source, "from sqlalchemy import select, update")
    failures, *_ = audit(tmp_path, baseline)
    assert len(failures) == 1 and "sqlalchemy.update" in failures[0]
    write(tmp_path, source, "pass")
    assert "stale exception" in audit(tmp_path, baseline)[0][0]


@pytest.mark.parametrize("entry", [
    exception("src/use_cases/*.py", "sqlalchemy.select"),
    exception("src/use_cases/old.py", "sqlalchemy.*"),
    {**exception("src/use_cases/old.py", "sqlalchemy.select"), "reason": ""},
    {**exception("src/use_cases/old.py", "sqlalchemy.select"), "remove_in": ""},
])
def test_policy_rejects_wildcards_or_unexplained_exceptions(entry):
    with pytest.raises(ValueError):
        validate_policy(policy(entry))


def test_new_legacy_location_and_stale_location_fail(tmp_path):
    write(tmp_path, "src/services/new.py", "pass")
    write(tmp_path, "src/new_service.py", "pass")
    failures, *_ = audit(tmp_path, policy())
    assert len(failures) == 2 and all("outside target layout" in failure for failure in failures)
    failures, *_ = audit(tmp_path, policy(legacy=["src/removed.py"]))
    assert any("stale legacy file" in failure for failure in failures)


def test_empty_adapter_module_still_requires_a_defined_responsibility(tmp_path):
    write(tmp_path, "src/adapters/misc/helper.py", "pass")
    failures, *_ = audit(tmp_path, policy())
    assert len(failures) == 1 and "outside a defined role" in failures[0]


@pytest.mark.parametrize("text", [
    "import importlib as loader\nloader.import_module('sqlalchemy')",
    "from importlib import import_module as load\nload('src.adapters.storage.postgres')",
    "__import__('sqlalchemy')",
    "import importlib\nimportlib.import_module('..adapters.storage', __package__)",
])
def test_literal_dynamic_imports_cannot_bypass_boundaries(tmp_path, text):
    write(tmp_path, "src/core/model.py", text)
    failures, _, dynamic, _ = audit(tmp_path, policy())
    assert failures and len(dynamic) == 1 and dynamic[0]["resolved"]


def test_unknown_dynamic_target_requires_review_even_in_legacy_module(tmp_path):
    write(tmp_path, "src/old.py", "import importlib\nimportlib.import_module(module_name)")
    failures, *_ = audit(tmp_path, policy(legacy=["src/old.py"]))
    assert len(failures) == 1 and "unresolved dynamic import" in failures[0]


def test_dynamic_fromlist_cannot_hide_a_bootstrap_import_in_legacy_code(tmp_path):
    write(tmp_path, "src/old.py", "__import__('src', fromlist=['bootstrap'])")
    failures, *_ = audit(tmp_path, policy(legacy=["src/old.py"]))
    assert len(failures) == 1 and "bootstrap" in failures[0]


def test_relative_imports_in_package_initializers_are_resolved():
    edges, _ = imports_in(Path("src/core/documents/__init__.py"), "from . import ports")
    assert edges[0].target == "src.core.documents.ports"


def test_inventory_includes_consumers_configuration_and_package_data_without_env(tmp_path):
    write(tmp_path, "src/core/model.py", "from pydantic import BaseModel")
    write(tmp_path, "tests/test_document.py", "import src.core.model")
    write(tmp_path, "Dockerfile", 'CMD ["uvicorn", "src.main:app"]')
    write(tmp_path, ".env", "PRIVATE_SENTINEL=must-not-be-read")
    write(tmp_path, "pyproject.toml", '[tool.setuptools.package-data]\n'
          '"src.notifications"=["announcements.json"]')
    _, edges, dynamic, sources = audit(tmp_path, policy())
    result = inventory(tmp_path, edges, dynamic, sources)
    assert {item["target"] for item in result["consumer_references"]} == {
        "src.core.model", "src.main:app", "src.notifications"
    }
    assert result["package_data"] == {"src.notifications": ["announcements.json"]}
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
