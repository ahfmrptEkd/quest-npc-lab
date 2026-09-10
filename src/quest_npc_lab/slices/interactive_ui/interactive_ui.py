"""Session state and comparison requests for the local UI."""

from dataclasses import asdict, dataclass, field, replace
from secrets import token_urlsafe
import json
from pathlib import Path
from typing import Any

from quest_npc_lab.slices.reaction_media import reaction_media, reaction_state

from .inference import ModelSettings, checkpoint_ready, local_generator

from quest_npc_lab.slices.guild_receptionist import (
    RequestInput,
    execute_request,
    RunError,
)

from quest_npc_lab.slices.guild_receptionist import QuestState

from quest_npc_lab.slices.prompt_evaluation import load_manifest
from quest_npc_lab.slices.prompt_evaluation.prompt_evaluation import MINIMAL_RULES

DEFAULT_STATE = QuestState("슬라임 토벌", 5, 5, "금화 100개", False)
OFFLINE_OUTPUT = json.dumps(
    {
        "action": "clarify",
        "dialogue": "오프라인 테스트 응답입니다. 실제 모델 추론이 아닙니다.",
    },
    ensure_ascii=False,
)
CONDITIONS = (
    ("base_minimal", "Base + Minimal Prompt"),
    ("base_improved", "Base + Improved Prompt"),
    ("sft_improved", "SFT + Improved Prompt"),
    ("grpo_improved", "SFT+GRPO + Improved Prompt"),
)


@dataclass
class Session:
    states: dict[str, QuestState] = field(
        default_factory=lambda: {key: replace(DEFAULT_STATE) for key, _ in CONDITIONS}
    )
    artifacts: dict[str, Any] = field(default_factory=dict)


class ComparisonApp:
    def __init__(
        self,
        *,
        offline=False,
        base_model=None,
        settings=None,
        sft_checkpoint=None,
        grpo_checkpoint=None,
        model_factory=local_generator,
    ):
        self.prompt_config = load_manifest()
        self.offline = offline
        self.settings = settings or ModelSettings()
        self.checkpoints = {
            "base_minimal": None,
            "base_improved": None,
            "sft_improved": Path(sft_checkpoint)
            if sft_checkpoint is not None
            else None,
            "grpo_improved": Path(grpo_checkpoint)
            if grpo_checkpoint is not None
            else None,
        }
        base = base_model or (
            (lambda prompt: OFFLINE_OUTPUT)
            if offline
            else model_factory(self.settings, None)
        )
        self.models = {"base_minimal": base, "base_improved": base}
        for key in ("sft_improved", "grpo_improved"):
            if not offline and checkpoint_ready(self.checkpoints[key]):
                self.models[key] = model_factory(self.settings, self.checkpoints[key])
        self.sessions = {}

    def new_session(self):
        session_id = token_urlsafe(32)
        self.sessions[session_id] = Session()
        return session_id

    def describe(self, session_id) -> dict[str, Any]:
        session = self.sessions[session_id]
        return {
            "mode": "offline" if self.offline else "live",
            "conditions": [
                {
                    "id": key,
                    "label": label,
                    "status": "ready" if key in self.models else "checkpoint_not_ready",
                    "state": asdict(session.states[key]),
                    "artifact": session.artifacts.get(key),
                    "reaction": reaction_media(
                        reaction_state(session.artifacts.get(key))
                    ),
                    "evaluation_label": "미채점 / Unrated",
                    "model": asdict(self.settings)
                    | {
                        "checkpoint": str(self.checkpoints[key])
                        if self.checkpoints[key]
                        else None,
                        "prompt_id": "minimal-v1"
                        if key == "base_minimal"
                        else self.prompt_config["version"],
                        "mode": "offline" if self.offline else "live",
                    },
                }
                for key, label in CONDITIONS
            ],
        }

    def _request(self, state, utterance, key):
        return RequestInput(
            state=replace(state),
            player_utterance=utterance,
            character_persona=self.prompt_config["character_persona"],
            rules=MINIMAL_RULES
            if key == "base_minimal"
            else self.prompt_config["system_rules"],
        )

    def compare(self, session_id, payload):
        self._payload(payload, {"state", "utterance"})
        try:
            state = QuestState(**payload["state"])
        except (TypeError, KeyError) as error:
            raise ValueError(
                "state must contain exactly the five quest fields"
            ) from error
        self._validate(state, payload["utterance"])
        session = self.sessions[session_id]
        session.states = {key: replace(state) for key, _ in CONDITIONS}
        session.artifacts.clear()
        for key, _ in CONDITIONS:
            if key in self.models:
                self._run(session, key, payload["utterance"])
        return self.describe(session_id)

    def turn(self, session_id, payload):
        self._payload(payload, {"condition", "utterance"})
        if (
            not isinstance(payload["condition"], str)
            or payload["condition"] not in self.models
        ):
            raise ValueError("condition is unknown or checkpoint is not ready")
        session = self.sessions[session_id]
        self._validate(session.states[payload["condition"]], payload["utterance"])
        self._run(session, payload["condition"], payload["utterance"])
        return self.describe(session_id)

    def _run(self, session, key, utterance):
        request = self._request(session.states[key], utterance, key)
        try:
            artifact = execute_request(request, self.models[key])
        except Exception as error:
            # Reuse the request artifact contract; no retry or output repair.
            artifact = execute_request(request, lambda prompt: "")
            artifact = replace(
                artifact, raw_output=None, error=RunError("inference", str(error))
            )
        session.artifacts[key] = artifact.to_dict()
        session.states[key] = artifact.server_execution.final_state

    @staticmethod
    def _payload(payload, fields):
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ValueError(
                "request must contain exactly: " + ", ".join(sorted(fields))
            )

    def _validate(self, state, utterance):
        # Use the sibling's public boundary to keep state rules in one place.
        # This constant callback never invokes a model or changes server state.
        artifact = execute_request(
            self._request(state, utterance, "base_minimal"),
            lambda prompt: OFFLINE_OUTPUT,
        )
        if artifact.error:
            raise ValueError(artifact.error.reason)
