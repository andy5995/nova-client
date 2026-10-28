# games.py
"""The games the client serves, and what differs between them.

Config sections name the game ([leagues.BRE.555]); everything the client needs
to know about it lives in its row here, so adding a game means adding a row.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Game:
    letter: str  # the hub's league ids carry it: [leagues.BRE.555] is "555B"
    nodes_file: str  # the roster in the game's own folder
    command: str  # game_command when the league config gives none
    maintenance_args: str  # maintenance_args likewise
    native: bool = False  # runs on Linux without dosemu


GAMES = {
    "BRE": Game("B", "brnodes.dat", "BRE", "PLANETARY"),
    "FE": Game("F", "fenodes.dat", "FE", "PLANETARY"),
    # The game runs from game_folder, its data directory; without -data it
    # would use ./data beneath it and never see the roster installed there.
    "IB": Game("I", "ibnodes.dat", "immortal-barons", "-maint -data .", native=True),
}

# For messages: "BRE, FE or IB"
GAME_NAMES = ", ".join(list(GAMES)[:-1]) + " or " + list(GAMES)[-1]


def game_for(game_type: str) -> Optional[Game]:
    """The game a config section names, in any case, or None if unknown."""
    return GAMES.get(game_type.upper())
