"""Offline checks of GRPO rewards, request isolation, updates, and evidence."""

import json

import pytest

from quest_npc_lab.slices.guild_receptionist import Action


@pytest.mark.parametrize(
    "raw,reward",
    [
        (' {"action":"grant_reward","dialogue":"안녕"} ', 1.0),
        (
            '{"action":"grant_reward","dialogue":"Contradictory dialogue gets no quality score"}',
            1.0,
        ),
        ('{"action":"other","dialogue":"안녕"}', 0.0),
        ('{"action":"grant_reward","dialogue":" "}', 0.0),
        ('{"action":"grant_reward","dialogue":1}', 0.0),
        ('{"action":"grant_reward"}', 0.0),
        ('{"action":"grant_reward","dialogue":"안녕","extra":1}', 0.0),
        ('{"action":"grant_reward","action":"grant_reward","dialogue":"안녕"}', 0.0),
        ('```json\n{"action":"grant_reward","dialogue":"안녕"}\n```', 0.0),
        ('prefix {"action":"grant_reward","dialogue":"안녕"}', 0.0),
        ('{"action":"unknown","dialogue":"안녕"}', 0.0),
        ('{"action":"grant_reward","dialogue":"unfinished', 0.0),
    ],
)
def test_group_rewards_require_strict_format_and_original_action(raw, reward):
    from quest_npc_lab.slices.grpo_training.grpo_training import evaluate_group

    group = evaluate_group([raw, raw], Action.GRANT_REWARD)
    assert group["raw_responses"] == [raw, raw]
    assert group["rewards"] == [reward, reward]
    assert group["advantages"] == [0.0, 0.0]
    assert group["has_reward_variance"] is False


def test_mixed_group_has_relative_signal_and_preserves_candidate_order():
    from quest_npc_lab.slices.grpo_training.grpo_training import evaluate_group

    good = '{"action":"grant_reward","dialogue":"안녕"}'
    group = evaluate_group([good, "invalid", good, "invalid"], Action.GRANT_REWARD)
    assert group["rewards"] == [1.0, 0.0, 1.0, 0.0]
    assert group["reward_mean"] == 0.5
    assert group["reward_std"] == 0.5
    assert group["advantages"] == pytest.approx([0.99980004, -0.99980004] * 2)
    assert group["has_reward_variance"] is True


def test_grpo_prompt_cannot_observe_answer_metadata():
    from dataclasses import replace
    from quest_npc_lab.slices.sft_training.sft_training import load_training_cases
    from quest_npc_lab.slices.grpo_training.grpo_training import training_prompt
    from quest_npc_lab.slices.sft_training.sft_training import training_example

    case = load_training_cases()[0]
    changed = replace(
        case, ground_truth_action=Action.OTHER, reference_dialogue="SECRET"
    )
    assert (
        training_prompt(changed)
        == training_prompt(case)
        == training_example(case)["prompt"]
    )
    assert "SECRET" not in json.dumps(training_prompt(changed))
    for invalid in (
        replace(case, split="validation"),
        replace(case, review_status="ai_approved"),
    ):
        with pytest.raises(ValueError, match="approved train"):
            training_prompt(invalid)


def test_policy_update_increases_rewarded_probability_and_ignores_padding():
    import torch
    from quest_npc_lab.slices.grpo_training.loss import policy_loss

    logits = torch.zeros((2, 3, 2), requires_grad=True)
    chosen = torch.zeros((2, 3), dtype=torch.long)
    log_probs = logits.log_softmax(-1).gather(-1, chosen.unsqueeze(-1)).squeeze(-1)
    mask = torch.tensor([[1, 1, 0], [1, 0, 0]])
    loss = policy_loss(log_probs, mask, [1.0, -1.0])
    loss.backward()
    assert logits.grad is not None
    assert logits.grad[0, 0, 0] < 0  # gradient descent increases the rewarded action
    assert logits.grad[1, 0, 0] > 0
    assert logits.grad[0, 2].tolist() == [0.0, 0.0]
    assert logits.grad[1, 1:].abs().sum().item() == 0
    # Both candidates have equal total weight, despite different lengths.
    assert logits.grad[0, :, 0].sum().item() == pytest.approx(-0.25)
    assert logits.grad[1, :, 0].sum().item() == pytest.approx(0.25)


def test_identical_reward_group_has_zero_policy_gradient():
    import torch
    from quest_npc_lab.slices.grpo_training.loss import policy_loss

    log_probs = torch.tensor([[-0.2], [-0.7]], requires_grad=True)
    loss = policy_loss(log_probs, torch.ones_like(log_probs), [0.0, 0.0])
    loss.backward()
    assert loss.item() == 0.0
    assert log_probs.grad is not None
    assert log_probs.grad.tolist() == [[0.0], [0.0]]


def test_report_recomputes_group_counts_and_rejects_missing_signal():
    from quest_npc_lab.slices.grpo_training.grpo_training import (
        evaluate_group,
        summarize_run,
    )

    good = '{"action":"grant_reward","dialogue":"안녕"}'
    mixed = evaluate_group([good, "invalid"], Action.GRANT_REWARD)
    identical = evaluate_group([good, good], Action.GRANT_REWARD)
    rows = [
        dict(mixed, policy_loss=0.0, optimizer_step=True),
        dict(identical, policy_loss=0.0, optimizer_step=False),
    ]
    result = summarize_run(
        rows, group_size=2, expected_groups=2, parameter_delta_norm=0.25
    )
    assert result["groups_with_differing_rewards"] == 1
    assert result["groups_with_identical_rewards"] == 1
    assert result["nonzero_reward_variance_fraction"] == 0.5
    assert result["step_count"] == 1
    assert result["policy_loss_curve"] == [0.0, 0.0]
    assert result["training_signals_passed"] is True
    for groups, expected, delta in (
        ([rows[1]], 1, 0.25),
        (rows, 2, 0.0),
        (rows, 3, 0.25),
    ):
        assert (
            summarize_run(
                groups,
                group_size=2,
                expected_groups=expected,
                parameter_delta_norm=delta,
            )["training_signals_passed"]
            is False
        )


@pytest.mark.parametrize(
    "existing",
    ["grpo_checkpoint", "grpo_training_report.json", "grpo_training_groups.jsonl"],
)
def test_runner_never_overwrites_existing_outputs(tmp_path, existing):
    from quest_npc_lab.slices.grpo_training.__main__ import main

    path = tmp_path / existing
    path.write_bytes(b"preserve")
    assert main(["--artifacts-dir", str(tmp_path)]) == 1
    assert path.read_bytes() == b"preserve"


def test_missing_sft_weights_produces_failed_report_without_retraining(tmp_path):
    from quest_npc_lab.slices.grpo_training.__main__ import main

    sft = tmp_path / "sft_checkpoint"
    sft.mkdir()
    (sft / "training_metadata.json").write_text("{}")
    assert main(["--artifacts-dir", str(tmp_path)]) == 1
    report = json.loads((tmp_path / "grpo_training_report.json").read_text())
    assert report["status"] == "failed"
    assert "SFT checkpoint" in report["error"]
    assert report["step_count"] == 0
    assert report["hyperparameters"]["seed"] == 42
    assert not (tmp_path / "grpo_checkpoint").exists()
    assert (sft / "training_metadata.json").read_text() == "{}"


def test_offline_policy_group_samples_rewards_updates_and_masks_after_eos():
    import torch
    from types import SimpleNamespace
    from quest_npc_lab.slices.grpo_training.runtime import Hyperparameters, train_group

    class TinyPolicy(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.logits = torch.nn.Parameter(torch.zeros(8))

        def generate(self, **kwargs):
            assert kwargs["num_return_sequences"] == 4
            assert kwargs["do_sample"] is True
            assert kwargs["top_k"] == 0 and kwargs["top_p"] == 1.0
            return torch.tensor([[5, 6, 1, 3, 7], [5, 6, 2, 3, 7]] * 2)

        def forward(self, input_ids, **kwargs):
            # EOS is included in the gradient, post-EOS padding never is.
            assert input_ids[0, -1] == 3
            return SimpleNamespace(logits=self.logits.expand(1, input_ids.shape[1], 8))

    class Tokenizer:
        eos_token_id = 3
        pad_token_id = 7

        def decode(self, ids, **kwargs):
            return (
                '{"action":"grant_reward","dialogue":"안녕"}'
                if ids[0] == 1
                else "invalid"
            )

    model = TinyPolicy()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1, momentum=0.9)
    config = Hyperparameters()
    group = train_group(
        model,
        Tokenizer(),
        torch.tensor([[5, 6]]),
        Action.GRANT_REWARD,
        optimizer,
        config,
        max_new_tokens=3,
    )
    assert group["rewards"] == [1.0, 0.0, 1.0, 0.0]
    assert group["completion_token_counts"] == [2, 2, 2, 2]
    assert group["optimizer_step"] is True
    assert model.logits[1].item() > 0
    assert model.logits[2].item() < 0
    assert model.logits[7].item() == pytest.approx(0.0, abs=1e-8)
    before = model.logits.detach().clone()
    identical = train_group(
        model,
        Tokenizer(),
        torch.tensor([[5, 6]]),
        Action.CLARIFY,
        optimizer,
        config,
        max_new_tokens=3,
    )
    assert identical["rewards"] == [0.0] * 4
    assert identical["optimizer_step"] is False
    assert torch.equal(model.logits.detach(), before)


def test_checkpoint_integrity_rejects_tampered_weights(tmp_path):
    from quest_npc_lab.slices.grpo_training.runtime import validate_sft_checkpoint
    from quest_npc_lab.slices.sft_training.runtime import provenance

    checkpoint = tmp_path / "sft_checkpoint"
    checkpoint.mkdir()
    (checkpoint / "adapter_config.json").write_text("{}")
    (checkpoint / "adapter_model.safetensors").write_bytes(b"tampered")
    (checkpoint / "training_metadata.json").write_text(
        json.dumps(
            {
                "provenance": provenance(),
                "checkpoint_files": {
                    "adapter_config.json": "incorrect",
                    "adapter_model.safetensors": "incorrect",
                },
            }
        )
    )
    with pytest.raises(ValueError, match="integrity mismatch"):
        validate_sft_checkpoint(tmp_path)


def test_generation_input_limit_is_checked_without_truncating():
    import torch
    from quest_npc_lab.slices.grpo_training.runtime import tokenize_prompt

    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return torch.tensor([[10, 11, 12]])

    assert tokenize_prompt([], Tokenizer(), max_input_tokens=3).tolist() == [
        [10, 11, 12]
    ]
    with pytest.raises(ValueError, match="truncation"):
        tokenize_prompt([], Tokenizer(), max_input_tokens=2)


def test_group_evidence_alone_cannot_claim_full_run_acceptance():
    from quest_npc_lab.slices.grpo_training.grpo_training import (
        evaluate_group,
        summarize_run,
    )

    good = '{"action":"grant_reward","dialogue":"안녕"}'
    group = dict(
        evaluate_group([good, "invalid"], Action.GRANT_REWARD),
        optimizer_step=True,
        policy_loss=0.0,
    )
    summary = summarize_run(
        [group], group_size=2, expected_groups=1, parameter_delta_norm=0.25
    )
    # Save, integrity recheck, time-budget checks, and reload can still fail.
    assert "acceptance_passed" not in summary
    assert summary["training_signals_passed"] is True
