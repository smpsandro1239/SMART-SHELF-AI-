"""Deployment contract tests for ONNX model trust settings."""
from pathlib import Path
import re

import pytest


COMPOSE_FILE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


@pytest.mark.parametrize("service", ["api", "vision-worker"])
@pytest.mark.parametrize(
    "setting",
    ["VISION_DETECTOR_MODEL_SHA256", "VISION_EMBEDDING_MODEL_SHA256", "VISION_MODEL_MANIFEST_PATH", "VISION_MODEL_TRUSTED_KEYS_JSON"],
)
def test_compose_forwards_model_integrity_and_trust_settings_to_every_provider_process(service, setting):
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    service_match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        compose,
    )
    assert service_match is not None, f"Missing Docker Compose service: {service}"

    defaults = {
        "VISION_DETECTOR_MODEL_SHA256": "",
        "VISION_EMBEDDING_MODEL_SHA256": "",
        "VISION_MODEL_MANIFEST_PATH": "/models/manifest.json",
        "VISION_MODEL_TRUSTED_KEYS_JSON": "",
        "VISION_MODEL_REVOKED_KEY_IDS_JSON": "[]",
        "VISION_MODEL_DEPLOYMENT_ID": "default",
    }
    expected_line = f"      {setting}: ${{{setting}:-{defaults[setting]}}}"
    assert expected_line in service_match.group("body").splitlines(), (
        f"{service} must receive {setting} from the deployment environment"
    )
