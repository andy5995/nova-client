"""Immortal Barons leagues: [leagues.IB.<n>].

IB is a native program with its own packet names, L555-<src>-<seq>-<dst>.brp
with the nodes and sequence in base 36, and a roster (ibnodes.dat) that the
game keeps in its data directory and updates itself from signed broadcasts.
"""

import asyncio
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from client import NovaHubClient, hub_league_id, unprocessed_packets  # noqa: E402
from game_runner import GameRunner, runner_for  # noqa: E402
from validator import ClientValidator  # noqa: E402

SEQ = "0000000000001"


def ib_name(src: str, dst: str, seq: str = SEQ, league: str = "555") -> str:
    return f"L{league}-{src}-{seq}-{dst}.brp"


@pytest.fixture
def ib_league(tmp_path, mock_server_url, mock_storage):
    """An IB league with this BBS as node 10 ("a" in a packet name)."""
    mock_storage.add_client(
        client_id="ib_client",
        client_secret="ib_secret",
        bbs_name="Test BBS",
        memberships=[{"league_id": "555I", "bbs_index": 10}],
    )
    data = tmp_path / "ib"
    dirs = {"data": data, "inbound": data / "inbound", "outbound": data / "outbound"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config.toml"
    config.write_text(f"""
[hub]
url = "{mock_server_url}"
client_id = "ib_client"
client_secret = "ib_secret"

[bbs]
name = "Test BBS"

[sync]
sent_action = "delete"
max_retries = 1
retry_delay = 0
metrics_file = "{tmp_path / 'metrics.json'}"

[leagues.IB.555]
enabled = true
bbs_index = 10
game_folder = "{data}"
inbound_dir = "{dirs['inbound']}"
outbound_dir = "{dirs['outbound']}"
""")
    return str(config), dirs


def add_row(storage, filename, dest, data=b"packet", source="01"):
    storage.packets.append({
        "id": storage.next_packet_id,
        "filename": filename.upper(),
        "league_number": "555",
        "game_type": "I",
        "source": source,
        "dest": dest,
        "sequence": 1,
        "received_at": datetime.now(),
        "retrieved_at": None,
        "file_size": len(data),
        "file_data": data,
    })
    storage.next_packet_id += 1


def test_league_id_carries_the_letter_i():
    assert hub_league_id("IB", "555") == "555I"


@pytest.mark.asyncio
async def test_uploads_only_its_own_packets(ib_league, mock_storage):
    config, dirs = ib_league
    ours = dirs["outbound"] / ib_name("a", "1")
    broadcast = dirs["outbound"] / ib_name("a", "0", seq="000000000000z")
    someone_else = dirs["outbound"] / ib_name("b", "1")
    no_roster = dirs["outbound"] / "L555-ABCDEFGHIJKLMNOPQRSTUVWXYZ.brp"
    temp = dirs["outbound"] / f".{ib_name('a', '2')}-123.tmp"
    for f in (ours, broadcast, someone_else, no_roster, temp):
        f.write_bytes(b"x")

    assert await NovaHubClient(config).run() == 0

    sent = sorted(p["filename"] for p in mock_storage.packets)
    assert sent == sorted([ours.name.upper(), broadcast.name.upper()])
    assert [p["source"] for p in mock_storage.packets] == ["0A", "0A"]
    assert not ours.exists() and not broadcast.exists()
    assert someone_else.exists() and no_roster.exists() and temp.exists()


@pytest.mark.asyncio
async def test_warns_about_a_packet_named_without_nodes(ib_league, capsys):
    config, dirs = ib_league
    (dirs["outbound"] / "L555-ABCDEFGHIJKLMNOPQRSTUVWXYZ.brp").write_bytes(b"x")

    await NovaHubClient(config).run()

    assert "no ibnodes.dat yet" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_downloads_a_broadcast_and_a_direct_packet(ib_league, mock_storage):
    config, dirs = ib_league
    broadcast = ib_name("1", "0").upper()
    direct = ib_name("1", "a").upper()
    add_row(mock_storage, broadcast, "0A", b"to everyone")
    add_row(mock_storage, broadcast, "02", b"to everyone")  # another board's copy
    add_row(mock_storage, direct, "0A", b"to us")

    assert await NovaHubClient(config).run() == 0

    assert (dirs["inbound"] / broadcast).read_bytes() == b"to everyone"
    assert (dirs["inbound"] / direct).read_bytes() == b"to us"
    assert unprocessed_packets(dirs["inbound"]) == sorted([broadcast, direct])


@pytest.mark.asyncio
async def test_first_roster_is_installed_as_ibnodes_dat(ib_league, mock_storage):
    config, dirs = ib_league
    roster = b"1\r\nNova Hub\r\n-\r\n-\r\n-\r\n-\r\n\r\n"
    mock_storage.add_nodelist("555I", roster)
    add_row(mock_storage, "IBNODES.555", "0A", roster)

    assert await NovaHubClient(config).run() == 0

    assert (dirs["data"] / "ibnodes.dat").read_bytes() == roster
    assert list(dirs["inbound"].iterdir()) == []


@pytest.mark.asyncio
async def test_an_existing_roster_is_left_alone(ib_league, mock_storage):
    config, dirs = ib_league
    kept = b"the game's own, from the Coordinator's signed broadcast"
    (dirs["data"] / "ibnodes.dat").write_bytes(kept)
    mock_storage.add_nodelist("555I", b"the hub's copy")
    add_row(mock_storage, "IBNODES.555", "0A", b"the hub's copy")

    assert await NovaHubClient(config).run() == 0

    assert (dirs["data"] / "ibnodes.dat").read_bytes() == kept
    assert list(dirs["inbound"].iterdir()) == []


def _fake_game(tmp_path, body: str) -> Path:
    game = tmp_path / "fake-ib"
    game.write_text("#!/bin/sh\n" + body)
    game.chmod(game.stat().st_mode | stat.S_IXUSR)
    return game


def test_validator_refuses_an_unknown_runner(ib_league):
    config, dirs = ib_league
    with open(config, "a") as f:
        f.write('runner = "nativ"\n')

    validator = ClientValidator(config)
    assert not validator.validate()
    assert any("runner must be native or dosemu" in e.message for e in validator.errors)


def test_ib_runs_natively_unless_told_otherwise():
    assert runner_for("IB", {}) == "native"
    assert runner_for("BRE", {}) == "dosemu"
    assert runner_for("IB", {"runner": "dosemu"}) == "dosemu"


@pytest.mark.skipif(sys.platform == "win32", reason="the native runner is the Linux path")
def test_native_maintenance_runs_in_the_game_folder(tmp_path):
    folder = tmp_path / "data dir"
    folder.mkdir()
    game = _fake_game(tmp_path, 'pwd > ran.txt\nfor a in "$@"; do echo "$a" >> ran.txt; done\n')
    runner = GameRunner({"daemon": {}})
    league = {
        "game_folder": str(folder),
        "game_command": str(game),
        "maintenance_args": f"-maint -data '{folder}'",
    }

    result = asyncio.run(runner.run_maintenance("IB", "555", league, timeout=30))

    assert result.success, result.error
    assert (folder / "ran.txt").read_text().splitlines() == [
        str(folder.resolve()), "-maint", "-data", str(folder)]


@pytest.mark.skipif(sys.platform == "win32", reason="the native runner is the Linux path")
def test_native_failure_says_why(tmp_path):
    game = _fake_game(tmp_path, "echo 'a packet was refused'\nexit 1\n")
    runner = GameRunner({"daemon": {}})
    league = {"game_folder": str(tmp_path), "game_command": str(game)}

    result = asyncio.run(runner.run_maintenance("IB", "555", league, timeout=30))

    assert not result.success
    assert result.error == "Exit code: 1 - a packet was refused"


@pytest.mark.skipif(sys.platform == "win32", reason="the native runner is the Linux path")
def test_native_default_command_is_immortal_barons_maint(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    game = _fake_game(bin_dir, 'echo "$@" > "$PWD/args.txt"\n')
    game.rename(bin_dir / "immortal-barons")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    runner = GameRunner({"daemon": {}})

    result = asyncio.run(runner.run_maintenance("IB", "555", {"game_folder": str(tmp_path)}, timeout=30))

    assert result.success, result.error
    assert (tmp_path / "args.txt").read_text().strip() == "-maint -data ."


def test_validator_reads_ibnodes_with_keys(ib_league):
    config, dirs = ib_league
    key = "ab" * 32
    (dirs["data"] / "ibnodes.dat").write_text(
        f"1\nNova Hub\n-\n-\n-\n-\n{key}\n\n10\nTest BBS\n-\nCity\nST\nUSA\n{key}\n\n"
    )

    validator = ClientValidator(config)
    assert validator.validate(), [str(e) for e in validator.errors]
    # The hub routes IB, so a roster without HOST lines is not worth a warning
    assert not [w for w in validator.warnings if "HOST" in w.message]
