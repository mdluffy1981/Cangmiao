from __future__ import annotations

from ..settings import EngineSettings

OVERRIDES = "reportAnalysisWinratesAs=SIDETOMOVE,ponderingEnabled=false"

REQUIRED_COMMANDS = ("play", "genmove", "undo", "clear_board", "boardsize", "komi", "kata-set-rules",
                     "final_score", "kata-set-param")
OPTIONAL_COMMANDS = ("kata-analyze",)

# First command waits for model loading and possibly OpenCL tuning.
STARTUP_TIMEOUT_S = 900.0
COMMAND_TIMEOUT_S = 30.0
SEARCH_GRACE_S = 30.0


def engine_args(es: EngineSettings) -> list[str]:
    return ["gtp", "-model", es.model, "-config", es.config, "-override-config", OVERRIDES]
