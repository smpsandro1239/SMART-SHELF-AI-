"""Deployment contract tests for ONNX model integrity settings."""
from pathlib import Path
import re

import pytest


COMPOSE_FILE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


@pytest.mark.parametrize("service", ["api", "vision-worker"])
@pytest.mark.parametrize(
    "setting",
    ["VISION_DETECTOR_MODEL_SHA256", "VISION_EMBEDDING_MODEL_SHA256"],
)
def test_compose_forwards_approved_model_digests_to_every_real_provider_process(service, setting):
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    service_match = re.search(
        rf"(?ms)^  {re.escape(service)}:\\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\\n|\\Z)",
        compose,
    )
    assert service_match is not None, f"Missing Docker Compose service: {service}"

    expected = rf"^      {re.escape(setting)}: \\${{{re.escape(setting)}:-}}$"
    assert re.search(expected, service_match.group("body"), re.MULTILINE), (
        f"{service} must receive {setting} from the deployment environment"
    )
