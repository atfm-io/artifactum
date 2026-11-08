from __future__ import annotations

import pytest


def test_client_raises_plan_limit_error_and_warns_once(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    import httpx

    from artifactum import client as client_mod
    from artifactum.config import Config
    from artifactum.exceptions import PlanLimitError

    responses = iter([
        httpx.Response(201, json={"id": "AAAAAAAA", "warning": "You've used 4 of 5 artifacts"}),
        httpx.Response(201, json={"id": "BBBBBBBB", "warning": "You've used 5 of 5 artifacts"}),
        httpx.Response(402, json={"detail": {"message": "You've reached the Free plan's limit", "upgrade_url": "http://x/settings"}}),
    ])
    c = client_mod.ArtifactumClient(Config(api_token="t", server_url="http://x"))
    monkeypatch.setattr(c, "_post", lambda path, json: c._handle(next(responses)))
    monkeypatch.setattr(client_mod, "_warned", set())

    with caplog.at_level("WARNING", logger="artifactum"):
        assert c.register_artifact(hash="a", gcs_url="g", size_bytes=1) == "AAAAAAAA"
        assert c.register_artifact(hash="b", gcs_url="g", size_bytes=1) == "BBBBBBBB"
    assert len([r for r in caplog.records if "artifacts" in r.getMessage()]) == 1

    with pytest.raises(PlanLimitError) as exc:
        c.register_artifact(hash="c", gcs_url="g", size_bytes=1)
    assert exc.value.upgrade_url == "http://x/settings" and "limit" in str(exc.value)
