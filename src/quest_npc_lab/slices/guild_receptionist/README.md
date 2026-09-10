# Guild receptionist single-request slice

This slice validates one quest state and player utterance, sends only the
persona, rules, current state, and current utterance to a supplied model,
strictly parses its raw response, scores the original action, and then applies
server reward rules.

Run one request with a deterministic supplied model response:

```bash
uv run python -m quest_npc_lab.slices.guild_receptionist \
  --quest-name "늑대 소탕" \
  --target-count 5 \
  --current-count 5 \
  --reward-description "금화 100개" \
  --utterance "보상 주세요." \
  --ground-truth-action grant_reward \
  --raw-output '{"action":"grant_reward","dialogue":"보상을 드립니다."}'
```

The command prints a JSON artifact with separate request, raw output, parsed
output, model action, evaluation, server execution, and error fields. Omit
`--ground-truth-action` for an unrated open-input run. Pass the previous
artifact's `server_execution.final_state` into a later request when session
state should persist; independent calls otherwise share no mutable state.
Input validation failures use the same artifact shape with `raw_output: null`
and an `input_validation` error, and never invoke the supplied model.
