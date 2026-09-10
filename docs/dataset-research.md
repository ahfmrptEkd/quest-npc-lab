# Quest NPC Lab 공개 데이터셋 조사

확인일: 2026-09-09. 기준: [설계](design.md). 공식 저장소·배포기관·원 논문으로 후보 4개만 조사했다. 검색 6회, 고유 URL 본문 조회 15개(404 1개 포함); 일시적 요청 제한은 재시도했다. 데이터셋 전체 다운로드·구현·실험은 하지 않았다. 아래 적용 판단은 문서·스키마 수준이며, 실제 데이터 전수 검증 결과가 아니다.

## 결론

**조사한 후보 중 그대로 학습·평가에 사용할 수 있는 데이터셋은 없다.** 한국어 판타지 접수원, 신뢰할 서버의 처치 진행도·보상 수령 여부, 사용자 최종 의도와 취소, 다음 6개 정답 행동을 함께 제공하는 후보는 확인되지 않았다.

`grant_reward` · `explain_progress` · `explain_reward` · `already_claimed` · `clarify` · `other`

- **최우선 참고: ABCD** — 사용자 요구와 업무 정책을 함께 고려한 행동 선택 구조.
- **한국어 보조 자료: KLUE-DST / Wizard-of-Seoul(WoS)** — 한국어 문의·되묻기 표현과 상태 주석. 조건을 지켜 원문 재사용은 가능하지만, 퀘스트 정답 데이터로는 재작성·재주석이 필요하다.
- **LIGHT는 캐릭터·세계 맥락 참고**, **MultiWOZ는 의도·슬롯·대화 행위 분리 참고**로 한정하는 편이 적합하다.
- 가장 작은 권장 경로는 **구조만 참고하여 프로젝트 규칙에 맞는 한국어 예문과 서버 상태 조합을 독립 작성**하는 것이다. 번역만으로는 규칙·행동·취소 라벨의 공백이 해결되지 않는다.

## 후보 비교

| 후보 / 확인된 규모 | 언어·배경 | 상태·행동 주석 | 취소 확인 | 프로젝트 적용 판정 |
|---|---|---|---|---|
| **ABCD v1.1**: 공식 README 기준 1만 건 이상 대화, 55개 의도, 30개 버튼 행동 [A1] | 영어 쇼핑 고객 상담. 한국어판은 확인 못 함 | 시나리오, 정책 지침, flow/subflow 의도, next-step, 행동, 슬롯 값 [A1,A2] | `manage_cancel`, `cancel shipment` 확인. **주문 취소이지 앞선 발화의 요청 철회 주석은 아님** [A2] | 직접 사용 불가. 정책 조건부 행동의 **구조 참고 1순위**; 원문 재배포 권한은 아래 유보 |
| **KLUE-DST / WoS**: 논문 전체 10,000대화·146,692턴, train/dev/test 8,000/1,000/1,000 [K2 §3.8, 표26] | 한국어 서울 관광·예약, 5개 도메인 | 사용자 턴의 누적 슬롯-값 상태. 필수 값 확인·되묻기 지침은 있으나 프로젝트 행동 라벨은 없음 [K2 §3.8] | 별도 취소 의도·철회 라벨 및 해당 사례 수는 **미확인** | 조건부 **한국어 보조 재사용 후보**. 퀘스트 상태·6개 행동은 새로 작성해야 함 |
| **LIGHT 원본**: 공식 페이지의 약 11,000 상호작용 에피소드 [L1] | 영어 판타지 역할극. 한국어판은 확인 못 함 | 장소·물체·인물·페르소나, 발화·행동·감정 표현과 세계 맥락 [L1,L3] | 명시적인 요청 철회 라벨은 **미확인** | **참고 전용 권고**. 말투·캐릭터 맥락은 유용하지만 퀘스트 보상 정책 정답이 아님 |
| **MultiWOZ 2.2**: 원본 계열 2.1은 10,438대화 [M3]; 2.2 문서는 무효 대화 1개 제거 명시 [M2] | 영어 여행·예약. 한국어판은 확인 못 함 | `active_intent`, `requested_slots`, `slot_values`, span 및 별도 대화 행위 주석 [M2] | 스키마의 의도는 `find`/`book`; 명시적 `cancel` 의도는 없음. 취소 발화 자체의 부재를 뜻하지 않음 [M2] | **참고 전용 권고**. 의도·문의 대상·상태 분리에 유용하나 서버 권한 판정과 다름 |

규모는 원 출처의 단위·버전을 유지했다. WoS의 논문 전체 규모를 현재 공개 다운로드 가능 수량으로 보장하지 않으며, LIGHT 원본에 WILD나 후속 퀘스트 자료 규모를 합산하지 않았다.

## 후보별 필요한 적응

### 1. ABCD — 행동 정책 구조가 가장 가까움

공식 설명은 환불 요청을 받더라도 신원·구매 조건 등 정책을 확인해야 한다고 명시한다. 대화 턴에 `take_action` / `retrieve_utterance` / `end_conversation`과 버튼 행동·값을 구분한다. 사용자 의도와 실행 조건을 분리한다는 점이 가장 가깝다. [A1]

다만 `scenario`의 정답 의도는 수집용 정보이며 사용자에게 직접 제시되지 않는다고 설명한다. 이를 모델 입력에 그대로 넣으면 의도 정답이 누출된다. 또한 주문·계정 시나리오는 게임 서버의 처치 수·수령 여부가 아니다. [A1]

**적응:** 상담 다단계 절차를 한 응답의 결정으로 축소하고, 한국어 접수원 대사·게임 상태·6개 행동을 새로 주석해야 한다. `offer-refund`를 `grant_reward`로 이름만 바꾸는 방식은 부적절하다. 주문 취소 사례와 동일 발화 안의 지급 요청 철회 사례도 분리해야 한다. [A2; 적용 판단]

### 2. WoS — 한국어 문의·되묻기 표현의 가장 실용적인 후보

한 작업자가 사용자와 시스템을 번갈아 연기하는 self-dialog 방식이다. 논문은 애매한 표현을 먼저 되묻고 슬롯을 채우도록 지시하며, 필수 슬롯 누락 시 질문을 허용한다. 이는 `clarify` 표현 참고에 유용하지만 **퀘스트 의도 모호함과 예약 정보 부족은 같은 정답 조건이 아니다.** [K2 §3.8.1]

**적응:** 관광·예약을 길드 접수원 대화로 재작성하고 한국어 높임말·판타지 어휘를 검토한다. 사용자 말에서 추론하는 누적 대화 상태를 신뢰할 게임 상태로 간주하지 않는다. 지급·정보 문의·재지급 요청·취소·범위 밖 의도와 6개 행동은 별도로 라벨링한다. 원문의 `None`·`Dontcare`를 각각 `clarify`·`other`로 자동 매핑하지 않는다. [K2; 적용 판단]

### 3. LIGHT — 판타지 분위기는 맞지만 보상 정책은 맞지 않음

세계 맥락에 근거해 말하고 행동하는 역할극 자료다. 공식 페이지는 원본, WILD, 후속 퀘스트 자료를 구분하므로 “LIGHT에 퀘스트가 있다”는 사실만으로 원본에 접수원 보상 판정 라벨이 있다고 볼 수 없다. [L1]

**적응:** 원문 사용 권한을 먼저 확인하고, 사용한다면 한국어 번역·접수원 역할 선별·말투 검토가 필요하다. 목표 처치 수·현재 처치 수·보상·수령 여부 및 정책 정답은 별도 구성해야 한다. 현재는 원문을 가져오기보다 캐릭터와 환경 맥락을 분리하는 구조만 참고한다. [L1,L3; 적용 판단]

### 4. MultiWOZ — 대화 상태 추적과 서버 상태의 차이를 보여주는 참고 자료

2.2는 의도, 요청 슬롯, 슬롯 값을 분리하고 대화 행위 주석도 제공한다. 하지만 공식 문서는 749턴에 표현 가능한 행위가 없어 주석이 남아 있지 않다고 명시한다. 누락 주석을 `other`로 간주하면 안 된다. [M2]

**적응:** 다중 도메인을 단일 퀘스트로 축소하고 한국어로 재작성한다. 예약 관련 `booked`나 대화 속 슬롯은 서버의 `reward_claimed`를 대신하지 못한다. `find`/`book` 및 대화 행위를 6개 행동으로 재정의하고 요청 철회·재지급 거절·사용자 허위 주장 사례를 추가해야 한다. [M1,M2; 적용 판단]

## 데이터와 코드 라이선스 — 공개 재배포 판단

공개 저장소 접근 가능, 논문의 공개 라이선스, 데이터 재배포 허용은 서로 다르다. 아래는 확인한 권리 표시의 요약이며 법률 자문이나 제3자 권리까지 포함한 보증이 아니다.

| 후보 | 데이터 권한 | 코드 권한 | 포트폴리오 공개 시 처리 |
|---|---|---|---|
| **ABCD** | 공식 저장소는 “code and data”를 함께 제공하고 루트에 MIT가 있다. 다만 LICENSE 본문은 “software and associated documentation”을 대상으로 하며 **데이터를 명시적으로 지정한 별도 허락은 이번 조사에서 확인 못 함** [A1,A3] | 루트 MIT 확인 [A3] | 데이터도 MIT 적용 대상으로 볼 근거는 있으나 코드와 별도로 확정하지 않는다. 원문·번역 데이터 재배포 전 적용 범위 확인. 코드 복사 시 저작권·허락 고지 유지 |
| **WoS** | KLUE 공개물 CC BY-SA 4.0. 논문 본문도 데이터 파생·재배포·상업적 사용 허용 방침 설명 [K1,K2 §2.1,K3] | 확인한 저장소 전체의 표기는 CC BY-SA 4.0. 별도 소프트웨어 라이선스 및 외부 baseline 코드 권한은 **미확인** [K1,K3] | 원문 사용 시 출처·라이선스·수정 여부 표시. 번역·각색 자료 공개 시 동일조건변경허락 준수. 프로젝트 코드와 데이터 라이선스를 분리하여 표시 |
| **LIGHT** | 확인한 공식 프로젝트·task 문서·외부 데이터 다운로드 정의에 **데이터 전용 라이선스가 명시되지 않음**. 데이터 권한 미확인 [L1,L2,L3] | LIGHT 저장소 MIT; ParlAI 로더도 코드에 MIT 명시 [L3,L4] | 코드의 MIT를 외부 배포 `.pkl` 데이터에 자동 적용하지 않는다. 확인 전 원문·번역 데이터 공개 제외. 특정 CC 라이선스라고도 추정하지 않음 |
| **MultiWOZ** | Cambridge **2.1 데이터** 배포 항목에 CC BY 4.0 확인 [M3]. **2.2 추가·수정 주석의 별도 권한은 미확인**; 시도한 2.2 LICENSE 경로는 404 | 공식 README가 toolkit을 MIT로 명시 [M1]. 개별 추가 코드까지 모두 같은 권한이라고 확장하지 않음 | 2.1은 출처·라이선스·변경 표시를 전제로 재사용 검토 가능. 2.2는 기반 2.1의 CC BY와 루트 코드 MIT만으로 추가 주석까지 확정하지 말고 배포 버전 권한 확인 |

CC BY-SA 원문·각색 데이터의 공개 의무가 학습 가중치나 모든 생성 응답에 어떻게 적용되는지는 이 조사에서 판정하지 않았다. 체크포인트 공개 권한은 기반 모델 라이선스와 함께 별도 검토해야 한다. 원문을 포함한 화면·예시 출력도 공개 범위에 포함해 점검한다. 고객 식별 정보나 실제 연락처 등은 가져오지 않고 가상의 퀘스트 정보만 사용한다.

## 프로젝트용 최소 보완안 — 제안이며 설계 변경 아님

1. **서버 상태와 사용자 발화를 독립 구성:** 목표 미달/달성/초과 및 수령 여부를 조합하고, 동일 발화를 여러 상태에서 평가한다. 발화의 “다 잡았다”, “아직 안 받았다”가 신뢰할 상태를 덮어쓰지 않게 한다.
2. **최종 의도와 행동을 구분:** 지급 요청은 상태에 따라 `grant_reward` / `explain_progress` / `already_claimed`; 진행 문의는 `explain_progress`, 보상 문의는 `explain_reward`, 퀘스트 의도 불명확은 `clarify`, 인사·범위 밖 요청은 `other`. 원 데이터의 이름이 비슷한 라벨을 그대로 옮기지 않는다.
3. **취소 최소대조군을 독립 작성:** 설계의 “보상 줘. 얼마였지?”는 지급 의사 유지, “보상 줘. 아니, 얼마인지만 알려줘.”는 명시적 철회, “보상 받을까 말까…”는 모호함으로 구분한다. 주문 취소 라벨이나 마지막 문장 키워드만으로 대체하지 않는다.
4. **새 정답 경계는 먼저 합의:** 지급 불가 복합 요청의 설명 우선순위 등 설계 미결정 사항을 조사 문서에서 임의로 확정하지 않는다. 행동별 건수·취소 사례를 기록하고, 퀘스트·표현군 단위로 학습/검증/최종 평가를 분리한다. 행동 정확도와 한국어 캐릭터 대사의 품질은 따로 평가한다.

## 실제 본문을 조회한 1차 출처

모두 위 확인일에 조회했다. URL은 공식 저장소·배포기관·원 논문이며, 검색 요약만으로 확정한 출처는 없다. 원문 아카이브나 데이터셋 파일은 저장하지 않았다.

- **[A1] ABCD 공식 README** — Introduction, Data, Scenario, Conversation: https://github.com/asappresearch/abcd
- **[A2] ABCD 공식 ontology** — intents/subflows, actions, values: https://raw.githubusercontent.com/asappresearch/abcd/master/data/ontology.json
- **[A3] ABCD LICENSE**: https://raw.githubusercontent.com/asappresearch/abcd/master/LICENSE
- **[K1] KLUE 공식 README** — Benchmark Datasets, License: https://github.com/KLUE-benchmark/KLUE
- **[K2] KLUE 원 논문 v4** — §2.1, §3.8, 표22–26: https://arxiv.org/html/2105.09680v4
- **[K3] KLUE License.md** — CC BY-SA 4.0 §1, §2, §3: https://raw.githubusercontent.com/KLUE-benchmark/KLUE/main/License.md
- **[L1] LIGHT 공식 프로젝트 페이지** — Abstract, Datasets: https://parl.ai/projects/light/
- **[L2] LIGHT-Dialogue 공식 task README**: https://raw.githubusercontent.com/facebookresearch/ParlAI/main/parlai/tasks/light_dialog/README.md
- **[L3] LIGHT-Dialogue 공식 로더** — 코드 저작권 고지, RESOURCES, 입력 필드: https://raw.githubusercontent.com/facebookresearch/ParlAI/main/parlai/tasks/light_dialog/build.py
- **[L4] LIGHT LICENSE**: https://raw.githubusercontent.com/facebookresearch/LIGHT/main/LICENSE
- **[L5] LIGHT 공식 저장소** — 프로젝트 설명, License: https://github.com/facebookresearch/LIGHT
- **[M1] MultiWOZ 공식 README** — Data structure, FAQ, License: https://github.com/budzianowski/multiwoz
- **[M2] MultiWOZ 2.2 공식 README** — Schema file, Dialogue files, Action annotation: https://raw.githubusercontent.com/budzianowski/multiwoz/master/data/MultiWOZ_2.2/README.md
- **[M3] Cambridge의 MultiWOZ 2.1 데이터 배포 기록** — Files, Software / Usage instructions, Rights and licensing: https://www.repository.cam.ac.uk/items/74e8d468-9442-424a-bb3b-1bb88dcb8673

**조회 실패 / 미검증:** https://raw.githubusercontent.com/budzianowski/multiwoz/master/data/MultiWOZ_2.2/LICENSE — 404. 이 경로의 부재만으로 다른 위치에도 라이선스가 없다고 단정하지 않는다. LIGHT 데이터 권한, ABCD의 데이터 적용 범위, 각 후보의 발화 내 요청 철회 사례 분포는 제한된 조사에서 해결하지 못했다. 이 공백을 남기고 추가 후보 탐색은 종료한다.
