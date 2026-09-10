"""Offline tests at formatting, frozen config, data and execution boundaries."""
import json

from quest_npc_lab.slices.guild_receptionist import QuestState
from quest_npc_lab.slices.prompt_evaluation import format_prompt, load_manifest


def test_frozen_prompt_formats_only_current_state_and_utterance():
    config = load_manifest()
    state = QuestState('늑대', 5, 3, '금화 100개', False)
    payload = json.loads(format_prompt(state, '보상 주세요.'))
    assert set(payload) == {'character_persona', 'rules', 'server_state', 'player_utterance'}
    assert payload['server_state']['current_count'] == 3
    assert payload['player_utterance'] == '보상 주세요.'
    assert payload['rules'] == config['system_rules']
    assert config['seed'] == 42
    assert config['generation'] == {'max_new_tokens': 128, 'do_sample': False, 'temperature': 0.0}
    assert config['model_name'] == 'Qwen/Qwen2.5-0.5B-Instruct'


def test_comparison_scores_original_actions_and_never_retries(tmp_path):
    from quest_npc_lab.slices.prompt_evaluation import compare_baselines, load_development_data
    cases = load_development_data()['validation'][:2]
    seen = []
    outputs = iter(['{"action":"grant_reward","dialogue":"지급"}', 'broken'] * 2)

    def generate(prompt):
        seen.append(json.loads(prompt))
        return next(outputs)

    report = compare_baselines({'validation': cases}, generate, tmp_path / 'report.json')
    assert len(seen) == 4
    assert [p['server_state'] for p in seen[:2]] == [p['server_state'] for p in seen[2:]]
    assert all(set(p) == {'character_persona', 'rules', 'server_state', 'player_utterance'} for p in seen)
    assert report['summary']['minimal']['validation']['format_valid_count'] == 1
    assert report['summary']['minimal']['validation']['action_accuracy'] == 0.5
    assert report['summary']['improved']['validation']['action_accuracy'] == 0.5
    assert report['records'][1]['artifact']['raw_output'] == 'broken'
    assert report['records'][1]['artifact']['evaluation']['is_action_correct'] is False
    assert json.loads((tmp_path / 'report.json').read_text()) == report


def test_manifest_tampering_is_rejected(tmp_path, monkeypatch):
    import pytest
    from quest_npc_lab.slices.prompt_evaluation import prompt_evaluation as module
    path = tmp_path / 'prompt_manifest.json'
    path.write_bytes(module.MANIFEST_PATH.read_bytes().replace(b'128', b'129'))
    path.with_suffix('.sha256').write_bytes(module.MANIFEST_PATH.with_suffix('.sha256').read_bytes())
    monkeypatch.setattr(module, 'MANIFEST_PATH', path)
    with pytest.raises(ValueError, match='integrity'):
        load_manifest()


def test_development_loader_opens_only_allowlisted_files(monkeypatch):
    from pathlib import Path
    from quest_npc_lab.slices.prompt_evaluation import load_development_data
    original = Path.open
    allowed = {'train_180.jsonl', 'val_60.jsonl', 'train_180_review_batches.json',
               'val_60_review_batches.json'}
    opened = set()

    def guarded_open(path, *args, **kwargs):
        assert path.name in allowed
        opened.add(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded_open)
    data = load_development_data()
    assert {split: len(cases) for split, cases in data.items()} == {'train': 180, 'validation': 60}
    assert opened == allowed


def test_comparison_rejects_non_development_or_unapproved_cases_before_generation(tmp_path):
    from dataclasses import replace
    import pytest
    from quest_npc_lab.slices.prompt_evaluation import compare_baselines, load_development_data
    case = load_development_data()['train'][0]

    def forbidden(_):
        raise AssertionError('must reject before generation')

    for data in ({'held_out': [case]}, {'train': [replace(case, review_status='ai_approved')]},
                 {'validation': [case]}, {'train': []}):
        with pytest.raises(ValueError):
            compare_baselines(data, forbidden, tmp_path / 'report.json')


def test_answer_metadata_cannot_change_model_input(tmp_path):
    from dataclasses import replace
    from quest_npc_lab.slices.guild_receptionist import Action
    from quest_npc_lab.slices.prompt_evaluation import compare_baselines, load_development_data
    case = load_development_data()['train'][0]
    seen = []

    def generate(prompt):
        seen.append(prompt)
        return '{"action":"other","dialogue":"안녕하세요"}'

    changed = replace(case, ground_truth_action=Action.OTHER, reference_dialogue='SECRET ANSWER',
                      player_intent='SECRET INTENT')
    compare_baselines({'train': [case, changed]}, generate, tmp_path / 'report.json')
    assert seen[0] == seen[1]
    assert seen[2] == seen[3]
    assert not any('SECRET' in prompt for prompt in seen)


def test_scoring_does_not_confuse_server_approval_with_correctness(tmp_path):
    from dataclasses import replace
    from quest_npc_lab.slices.guild_receptionist import Action
    from quest_npc_lab.slices.prompt_evaluation import compare_baselines, load_development_data
    case = load_development_data()['train'][0]
    cases = [replace(case, ground_truth_action=Action.EXPLAIN_REWARD),
             replace(case, current_count=0, ground_truth_action=Action.EXPLAIN_PROGRESS)]
    report = compare_baselines({'train': cases},
                              lambda _: '{"action":"grant_reward","dialogue":"지급"}',
                              tmp_path / 'report.json')
    assert report['summary']['minimal']['train']['action_accuracy'] == 0.0
    assert report['records'][0]['artifact']['server_execution']['approved'] is True
    assert report['records'][1]['artifact']['server_execution']['approved'] is False
    assert all(r['artifact']['model_action'] == 'grant_reward' for r in report['records'])


def test_manifest_copy_cannot_change_subsequent_experiment_configuration():
    config = load_manifest()
    config['generation']['max_new_tokens'] = 1
    config['system_rules'] = 'changed'
    assert load_manifest()['generation']['max_new_tokens'] == 128
    assert load_manifest()['system_rules'] != 'changed'


def test_batched_generator_preserves_order_and_generates_each_input_once():
    from quest_npc_lab.slices.prompt_evaluation.prompt_evaluation import batched_generator
    calls = []

    def generate_batch(prompts):
        calls.append(list(prompts))
        return [prompt.upper() for prompt in prompts]

    generate = batched_generator(['a', 'b', 'c'], generate_batch, batch_size=2)
    assert [generate(p) for p in ['a', 'b', 'c']] == ['A', 'B', 'C']
    assert calls == [['a', 'b'], ['c']]


def test_batch_order_or_output_count_mismatch_stops_without_retry():
    import pytest
    from quest_npc_lab.slices.prompt_evaluation.prompt_evaluation import batched_generator
    calls = []

    def generate_batch(prompts):
        calls.append(list(prompts))
        return []

    generate = batched_generator(['expected'], generate_batch)
    with pytest.raises(ValueError, match='order'):
        generate('unexpected')
    assert calls == []
    with pytest.raises(ValueError, match='exactly one'):
        generate('expected')
    assert calls == [['expected']]
