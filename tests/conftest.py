import pytest


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_ROOT", str(tmp_path))
    return tmp_path
