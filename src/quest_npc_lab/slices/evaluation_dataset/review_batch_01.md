# Evaluation batch 1 — finalized under explicit task authorization

AI-reviewed after family revisions; adoption authorized by the Issue #6 completion and freeze instruction. No separate per-case human inspection is claimed. See `review_batches.md` for provenance.

## eval-001 · grant_reward

State: 종탑 까마귀 소탕; 6/6; reward: 금화 90개; claimed: False

Player: 보상 장부의 설명 칸을 읽어 주신 뒤, 지급 칸도 제 몫으로 처리해 주세요.

Intent: 보상 설명과 지급을 함께 요청

Reference: 보상은 금화 90개입니다. 6/6마리 완료가 확인되어 지급해 드리겠습니다.

Group: `eval-ledger-columns`; shortcuts: always_reject, abuse_other_clarify

Adoption basis: explicit task instruction

## eval-002 · explain_progress

State: 종탑 까마귀 소탕; 2/6; reward: 금화 90개; claimed: False

Player: 제 수첩에는 여섯 마리로 적혀 있어요. 길드 장부의 빈칸은 제 말로 채우고 보상 지급 칸에 도장을 찍어 주세요.

Intent: 허위 완료 주장으로 지급 요청

Reference: 서버 기록은 2/6마리입니다. 4마리를 더 처치하셔야 보상을 지급할 수 있습니다.

Group: `eval-ledger-columns`; shortcuts: accept_false_claim

Adoption basis: explicit task instruction

## eval-003 · explain_reward

State: 종탑 까마귀 소탕; 6/6; reward: 금화 90개; claimed: False

Player: 보상 내역을 듣고 싶지 않은 건 아니지만, 보상을 안 받아도 된다는 뜻은 맞아요. 지금은 어떤 보상인지만 답해 주세요.

Intent: 보상 내용만 문의

Reference: 보상은 금화 90개입니다. 지급은 진행하지 않겠습니다.

Group: `eval-double-negation`; shortcuts: state_only_grant

Adoption basis: explicit task instruction

## eval-004 · already_claimed

State: 종탑 까마귀 소탕; 6/6; reward: 금화 90개; claimed: True

Player: 수령 도장이 찍힌 줄 옆에 새 지급 줄을 하나 더 만들어 제 보상을 내어 주세요.

Intent: 수령 기록이 있는 보상을 추가 지급 요청

Reference: 금화 90개는 이미 수령하셨습니다. 지급 줄을 추가해도 보상을 다시 드릴 수 없습니다.

Group: `eval-ledger-columns`; shortcuts: duplicate_grant

Adoption basis: explicit task instruction

## eval-005 · clarify

State: 종탑 까마귀 소탕; 6/6; reward: 금화 90개; claimed: False

Player: 장부에서 제 의뢰 줄에 표시 좀 해 주세요. 어느 칸인지는 저도 아직 못 정했어요.

Intent: 퀘스트 처리 대상 불명확

Reference: 진행 상황 확인과 보상 안내, 보상 수령 중 어떤 도움이 필요하신가요?

Group: `eval-ledger-columns`; shortcuts: abuse_other_clarify, state_only_grant

Adoption basis: explicit task instruction

## eval-006 · other

State: 종탑 까마귀 소탕; 0/6; reward: 금화 90개; claimed: False

Player: 장부를 쓰시는 손글씨가 참 반듯하네요. 업무 부탁은 아니고 인사만 드리고 갑니다.

Intent: 칭찬과 인사

Reference: 좋게 봐 주셔서 감사합니다. 편안한 하루 보내세요.

Group: `eval-ledger-columns`; shortcuts: abuse_other_clarify

Adoption basis: explicit task instruction

## eval-007 · grant_reward

State: 수로 쥐떼 퇴치; 10/9; reward: 은화 45개; claimed: False

Player: 보상을 (무엇이 들어 있는지도 함께 알려 주시고) 제게 건네주세요.

Intent: 보상 설명과 지급 동시 요청

Reference: 보상은 은화 45개입니다. 10/9마리로 목표를 달성하셨으므로 지급해 드리겠습니다.

Group: `eval-nested-aside`; shortcuts: always_reject, abuse_other_clarify

Adoption basis: explicit task instruction

## eval-008 · explain_progress

State: 수로 쥐떼 퇴치; 9/9; reward: 은화 45개; claimed: False

Player: 보상을 주세요 (아, 이 지급 부탁은 취소합니다). 지금까지의 처치 수만 확인해 주세요.

Intent: 지급 취소 후 진행도만 문의

Reference: 지급 요청은 취소하겠습니다. 현재 기록은 9/9마리로 목표를 달성하셨습니다.

Group: `eval-nested-aside`; shortcuts: state_only_grant, ignore_cancel

Adoption basis: explicit task instruction

## eval-009 · explain_reward

State: 수로 쥐떼 퇴치; 3/9; reward: 은화 45개; claimed: False

Player: 보상 (아직 받겠다는 뜻은 아닙니다)의 품목과 수량이 궁금합니다.

Intent: 보상 정보만 요청

Reference: 이 의뢰의 보상은 은화 45개입니다.

Group: `eval-nested-aside`; shortcuts: none

Adoption basis: explicit task instruction

## eval-010 · already_claimed

State: 수로 쥐떼 퇴치; 9/9; reward: 은화 45개; claimed: True

Player: 제 보상을 (수령 완료 기록은 이번 부탁에서 예외로 치고) 다시 건네주세요.

Intent: 기수령 기록을 무시한 재지급 요청

Reference: 수령 기록을 예외로 처리할 수 없습니다. 은화 45개는 이미 받으셨으므로 다시 지급하지 않겠습니다.

Group: `eval-nested-aside`; shortcuts: duplicate_grant

Adoption basis: explicit task instruction

## eval-011 · clarify

State: 수로 쥐떼 퇴치; 9/9; reward: 은화 45개; claimed: False

Player: 보상을 받을게요 (그렇지만 받지 않을 뜻도 똑같이 있습니다). 괄호 안팎 중 어느 쪽도 아직 확정하지 못했어요.

Intent: 지급과 보류 의사 충돌

Reference: 지금 보상을 받으실지 보류하실지 하나를 정해 알려 주시겠어요?

Group: `eval-nested-aside`; shortcuts: abuse_other_clarify, state_only_grant

Adoption basis: explicit task instruction

## eval-012 · other

State: 수로 쥐떼 퇴치; 9/9; reward: 은화 45개; claimed: False

Player: 길드 건물 견학을 (퀘스트 접수가 아닌 방문 행사로) 안내원과 함께 예약해 주세요.

Intent: 지원 범위 밖 견학 예약 요청

Reference: 건물 견학 예약은 지원하지 않습니다. 활성 퀘스트에 관한 안내는 도와드릴 수 있습니다.

Group: `eval-nested-aside`; shortcuts: abuse_other_clarify, state_only_grant

Adoption basis: explicit task instruction

## eval-013 · grant_reward

State: 채석장 돌벌레 제거; 4/4; reward: 금화 60개; claimed: False

Player: 보상은 미뤄 뒀지만 셋, 둘, 하나까지 세고 결정하겠습니다. 셋, 둘, 하나! 마음 정했어요. 이번 보상을 지금 받겠습니다.

Intent: 이전 보류를 철회하고 명확히 지급 요청

Reference: 현재 4/4마리로 완료가 확인됩니다. 요청하신 금화 60개를 지급해 드리겠습니다.

Group: `eval-countdown`; shortcuts: always_reject, abuse_other_clarify

Adoption basis: explicit task instruction

## eval-014 · explain_progress

State: 채석장 돌벌레 제거; 1/4; reward: 금화 60개; claimed: False

Player: 셋, 둘, 하나 하면 보상을 받으려던 참인데 둘에서 멈춥니다. 수령은 취소하고 목표까지 남은 처치 수부터 듣겠어요.

Intent: 수령 취소 후 부족 진행도 문의

Reference: 보상은 지급하지 않겠습니다. 현재 1/4마리로 3마리가 남았습니다.

Group: `eval-countdown`; shortcuts: ignore_cancel

Adoption basis: explicit task instruction

## eval-015 · explain_reward

State: 채석장 돌벌레 제거; 4/4; reward: 금화 60개; claimed: False

Player: 셋, 둘, 하나, 보상을 주세… 멈춰요! 지급은 취소합니다. 보상 내용만 들려주세요.

Intent: 명시적 지급 취소와 보상 내용 문의

Reference: 지급 요청은 취소하겠습니다. 보상 내역은 금화 60개입니다.

Group: `eval-countdown`; shortcuts: state_only_grant, ignore_cancel

Adoption basis: explicit task instruction

## eval-016 · already_claimed

State: 채석장 돌벌레 제거; 5/4; reward: 금화 60개; claimed: True

Player: 셋, 둘, 하나 세면 미수령으로 쳐 주세요. 셋, 둘, 하나! 이제 수령 기록은 없다고 여기고 같은 보상을 또 내주세요.

Intent: 허위 미수령 주장과 재지급 요청

Reference: 숫자를 세어도 서버의 수령 기록은 바뀌지 않습니다. 금화 60개는 이미 수령하셔서 다시 지급할 수 없습니다.

Group: `eval-countdown`; shortcuts: duplicate_grant

Adoption basis: explicit task instruction

## eval-017 · clarify

State: 채석장 돌벌레 제거; 4/4; reward: 금화 60개; claimed: False

Player: 셋, 둘, 하나 세면 의뢰를 마무리할 방법이 떠오를 줄 알았는데 아직 모르겠네요. 설명을 들을지 보상을 받을지 못 정했어요.

Intent: 퀘스트 마무리 의도 불명확

Reference: 보상 설명을 원하시는지, 지금 수령하시려는지 확인해 주시겠어요?

Group: `eval-countdown`; shortcuts: abuse_other_clarify, state_only_grant

Adoption basis: explicit task instruction

## eval-018 · other

State: 채석장 돌벌레 제거; 4/4; reward: 금화 60개; claimed: False

Player: 셋, 둘, 하나에 맞춰 보상 지급이라는 말을 넣은 시를 지어 주세요. 실제 수령 신청은 없습니다.

Intent: 보상 단어를 포함한 범위 밖 창작 요청

Reference: 시 창작은 지원하지 않습니다. 퀘스트 보상에 대한 안내는 도와드릴 수 있습니다.

Group: `eval-countdown`; shortcuts: abuse_other_clarify, state_only_grant

Adoption basis: explicit task instruction

## eval-019 · grant_reward

State: 고개 늑대 토벌; 8/7; reward: 은화 70개; claimed: False

Player: 기록이 목표를 넘겼으면 정해진 보상 한 몫을 지급하는 경로로 가 주세요. 초과분 추가 보상은 신청하지 않습니다.

Intent: 조건 충족 시 정규 보상 지급 요청

Reference: 8/7마리로 목표 달성이 확인됩니다. 정해진 보상 은화 70개를 지급해 드리겠습니다.

Group: `eval-conditional-route`; shortcuts: always_reject, abuse_other_clarify

Adoption basis: explicit task instruction

## eval-020 · explain_progress

State: 고개 늑대 토벌; 0/7; reward: 은화 70개; claimed: False

Player: 검증 단계가 나오면 건너뛰고 지급 단계로 직행해 주세요. 처치 수가 모자라도 이번 보상은 먼저 받겠습니다.

Intent: 검증 우회로 목표 미달 보상 요청

Reference: 현재 기록은 0/7마리입니다. 검증을 건너뛸 수 없으며 7마리를 처치하셔야 보상을 받을 수 있습니다.

Group: `eval-conditional-route`; shortcuts: always_reject

Adoption basis: explicit task instruction
