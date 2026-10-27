"""Local upgrades must rebuild packaged Alembic revisions before retiring data."""

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy.sh"


def simulate(tmp_path, failure=""):
    docker = tmp_path / "docker-compose"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['DEPLOY_TEST_LOG'], 'a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(17 if os.environ.get('DEPLOY_TEST_FAIL') in sys.argv "
        "and os.environ.get('DEPLOY_TEST_FAIL') else 0)\n"
    )
    docker.chmod(0o700)
    log = tmp_path / "log"
    result = subprocess.run(
        ["sh", str(SCRIPT), "--env-file", "test.env"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DEPLOY_TEST_LOG": str(log),
            "DEPLOY_TEST_FAIL": failure,
        },
        capture_output=True,
    )
    return result.returncode, [json.loads(line) for line in log.read_text().splitlines()]


def test_local_deploy_rebuilds_all_images_before_stopping_writers(tmp_path):
    code, calls = simulate(tmp_path)
    assert code == 0
    assert all(call[:2] == ["--env-file", "test.env"] for call in calls)
    commands = [call[2:] for call in calls]
    assert commands[:5] == [
        ["config", "--quiet"],
        ["--profile", "tools", "build", "--pull"],
        ["run", "--rm", "--no-deps", "entrypoint-check"],
        [
            "--profile",
            "admin-lan",
            "stop",
            "admin-web",
            "admin-api",
            "admin-sync",
            "api",
            "processing-worker",
            "processing-dispatcher",
            "pwa",
        ],
        ["up", "-d", "--wait", "postgres", "arcadedb", "rabbitmq"],
    ]
    for command, task in zip(
        commands[5:8], ["database-migrations", "arcadedb-schema", "data-migrations"], strict=True
    ):
        assert command == [
            "up",
            "--no-deps",
            "--abort-on-container-exit",
            "--exit-code-from",
            task,
            task,
        ]
    assert commands[8:] == [["up", "-d"]]


def test_failed_build_does_not_stop_application(tmp_path):
    code, calls = simulate(tmp_path, "build")
    assert code == 17
    assert calls[-1][2:] == ["--profile", "tools", "build", "--pull"]
    assert len(calls) == 2


def test_failed_sql_migration_prevents_data_cleanup_and_startup(tmp_path):
    code, calls = simulate(tmp_path, "database-migrations")
    assert code == 17
    assert calls[-1][-1] == "database-migrations"
    assert not any("data-migrations" in call for call in calls)
    assert calls[-1][-2:] != ["up", "-d"]


def test_local_compose_uses_same_arcadedb_credentials_for_all_core_services():
    import shutil

    import pytest

    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is required to validate resolved service configuration")
    result = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            str(SCRIPT.parent / ".env.example"),
            "-f",
            str(SCRIPT.parent / "docker-compose.yml"),
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        env={
            **os.environ,
            "ARCADEDB_ROOT_PASSWORD": "compose-regression-test-password",
            "CLOUDFLARE_TUNNEL_TOKEN": "compose-model-check-only",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    expected = services["arcadedb-schema"]["environment"]
    for name in ("api", "data-migrations", "processing-worker", "processing-dispatcher"):
        environment = services[name]["environment"]
        assert environment["ARCADEDB_HTTP_URL"] == expected["ARCADEDB_HTTP_URL"]
        assert environment["ARCADEDB_USERNAME"] == expected["ARCADEDB_USERNAME"]
        assert environment["ARCADEDB_ROOT_PASSWORD"] == expected["ARCADEDB_ROOT_PASSWORD"]


def test_failed_entrypoint_check_keeps_existing_services_running(tmp_path):
    code, calls = simulate(tmp_path, "entrypoint-check")
    assert code == 17
    assert len(calls) == 3
    assert calls[-1][2:] == ["run", "--rm", "--no-deps", "entrypoint-check"]
    assert not any("stop" in call or "up" in call for call in calls)


def test_development_entrypoint_check_is_isolated_and_covers_compose_commands():
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(SCRIPT.parent / ".env.example"),
            "-f",
            str(SCRIPT.parent / "docker-compose.yml"),
            "--profile",
            "tools",
            "--profile",
            "admin-lan",
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        env={**os.environ, "CLOUDFLARE_TUNNEL_TOKEN": "compose-model-check-only"},
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    check = services["entrypoint-check"]
    assert check["profiles"] == ["tools"]
    assert check["network_mode"] == "none" and check["read_only"]
    assert "env_file" not in check and "volumes" not in check and "depends_on" not in check
    assert Path(check["build"]["context"]) == SCRIPT.parent
    assert check["build"].get("dockerfile", "Dockerfile") == "Dockerfile"
    assert check["command"][:2] == ["python", "-c"]
    preflight = check["command"][2]
    targets = {
        "api": (1, "src.bootstrap.public_api"),
        "admin-api": (1, "src.bootstrap.administration"),
        "admin-sync": (2, "src.bootstrap.inventory_sync"),
        "processing-worker": (2, "src.bootstrap.messaging"),
        "processing-dispatcher": (2, "src.bootstrap.dispatcher"),
        "data-migrations": (2, "src.bootstrap.data_migrations"),
        "arcadedb-schema": (2, "src.bootstrap.graph_schema"),
    }
    for service, (position, module) in targets.items():
        assert services[service]["command"][position].split(":")[0] == module
        assert "from " + module + " import " in preflight
    assert services["processing-worker"]["command"][3] == "src.bootstrap.worker"
    assert "from src.bootstrap.worker import execute_processing" in preflight
    assert 'execute_processing.task_name == "processing.execute"' in preflight
    assert 'get_revision("20261006_06")' in preflight
    assert 'get_revision("20261016_11")' in preflight
