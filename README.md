# Quest NPC Lab

**자연스러운 NPC 대사와 올바른 행동 선택은 같은 능력일까?** 한국어 길드
접수원이 플레이어 요청과 신뢰할 서버 상태를 함께 판단하도록 프롬프트 개선 →
LoRA SFT → GRPO를 비교한 연구 포트폴리오입니다.

실제 네 조건의 **240개 응답과 정량 평가가 저장되어 있습니다.**
[원본 응답](artifacts/final_240_responses.jsonl) ·
[평가 보고서와 실패 목록](artifacts/final_evaluation_report.json) ·
[실행 환경과 provenance](artifacts/final_evaluation_run.json) ·
[Pages/Spaces 빌드·배포 안내](src/quest_npc_lab/slices/public_showcase/README.md)

공개 데모는 빌드 가능한 번들로 제공합니다. 공개 Pages/Spaces의 실제 배포
성공을 주장하지 않습니다. 자격·공개 어댑터 위치·호스팅 검증은
[배포 상태](src/quest_npc_lab/slices/public_showcase/README.md#deployment-status)에 기록합니다.

## 문제와 처리 경계

서버는 활성 퀘스트 하나의 목표·처치 수·보상·수령 여부를 관리합니다.
NPC는 현재 발화와 상태에서 `grant_reward`, `explain_progress`, `explain_reward`,
`already_claimed`, `clarify`, `other` 중 하나와 대사를 JSON으로 출력합니다.
허위 완료 주장, 재지급 요청, 지급 취소, 설명과 지급의 복합 요청을 다룹니다.
JSON 보정이나 실패한 응답 재생성은 없습니다.

**모델의 원래 행동 정확도와 서버 실행 승인은 별개**입니다. 상태 가드는
잘못된 상태 변경을 차단하며, 자유 입력에는 정답 라벨을 만들어 붙이지 않습니다.
대화 간 서버 상태는 유지하되 이전 대화 이력은 모델 입력에 포함하지 않습니다.

## 실제 결과

동일한 미학습 표현 평가 60건 × 네 조건. 정답 행동은 각 10건씩 균형 구성입니다.

| 조건 | 가중치 / 프롬프트 | 행동 정답 | 정확도 | 형식 유효 |
|---|---|---:|---:|---:|
| Base Minimal | 원본 / 최소 | 0 / 60 | 0.0% | 0 / 60 |
| Base Improved | 원본 / 개선 | 0 / 60 | 0.0% | 0 / 60 |
| SFT Improved | LoRA SFT / 개선 | 16 / 60 | 26.7% | 60 / 60 |
| SFT+GRPO | SFT 이후 GRPO / 같은 개선 | 19 / 60 | 31.7% | 60 / 60 |

SFT 대비 GRPO는 **+5.0%p, 추가 정답 3개**입니다. 두 Base 조건은 모든 응답이
엄격한 JSON 계약을 위반했습니다. SFT와 GRPO는 형식이 모두 유효하지만 행동은
각각 44건, 41건 틀렸습니다. 형식 학습과 행동 정확도를 구분해 읽어야 합니다.

**남아 있는 연구 한계:** 최종 실행은 현재 SFT 어댑터와 GRPO 부모의 일치를
확인했지만, 현재 SFT 메타데이터가 과거 SFT 학습 보고서와 다릅니다. 과거
업데이트·재로딩 증거가 이번 SFT 어댑터를 입증하지 않는다는 경고를 보존합니다.
이 차이를 해결하기 전에는 완전히 검증된 GRPO 인과 효과라고 주장할 수 없습니다.

[블라인드 대사 표본 48개](artifacts/dialogue_review_48_blind.md)의 사람 평가는
아직 완료되지 않았습니다. [각 평가 기준](artifacts/dialogue_review_summary.json)에서
24건은 대기, 형식 오류 24건은 평가 불가입니다. 행동 정확도는 대사 자연스러움,
캐릭터성, 사람 선호 개선의 증거가 아닙니다.

## Vertical Slice Architecture

기능의 입력·규칙·실행·상태 변경·테스트를 `src/quest_npc_lab/slices/` 아래에
함께 둡니다. 공통 기술 계층으로 나누지 않고 검증된 공통 기능만 재사용합니다.

| Slice | 책임 |
|---|---|
| `guild_receptionist` | 요청 검증, 엄격한 파싱, 원래 행동 채점, 서버 승인과 상태 전이 |
| `dataset_pipeline`, `evaluation_dataset` | 승인 데이터, 표현 그룹 분리, 최종 60건 고정 |
| `prompt_evaluation`, `model_smoke` | 프롬프트 고정, 개발 비교, 모델 실행 점검 |
| `sft_training`, `grpo_training` | LoRA 업데이트, 보상, 체크포인트와 실행 증거 |
| `final_evaluation` | 240개 원본 생성, 지표 재계산, 블라인드 대사 검토 |
| `interactive_ui`, `reaction_media` | 자유 입력 비교, 세션 격리, 승인 상태에 맞는 SVG |
| `public_showcase` | Pages 빌더·정적 자산·Spaces 설정·재현 검증 테스트 |

Pages는 같은 입력의 저장된 네 출력을 보여줍니다. 로컬/Spaces는 자유 입력을
실제 모델에 전달합니다. SVG 미소는 서버가 지급을 승인한 뒤에만 표시합니다.
런타임 영상 생성이나 유료 API는 없습니다.

<a id="reproduction"></a>
## 재현

Python 3.12와 uv를 준비하고 저장소 루트에서 실행합니다. `uv.lock`으로
라이브러리 환경을 고정합니다.

```bash
uv sync --locked
uv run pytest

# 모델 없이 원본에서 정량 지표를 다시 계산합니다.
uv run python -m quest_npc_lab.slices.final_evaluation --recompute

# 새 디렉터리에 정적 Pages를 생성합니다. 외부 웹 의존성은 없습니다.
uv run python -m quest_npc_lab.slices.public_showcase pages
python -m http.server 8080 --bind 127.0.0.1 \
  --directory src/quest_npc_lab/slices/public_showcase/build/pages
```

`http://127.0.0.1:8080`에서 60개 사례, 240개 원시 응답, 네 조건 비교,
실패 분석과 자료 링크를 확인합니다. 빌더는 기존 디렉터리를 덮어쓰지 않습니다.
다시 빌드할 때는 `--output <새 디렉터리>`를 사용하세요.

### 로컬 실제 추론

고정 기반 모델을 캐시에 준비합니다. 다음 다운로드는 최초 한 번 필요합니다.

```bash
uv run hf download Qwen/Qwen2.5-0.5B-Instruct \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775

# 보존된 전체 어댑터 폴더를 artifacts/{sft,grpo}_checkpoint에 준비한 뒤:
uv run python -m quest_npc_lab.slices.interactive_ui

# 활성 가상환경에서는 같은 명령을 직접 실행할 수 있습니다.
source .venv/bin/activate
python -m quest_npc_lab.slices.interactive_ui
```

`http://127.0.0.1:8000`에서 같은 시작 상태로 비교하거나 한 조건을 계속합니다.
최종 평가와 같은 고정 프롬프트·모델 revision·128-token greedy가 기본값입니다.
어댑터 경로는 `--sft-checkpoint`, `--grpo-checkpoint`로 지정할 수 있습니다.
GPU가 없으면 CPU를 사용하며 결과·속도가 달라질 수 있습니다. `--offline`은
명시적으로 표시된 UI 테스트 대역이며 모델 성과가 아닙니다.

Git clone에는 **어댑터 가중치가 없습니다**. `adapter_config.json`,
`adapter_model.safetensors`, `training_metadata.json` 전체를 준비해야 합니다.
현재 공개 Hub 어댑터 주소는 등록되지 않았습니다. 정확한 최종 어댑터를 구하지
못하면 원본 지표 재계산은 가능하지만 동일 체크포인트 재추론은 불가능합니다.
새 학습을 같은 어댑터 복원으로 간주하지 마세요.

### 학습과 평가 실행 경로

다음은 GPU·시간이 필요한 별도 재실행입니다. 기존 결과 보존과 각 CLI 옵션은
[SFT](src/quest_npc_lab/slices/sft_training/README.md),
[GRPO](src/quest_npc_lab/slices/grpo_training/README.md),
[최종 평가](src/quest_npc_lab/slices/final_evaluation/README.md)를 참조하세요.
아래는 새 아티팩트 루트에서의 실행 순서입니다.

```bash
uv run python -m quest_npc_lab.slices.sft_training --artifacts-dir artifacts/reproduction
uv run python -m quest_npc_lab.slices.grpo_training --artifacts-dir artifacts/reproduction
uv run python -m quest_npc_lab.slices.final_evaluation \
  --checkpoint-dir artifacts/reproduction --output-dir artifacts/reproduction/final
```

기록된 최종 환경: Python 3.12.10, PyTorch 2.14.0, Transformers 5.16.1,
PEFT 0.20.0, RTX 3060, float32, batch 1. Seed 42, `do_sample=False`,
`max_new_tokens=128`, 재시도 0. 240개 생성 시간은 1111.6초입니다.
학습/검증/평가 데이터는 180/60/60건이며 승인·해시를 유지합니다.
[고정 프롬프트](src/quest_npc_lab/slices/prompt_evaluation/prompt_manifest.json),
[평가 manifest](src/quest_npc_lab/slices/evaluation_dataset/data/eval_manifest.json),
[최종 SFT](artifacts/sft_checkpoint/training_metadata.json),
[최종 GRPO](artifacts/grpo_checkpoint/training_metadata.json)에 버전·해시가 있습니다.

## 해석 범위와 공개 권리

- 단일 seed와 균형 평가 60건의 탐색적 비교입니다. 반복적으로 안정적인 개선,
  실제 서비스 빈도에서의 성능, 미학습 게임 규칙 일반화를 입증하지 않습니다.
- 한 응답의 의사결정만 다룹니다. 장기 기억·계획·멀티턴 RL은 범위 밖입니다.
- 보상은 엄격한 형식과 행동 정답이 맞으면 1, 그 외 0입니다. 사람 선호 학습이 아닙니다.
- 대사 평가는 한 명의 소규모 검토를 예정했으며 현재 판정 대기입니다.
- SVG는 [CC0-1.0](src/quest_npc_lab/slices/reaction_media/media_manifest.json),
  기반 Qwen은 [Apache-2.0](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/blob/7ae557604adf67be50417f59c2c2f167def9a775/README.md)입니다.
  합성 데이터와 파생 어댑터의 별도 공개 재배포 라이선스는 아직 지정되지 않았습니다.
  가중치 공개 위치와 권리를 확인한 뒤 Spaces의 어댑터를 설정해야 합니다.

[합의된 설계](docs/design.md) · [명세 #1](https://github.com/ahfmrptEkd/quest-npc-lab/issues/1) ·
[데이터 조사](docs/dataset-research.md) · [공개 티켓 #13](https://github.com/ahfmrptEkd/quest-npc-lab/issues/13)
