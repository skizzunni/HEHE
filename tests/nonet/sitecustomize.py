"""Loaded only by tools/check.sh (PYTHONPATH=tests/nonet): every socket connect
fails, so a unit test that silently reaches ESPN / FanDuel / NHL fails loudly
here instead of passing on a good day and breaking CI on a bad one
(2026-11-23: tests that needed the network and numpy broke the CI run)."""
import socket


def _blocked(self, addr):
    raise OSError(f"network blocked in unit tests: {addr!r}")


socket.socket.connect = _blocked
socket.create_connection = lambda *a, **k: _blocked(None, a[0] if a else None)
