"""The suite must not touch the network.

Everything it needs is either local or stubbed, and a test that reaches out is
a bug: it makes the run depend on the weather, and a stub that quietly stopped
intercepting would go unnoticed. One did — a Space-Track test kept its old
patch after the code moved to a different call, and every run then attempted a
real login.
"""

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError(
            "a test tried to open a network connection; stub it instead"
        )

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
