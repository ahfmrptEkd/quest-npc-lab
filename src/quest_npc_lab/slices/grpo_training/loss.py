"""Single-update, sequence-normalized GRPO policy objective (KL coefficient zero)."""


def policy_loss(log_probs, completion_mask, advantages):
    """On-policy ratio has value one and a nonzero score-function gradient.

    One update per fresh group makes clipping inactive. Average valid completion
    tokens per candidate, then candidates per group; prompt/padding are excluded.
    """
    import torch

    if log_probs.ndim != 2 or log_probs.shape != completion_mask.shape:
        raise ValueError(
            "log probabilities and completion mask must be matching matrices"
        )
    advantage = torch.as_tensor(
        advantages, dtype=log_probs.dtype, device=log_probs.device
    )
    if advantage.shape != (log_probs.shape[0],):
        raise ValueError("one advantage is required per candidate")
    lengths = completion_mask.sum(dim=1)
    if (
        (lengths <= 0).any()
        or not torch.isfinite(log_probs).all()
        or not torch.isfinite(advantage).all()
    ):
        raise ValueError(
            "finite probabilities/advantages and nonempty completions required"
        )
    ratio = (log_probs - log_probs.detach()).exp()
    return -((ratio * completion_mask).sum(dim=1) / lengths * advantage).mean()
