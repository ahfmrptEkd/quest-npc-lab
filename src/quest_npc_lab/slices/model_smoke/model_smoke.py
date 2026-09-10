"""Pure smoke-validation rules shared by unit tests and the real-model runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import math
from typing import TYPE_CHECKING

from quest_npc_lab.slices.dataset_pipeline import DatasetCase, build_model_prompt
from quest_npc_lab.slices.guild_receptionist import (
    Action,
    OutputParseError,
    QuestState,
    RequestInput,
    execute_request,
    parse_model_output,
)

if TYPE_CHECKING:
    import torch


def _user_prompt(case: DatasetCase) -> list[dict[str, str]]:
    return [{"role": "user", "content": build_model_prompt(case)}]


def sft_example(case: DatasetCase) -> dict[str, list[dict[str, str]]]:
    """SFT 예시: 정답 행동·참조 대사는 completion에만 둔다."""
    answer = json.dumps(
        {"action": case.ground_truth_action.value, "dialogue": case.reference_dialogue},
        ensure_ascii=False,
    )
    return {
        "prompt": _user_prompt(case),
        "completion": [{"role": "assistant", "content": answer}],
    }


def grpo_example(case: DatasetCase, *, case_id: str) -> dict[str, object]:
    """GRPO 입력: 정답은 보상 함수 전용 열이며 프롬프트에 포함하지 않는다."""
    return {
        "prompt": _user_prompt(case),
        "ground_truth_action": case.ground_truth_action.value,
        "case_id": case_id,
    }


def run_inference_smoke(
    case: DatasetCase, generate: Callable[[str], str]
) -> dict[str, object]:
    """실제 모델 응답을 공통 요청 처리 경로(execute_request)로 보낸다."""
    expected_prompt = build_model_prompt(case)

    def guarded_model(prompt: str) -> str:
        # 요청 경로의 프롬프트가 정답 없는 데이터셋 프롬프트와 다르면 누출 위험으로 중단한다.
        if prompt != expected_prompt:
            raise RuntimeError("request prompt diverged from build_model_prompt")
        return generate(prompt)

    request = RequestInput(
        state=QuestState(
            quest_name=case.quest_name,
            target_count=case.target_count,
            current_count=case.current_count,
            reward_description=case.reward_description,
            reward_claimed=case.reward_claimed,
        ),
        player_utterance=case.player_utterance,
        ground_truth_action=case.ground_truth_action,
    )
    return execute_request(request, guarded_model).to_dict()


def strict_action_reward(raw_output: str, ground_truth_action: Action) -> float:
    """GRPO 보상: 출력 계약 통과 + 정답 행동 일치면 1.0, 그 외 0.0."""
    try:
        parsed = parse_model_output(raw_output)
    except OutputParseError:
        return 0.0
    return 1.0 if parsed.action is ground_truth_action else 0.0


def summarize_reward_groups(
    rewards_by_group: Mapping[str, Sequence[float]],
) -> dict[str, object]:
    """후보 그룹별 보상 차이 유무로 상대적 학습 신호를 요약한다."""
    groups = {
        key: [float(r) for r in rewards] for key, rewards in rewards_by_group.items()
    }
    identical = sum(1 for rewards in groups.values() if len(set(rewards)) <= 1)
    varied = len(groups) - identical
    return {
        "group_count": len(groups),
        "varied_group_count": varied,
        "identical_group_count": identical,
        "identical_group_ratio": identical / len(groups) if groups else None,
        "has_relative_signal": varied > 0,
        "rewards_by_group": groups,
    }


def parameter_diff(
    before: Mapping[str, "torch.Tensor"], after: Mapping[str, "torch.Tensor"]
) -> dict[str, object]:
    """같은 이름의 파라미터 스냅샷 두 개의 변화량을 요약한다."""
    if set(before) != set(after):
        raise ValueError("parameter snapshots must contain the same tensor names")
    squared_sum = 0.0
    max_abs = 0.0
    changed = 0
    for name, old in before.items():
        delta = (after[name] - old).float()
        tensor_max = float(delta.abs().max()) if delta.numel() else 0.0
        changed += tensor_max > 0
        max_abs = max(max_abs, tensor_max)
        squared_sum += float(delta.pow(2).sum())
    return {
        "tensor_count": len(before),
        "changed_tensor_count": changed,
        "l2_norm": math.sqrt(squared_sum),
        "max_abs": max_abs,
        "changed": changed > 0,
    }


TARGET_TRAIN_CASES = 180
SMOKE_ARTIFACT_NOTE = (
    "artifacts/smoke/의 체크포인트·로그는 파이프라인 확인용이다. 본 SFT는 나중에 고정한 "
    "개선 프롬프트·실행 설정으로 원본 기반 모델에서 새로 시작하며 스모크 체크포인트를 "
    "본 결과로 재사용하지 않는다."
)
BUDGET_METHOD = (
    "1스텝 스모크 실측의 선형 외삽. 첫 스텝 워밍업이 포함되어 과대추정일 수 있고, "
    "평가·재시도·에폭 수 결정은 포함하지 않는다."
)
ZEROGPU_CONSIDERATIONS = (
    "ZeroGPU는 Gradio SDK Space만 지원하며 GPU 함수는 @spaces.GPU로 감싸고 모델은 "
    "모듈 로드 시 cuda에 올린다. 기본 실행 한도는 60초(duration으로 조정).",
    "기본 large 크기는 RTX Pro 6000 Blackwell 절반(48GB VRAM)으로 0.5B 모델+LoRA "
    "추론에는 충분하다.",
    "문서상 지원 PyTorch는 2.8.0~2.13.0, Python은 3.12.12/3.10.13이다. 로컬 torch "
    "2.14.0+cu130은 목록 밖이므로 Space 요구사항에서 지원 버전으로 고정하고 재검증한다.",
    "torch.compile은 지원하지 않는다(AoT 컴파일만 가능).",
    "무료 개인 계정은 인증된 이메일·가입 30일 이상 조건에서 ZeroGPU Space 2개까지 "
    "호스팅할 수 있다. 방문자 일일 할당량은 비로그인 2분·무료 계정 5분이다.",
    "로컬 hf CLI는 로그인되어 있지 않아 계정 자격은 아직 확인하지 못했다. 배포 전 "
    "최신 조건과 계정 자격을 재확인한다. (출처: huggingface.co/docs/hub/spaces-zerogpu)",
)


def _per_epoch_seconds(phase: Mapping[str, object], key: str) -> float | None:
    value = phase.get(key)
    if phase.get("status") != "ok" or value is None:
        return None
    return round(float(value) * TARGET_TRAIN_CASES, 1)


def _blockers(phases: Mapping[str, Mapping[str, object]]) -> list[str]:
    blockers = [
        f"{name}: {phase.get('error', phase.get('status'))}"
        for name, phase in phases.items()
        if phase.get("status") != "ok"
    ]
    sft = phases.get("sft", {})
    if sft.get("status") == "ok":
        if not sft["weight_diff"]["changed"]:
            blockers.append("sft: LoRA weights unchanged after update")
        reload = sft.get("reload", {})
        if reload.get("status") != "ok":
            blockers.append(f"sft reload: {reload.get('error', 'missing')}")
        elif not reload.get("matches_trained_weights"):
            blockers.append("sft: reloaded adapter weights differ from trained weights")
    grpo = phases.get("grpo", {})
    if grpo.get("status") == "ok":
        if not grpo["reward_groups"]["has_relative_signal"]:
            blockers.append(
                "grpo: no relative reward signal (every candidate group had identical rewards)"
            )
        if not grpo["parameter_diff"]["changed"]:
            blockers.append("grpo: parameters unchanged after policy update")
    return blockers


def build_smoke_report(
    *,
    environment: Mapping[str, object],
    limits: Mapping[str, object],
    phases: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """스모크 결과를 판정·예산 외삽·배포 고려사항과 함께 하나의 보고서로 묶는다."""
    blockers = _blockers(phases)
    return {
        "run_kind": "smoke",
        "status": "blocked" if blockers else "passed",
        "blockers": blockers,
        "smoke_artifacts": {
            "reusable_for_main_experiment": False,
            "note": SMOKE_ARTIFACT_NOTE,
        },
        "environment": dict(environment),
        "limits": dict(limits),
        "budget_estimate": {
            "target_train_cases": TARGET_TRAIN_CASES,
            "sft_seconds_per_epoch": _per_epoch_seconds(
                phases.get("sft", {}), "seconds_per_case"
            ),
            "grpo_seconds_per_epoch": _per_epoch_seconds(
                phases.get("grpo", {}), "seconds_per_prompt"
            ),
            "method": BUDGET_METHOD,
        },
        "zerogpu_considerations": list(ZEROGPU_CONSIDERATIONS),
        "phases": {name: dict(phase) for name, phase in phases.items()},
    }
