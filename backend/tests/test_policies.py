import json
from pathlib import Path

import pytest
from mergescope.domain.models import SecurityReviewMode
from mergescope.services.policies import (
    PolicyRegistry,
    RepositoryNotAllowedError,
)


def test_policy_registry_merges_defaults_and_enforces_allowlist(tmp_path: Path) -> None:
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            {
                "default": {
                    "minimum_confidence": 0.7,
                    "max_inline_comments": 20,
                },
                "repositories": {
                    "Example/Project": {
                        "security_review": "always",
                        "publish_comments": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = PolicyRegistry(path=path, allowed_repositories={"example/project"})

    policy = registry.policy_for("example/project")
    assert registry.is_allowed("EXAMPLE/PROJECT") is True
    assert policy.minimum_confidence == 0.7
    assert policy.max_inline_comments == 20
    assert policy.security_review is SecurityReviewMode.always
    assert policy.publish_comments is True
    assert registry.fingerprint("example/project") != registry.fingerprint("other/project")

    with pytest.raises(RepositoryNotAllowedError, match="not present"):
        registry.require_allowed("other/project")
