"""The public path must remain useful with all network/process entry points denied."""

import json
import os
import socket
import subprocess
import urllib.request

import pytest

from mcp_contract_guard.cli import main
from mcp_contract_guard.loading import OFFLINE_REGISTRY, _deny_remote


def test_cli_never_executes_or_connects(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network/process invocation is outside the offline contract")

    for target, name in [
        (socket, "socket"),
        (socket, "create_connection"),
        (urllib.request, "urlopen"),
        (subprocess, "Popen"),
        (os, "system"),
    ]:
        monkeypatch.setattr(target, name, forbidden)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "name": "shell",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"command": {"type": "string"}},
                        },
                    }
                ]
            }
        )
    )
    fixtures = tmp_path / "fixtures.json"
    marker = tmp_path / "should-not-exist"
    fixtures.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "inert-command",
                        "tool": "shell",
                        "arguments": {"command": f"touch {marker}"},
                    }
                ]
            }
        )
    )
    assert main(["compare", str(snapshot), str(snapshot), "--fixtures", str(fixtures)]) == 0
    assert "PASS" in capsys.readouterr().out
    assert not marker.exists()


def test_registry_refuses_retrieval_even_if_called_directly():
    from referencing.exceptions import NoSuchResource

    with pytest.raises(NoSuchResource):
        _deny_remote("https://example.invalid/schema")
    with pytest.raises(NoSuchResource):
        OFFLINE_REGISTRY.get_or_retrieve("https://example.invalid/schema")
