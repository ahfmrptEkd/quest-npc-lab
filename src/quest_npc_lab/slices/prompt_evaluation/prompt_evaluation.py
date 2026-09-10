"""Zero-shot development comparison and the shared experimental prompt contract."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from quest_npc_lab.slices.guild_receptionist import QuestState

MANIFEST_PATH = Path(__file__).with_name('prompt_manifest.json')
MINIMAL_RULES = (
    '현재 서버 상태만 신뢰한다. 명확한 지급 요청에 목표 달성·미수령이면 grant_reward, '
    '미달이면 explain_progress, 이미 수령했으면 already_claimed를 선택한다. '
    '진행 문의는 explain_progress, 보상 문의는 explain_reward, 애매한 퀘스트 요청은 clarify, '
    '인사나 범위 밖 요청은 other다. action과 비어 있지 않은 한국어 dialogue만 있는 '
    'JSON 객체 하나를 출력한다. 추가 필드, 중복 키, 코드 펜스, JSON 밖 설명은 금지한다.'
)


def load_manifest() -> dict:
    """Load a fresh copy; accidental edits to the frozen contract fail closed."""
    raw = MANIFEST_PATH.read_bytes()
    expected = MANIFEST_PATH.with_suffix('.sha256').read_text().strip()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('frozen prompt manifest integrity mismatch')
    return json.loads(raw)


def format_prompt(state: QuestState, player_utterance: str, *, baseline: str = 'improved') -> str:
    """Same JSON request template as execute_request, with no answer input seam."""
    config = load_manifest()
    if baseline not in ('minimal', 'improved'):
        raise ValueError('unknown baseline')
    values = {
        'character_persona': config['character_persona'],
        'rules': MINIMAL_RULES if baseline == 'minimal' else config['system_rules'],
        'server_state': asdict(state),
        'player_utterance': player_utterance,
    }
    payload = {key: values[value] for key, value in config['prompt_template'].items()}
    return json.dumps(payload, **config['serialization'])


def load_development_data() -> dict:
    """Fixed allowlist: no caller-controlled paths, directory scans or held-out data."""
    from quest_npc_lab.slices.dataset_pipeline.dataset_pipeline import (
        load_dataset, validate_review_manifest, validate_dataset,
    )
    directory = Path(__file__).parent.parent / 'dataset_pipeline' / 'data'
    result = {}
    for split, name in (('train', 'train_180'), ('validation', 'val_60')):
        path = directory / f'{name}.jsonl'
        if path.is_symlink():
            raise ValueError('development dataset must not be a symlink')
        cases = load_dataset(path)
        review = json.loads((directory / f'{name}_review_batches.json').read_text())
        validate_review_manifest(cases, review, dataset_path=path)
        from collections import Counter
        from quest_npc_lab.slices.guild_receptionist import Action
        total = 180 if split == 'train' else 60
        if (len(cases) != total or {c.split for c in cases} != {split}
                or {c.review_status for c in cases} != {'user_approved'}
                or Counter(c.ground_truth_action for c in cases) != {a: total // 6 for a in Action}):
            raise ValueError('development split must be complete, balanced and approved')
        result[split] = cases
    validate_dataset((*result['train'], *result['validation']))
    return result


def compare_baselines(datasets, generate, output_path: Path) -> dict:
    """Generate once per condition/case and score through the receptionist boundary."""
    from quest_npc_lab.slices.guild_receptionist import Action, RequestInput, execute_request

    if not datasets or set(datasets) - {'train', 'validation'}:
        raise ValueError('only development splits are permitted')
    for split, cases in datasets.items():
        if not cases or any(c.split != split or c.review_status != 'user_approved' for c in cases):
            raise ValueError('only approved development cases are permitted')
    config = load_manifest()
    records = []
    summary = {}
    for baseline in ('minimal', 'improved'):
        summary[baseline] = {}
        for split, cases in datasets.items():
            artifacts = []
            for index, case in enumerate(cases):
                state = QuestState(case.quest_name, case.target_count, case.current_count,
                                   case.reward_description, case.reward_claimed)
                prompt = format_prompt(state, case.player_utterance, baseline=baseline)

                def guarded_generate(actual_prompt):
                    if actual_prompt != prompt:
                        raise ValueError('request pathway diverged from frozen prompt')
                    return generate(actual_prompt)

                request = RequestInput(state, case.player_utterance, case.ground_truth_action,
                                       config['character_persona'],
                                       MINIMAL_RULES if baseline == 'minimal' else config['system_rules'])
                artifact = execute_request(request, guarded_generate)
                artifacts.append(artifact)
                records.append({'baseline': baseline, 'split': split, 'case_index': index,
                                'expression_group': case.expression_group,
                                'shortcut_tags': list(case.shortcut_tags),
                                'artifact': artifact.to_dict()})
            correct = sum(a.evaluation.is_action_correct is True for a in artifacts)
            valid = sum(a.evaluation.is_format_valid for a in artifacts)
            non_other = [a for a in artifacts if a.request_input.ground_truth_action != Action.OTHER]
            summary[baseline][split] = {
                'count': len(artifacts), 'format_valid_count': valid,
                'format_validity': valid / len(artifacts), 'action_correct_count': correct,
                'action_accuracy': correct / len(artifacts),
                'other_misclassification_rate': (
                    sum(a.model_action == Action.OTHER for a in non_other) / len(non_other)
                    if non_other else None),
                'by_action': {
                    action.value: {
                        'count': sum(a.request_input.ground_truth_action == action for a in artifacts),
                        'correct': sum(a.request_input.ground_truth_action == action and
                                       a.evaluation.is_action_correct is True for a in artifacts),
                    } for action in Action
                },
            }
    report = {'run_kind': 'development_baseline_comparison', 'manifest': config,
              'minimal_rules': MINIMAL_RULES, 'summary': summary, 'records': records}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def batched_generator(prompts, generate_batch, *, batch_size: int = 8):
    """Adapt ordered, approved prompts to the single-request model boundary."""
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    from collections import deque
    pending = deque()
    index = 0

    def generate(prompt):
        nonlocal index
        if index >= len(prompts) or prompt != prompts[index]:
            raise ValueError('batch prompt order diverged from request pathway')
        if not pending:
            batch = prompts[index:index + batch_size]
            outputs = list(generate_batch(batch))
            if len(outputs) != len(batch):
                raise ValueError('batch must return exactly one output per input')
            pending.extend(outputs)
        index += 1
        return pending.popleft()

    return generate
