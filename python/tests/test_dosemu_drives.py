"""[daemon] dosemu_drives: redirected DOS drives for maintenance runs.

Written for a BBS (eqx, Ezycom under dosemu2) whose games live under an M:
that lredir maps to the BBS tree. BRE/FE keep M:\\ paths in their own config
files, so a maintenance run that only CDs into the game folder from C: can't
find its packets or data.
"""

import sys
from pathlib import Path

import pytest
import toml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game_runner import GameRunner  # noqa: E402
from validator import ClientValidator  # noqa: E402


def runner():
    return GameRunner({"daemon": {}}, verbose=False)


def test_conf_allows_lredir_of_each_drive(tmp_path):
    conf = tmp_path / "bre_015.conf"
    runner()._write_dosemu_config(conf, {"M": "/opt/eqx/bbs", "N": "/srv/files"})
    assert '$_lredir_paths = "/opt/eqx/bbs /srv/files"' in conf.read_text()


def test_conf_unchanged_without_drives(tmp_path):
    conf = tmp_path / "bre_015.conf"
    runner()._write_dosemu_config(conf)
    assert "lredir" not in conf.read_text()


def test_batch_maps_drives_before_changing_to_the_game(tmp_path):
    bat = tmp_path / "NOVAMNT.BAT"
    runner()._create_batch_file(bat, "BRE PLANETARY", "M:\\EZY\\DOORS\\BRE_015", {"M": "/opt/eqx/bbs"})
    lines = bat.read_text().splitlines()
    assert lines.index("lredir -f M: /opt/eqx/bbs") < lines.index("M:") < lines.index("CD M:\\EZY\\DOORS\\BRE_015")


@pytest.mark.parametrize("drives, why", [
    ({"C": "/opt/bbs"}, "drive letter"),
    ({"MM": "/opt/bbs"}, "drive letter"),
    ({"M": "bbs"}, "absolute"),
])
def test_bad_drives_refused(drives, why):
    with pytest.raises(ValueError, match=why):
        GameRunner._dosemu_drives(drives)


def test_letter_spelling_is_forgiving():
    assert GameRunner._dosemu_drives({"m:": "/opt/bbs"}) == {"M": "/opt/bbs"}


def _validate(tmp_path, drives):
    cfg = tmp_path / "config.toml"
    cfg.write_text(toml.dumps({
        "hub": {"url": "http://hub", "client_id": "a", "client_secret": "b"},
        "bbs": {"name": "Test"},
        "daemon": {"dosemu_drives": drives},
    }))
    v = ClientValidator(config_path=str(cfg))
    v.validate()
    return [e.message for e in v.errors]


def test_validator_checks_drive_directories(tmp_path):
    assert _validate(tmp_path, {"M": str(tmp_path)}) == []
    assert any("does not exist" in m for m in _validate(tmp_path, {"M": str(tmp_path / "nope")}))
    assert any("drive letter" in m for m in _validate(tmp_path, {"C": str(tmp_path)}))
