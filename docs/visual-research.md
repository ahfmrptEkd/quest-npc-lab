# Quest NPC Lab — 최소 시각 연출 조사

확인일: **2026-09-10**. 기준: [설계](design.md)의 NPC `action`+`dialogue`, 상태 편집, 네 비교군. **이번 주 학습·평가·데모 완성을 우선**하며 시각 모델 학습, 매 턴 영상 생성은 제외한다. 공식 저장소·모델 카드·도구 제공자 문서를 실제 조회한 연구 메모다. 설치·가중치 다운로드·생성·GPU 실측은 하지 않았다. 아래 권고와 테스트 예산은 제안이며 설계 변경이나 구현 승인이 아니다.

> 후속 결정: 아래는 조사 당시의 제안이다. 현재는 MiniMax H3 API로 5초 영상 4개를 사전 제작하는 안을 선택했다. 범위·예산·실행 승인 조건은 [설계](design.md)를 우선한다.

## 결론

**권장: 같은 NPC의 사전 제작 표정 3장(기본·미소·생각) + 작은 CSS 호흡·표정 전환.** 로컬 제작 후보는 **SDXL 1.0 base 단독, FP16, CPU offload**다. 원본 초상화에서 img2img/부분 inpaint로 표정을 바꾸고 얼굴·복장·구도를 검수한다. 동일 seed만으로 동일 인물이 보장되지는 않는다. refiner·LoRA·리깅·TTS·립싱크는 넣지 않는다. [S1,S2; 적용 판단]

- **확실한 폴백:** 권리가 확인된 기본 초상화 1장 + 행동 배지·대사·실제 상태 변화. 표정 일관성 확보가 오래 걸리면 추가 생성 없이 종료한다.
- **조건부 시각 보강:** 기본 데모가 완성되고 별도 90분 예산을 승인하면 **Wan 2.2 TI2V-5B / ComfyUI native offload**로 무음 idle 한 개만 사전 렌더한다. 실패하면 초상화로 돌아간다. 영상은 완료 조건이 아니다. [W1–W3; 적용 판단]
- **이번 범위 제외:** 런타임 LivePortrait/talking head. 장면 전체 생성보다 가볍지만 음성→표정 구동·스트리밍·가중치 권리 확인이라는 별도 작업이 생긴다. [P1–P4]

## 세 방식의 실제 차이

| 방식 | 얻는 효과 | 데모 실행 중 부담 | 주요 실패점 / 판정 |
|---|---|---|---|
| 순수 초상화 1장 | 캐릭터 정체성, 읽기 쉬운 비교 | 이미지 표시만; 생성 모델 상주 불필요 | 가장 안전한 기준선. 정적인 느낌은 남음 |
| **표정 3장 + CSS** | 응답에 반응하는 느낌, 가벼운 호흡 | 브라우저 합성·이미지 전환; 추론 GPU 점유 불필요 | **최소 권장안.** CSS 이동은 실제 얼굴 변형이 아님. 눈깜박임에는 별도 눈감은 그림/레이어가 필요하므로 기본안에서 제외 [B1] |
| 사전 렌더 3–5초 idle | 눈깜박임·머리·머리카락 등 자연스러운 작은 움직임 | 저장된 영상 디코딩만; 생성 서버 불필요 | 인물 변형, 시작/끝 이음새, 표정 이미지로 전환할 때 점프. 루프 생성 자체는 보장되지 않음 |
| 런타임 animated/talking portrait | 새 대사와 동기화된 움직임 가능 | GPU 서비스·전송·동기화, 음성을 쓰면 TTS까지 | 이번 데모에 불필요. LivePortrait 단독은 텍스트→한국어 발화 시스템이 아님 [P1] |

영상의 **재생 길이**와 **생성 wall time**은 다르다. 예를 들어 97프레임/24fps는 약 **4.04초짜리 파일**이지 4초 안에 생성된다는 뜻이 아니다. 아래 어떤 로컬 후보도 이 조사에서 **RTX 3060 실측 또는 네 모델 추론과의 동시 실행**이 검증되지 않았다.

## 후보 5개 — 정확한 변형과 자원 근거

### 1. SDXL 1.0 base + 브라우저 CSS — 채택 권고

- **경로:** `stabilityai/stable-diffusion-xl-base-1.0`, Diffusers `variant=fp16`, FP16, base만 사용, `enable_model_cpu_offload`. 공식 기본 생성 크기는 1024×1024이고 img2img는 768–1024 정사각형 범위를 안내한다. [S1,S2]
- **VRAM/시간:** 공식 카드에 FP16·CPU offload 방법은 있으나 **이 조합의 해상도별 peak VRAM·3060 생성 시간 숫자는 없다.** 따라서 “정확히 N GB” 또는 “12GB에서 보장”이라고 쓰지 않는다. 1장씩 만드는 낮은 위험의 첫 로컬 시험이라는 판단이다.
- **RAM/저장소:** 검토 문서에 이 변형의 최소 host RAM은 없다. 별도 single-file 배포 `sd_xl_base_1.0.safetensors`는 **6.94GB**이며, 이것을 Diffusers FP16 폴더 전체 다운로드량이나 실행 RAM으로 혼동하면 안 된다. 라이브러리·캐시 공간은 별도다. [S3]
- **설치 부담:** Python/PyTorch, Diffusers, Transformers, Accelerate, Safetensors, 문서상 권장 watermark 라이브러리. 새 ComfyUI까지 추가할 필요는 없다. 최종 브라우저에는 생성 도구가 필요 없다. [S1,S2]
- **한계:** 독립 생성 3장은 서로 다른 얼굴이 되기 쉽다. 동일 원본 부분 편집을 우선하고 일관성 실패 시 한 장으로 축소한다. CSS는 `transform`/`opacity` 수준, 움직임 감소 설정과 정지 선택을 제공한다. [B1; 적용 판단]

### 2. Wan 2.2 TI2V-5B / ComfyUI — 사전 idle 1순위

- **저VRAM 경로를 정확히 구분:** Comfy 공식 문서는 **“5B should fit well on 8GB VRAM with native offloading”**이라고 한다. 지정 파일은 **확산 FP16** `wan2.2_ti2v_5B_fp16`, **텍스트 인코더 FP8 e4m3fn scaled** `umt5_xxl_fp8_e4m3fn_scaled`, `wan2.2_vae`다. VAE의 실제 실행 dtype과 offload 분할은 해당 안내에 고정 명시되지 않는다. [W1]
- **해상도/프레임:** 연결된 공식 템플릿은 **1280×704, 121프레임, 24fps, 20 steps, batch 1**. 다만 8GB 문장은 **해상도·카드별 실측 표가 아니라 실행 가능성 안내**다. 템플릿 설정 전체를 3060에서 검증한 수치로 인용할 수 없다. I2V는 기본 비활성인 이미지 입력을 활성화하는 경로다. [W2]
- **원본 경로와 다름:** Wan 원본 카드는 `offload_model`, `convert_model_dtype`, `t5_cpu`를 켠 1280×704 실행 예시에 **24GB 이상**을 명시한다. 같은 카드의 **5초 720P 영상 / 생성 9분 미만**은 소비자 GPU에 대한 주장으로, 위 8GB Comfy 경로나 3060의 시간이 아니다. **Wan 2.1 T2V-1.3B의 8.19GB를 I2V 요구량으로 가져오지도 않는다.** [W3,W6]
- **RAM/저장소:** 파일 페이지 기준 확산 **10GB** + 텍스트 **6.74GB** + VAE **1.41GB** = 약 **18.15GB 가중치**. 런타임·캐시·출력 제외. 검토한 안내에는 해당 offload 경로의 최소 host RAM 수치가 없다. VRAM 절감은 host RAM·전송 시간 문제를 없애지 않는다. [W4]
- **설치 부담:** 최신 호환 ComfyUI와 위 세 파일, 공식 core-node 템플릿. 커스텀 노드·GGUF·추가 가속 LoRA는 첫 시험에 넣지 않는다. 원본 Python 경로의 24GB 요구를 해결하려고 별도 최적화 개발을 시작하지 않는다. [W1]

### 3. LTX-Video 2B 0.9.8 distilled — 가벼운 I2V 대안, 이번 우선순위 2

- **정확한 후보:** `ltxv-2b-0.9.8-distilled.safetensors`. 공식 YAML은 **BF16, 2단계 multi-scale**, 1차 7개/2차 3개 timestep, 공간 upscaler, PixArt 저장소의 텍스트 인코더를 사용한다. “distilled니까 무조건 단일 8 steps”로 축약하면 다른 경로가 된다. [L1,L2]
- **VRAM/시간 함정:** 공식 README에 소개된 **8GB RTX 4060에서 720×480×121을 1분 미만**이라는 사례는 **커뮤니티 LTX-VideoQ8 / Ada GPU 최적화**다. 이 0.9.8 BF16 설정의 측정이 아니며 offload·세부 checkpoint도 그 요약에 없다. 공식 FP8 커널은 **Ada 이상** 대상으로, RTX 3060용 가속 근거가 아니다. H100의 실시간/수초 생성 주장 역시 전용하지 않는다. 이 BF16 경로의 12GB 적합성과 3060 wall time은 미확인이다. [L1]
- **RAM/저장소:** checkpoint **6.34GB**, 해당 공간 upscaler **505MB**, 텍스트 인코더 별도. 선택적 prompt enhancer까지 쓰면 추가 가중치가 필요하다. FP8 파일 **4.46GB**는 저장 크기이며 전체 VRAM 요구량이 아니다. host RAM·완전한 설치 크기는 확인 문서에 없다. [L2,L3]
- **설치 부담:** 공식 테스트 환경 Python 3.10.5 / CUDA 12.2, PyTorch ≥2.1.2. 별도 환경과 inference extras, 또는 권장 Comfy workflow. YAML에는 Florence prompt enhancer와 Llama-3.2-3B까지 지정되어 있어 **자동 prompt enhancement는 제외하는 구성 확인이 필요**하다. 추가 가중치의 권리 검토까지 이번 범위에 들이지 않는다. [L1,L2]
- **판단:** 2B라는 크기는 매력적이나, 이번에는 Wan 쪽이 저VRAM 공식 경로와 필요한 파일 목록이 더 명확하다. LTX 개발의 중심은 LTX-2로 이동했으며, 여기서는 작은 기존 2B 변형만 검토했다. LTX 전체 최신 모델의 품질 순위를 주장하지 않는다. [L1]

### 4. LivePortrait humans — 표정 제어에는 적합, 런타임 통합은 보류

- **기능:** 초상화 + driving 영상/이미지/모션 템플릿으로 표정·포즈를 전달한다. 사전 idle 제작에도 사용할 수 있다. **음성을 영상에 합치는 기능은 audio-driven lip-sync가 아니다.** 새 대사를 말하게 하려면 별도 음성·구동 모델과 연결해야 한다. [P1]
- **정밀도/크기/시간:** 기본 설정은 half precision, 내부 입력 **256×256**, 기본 출력 fps **25**. 공식 속도 스크립트는 **FP16, batch 1, 256×256, RTX 4090 + torch.compile**, warm-up 뒤 모듈별 측정이다. 표의 warping **5.21ms**, generator **7.59ms** 등은 **검출·전송·인코딩을 포함한 완성 서비스 지연이 아니다**. 3060 FPS나 최소 VRAM/host RAM은 검토 자료에서 확인되지 않았다. [P2,P3]
- **저장소/설치:** 공식 표의 핵심 모듈 크기 합은 약 **500MB**지만 검출·landmark·환경을 포함한 전체 크기는 아니다. Python 3.10, PyTorch, ONNX 계열 의존성, FFmpeg, 여러 가중치가 필요하다. 문서는 compile 초기 최적화 약 1분 및 Windows/macOS 미지원도 명시한다. humans만 쓰면 animals용 X-Pose CUDA 빌드는 불필요하다. [P1–P3]
- **큰 차단점:** MIT 코드/자체 가중치와 달리 기본 InsightFace 검출 가중치는 **비상업 연구 전용**. 공식 LICENSE는 상업 이용 시 이를 제거·대체하라고 명시한다. 무료 공개 데모라는 이유만으로 권리가 정리됐다고 판단하지 않는다. 대체 검출기 호환성·권리까지 검증하기 전 공개 자산 제작 기본 경로로 쓰지 않는다. [P4,P5]

### 5. MiniMax H3 — 로컬 대체가 아니라, 별도 승인할 API 탈출구

- **실재 확인:** 공식 API의 정확한 이름은 `MiniMax-H3`. I2V 및 첫/끝 프레임 입력, **4–15초 정수 길이, 768P/2K**, 비동기 작업 제출→상태 조회→파일 수령이다. 4–5초 idle 제작에는 관련 있지만 **생성 지연 SLA는 확인되지 않았다**. `H3-Max`는 다른 모델이다. [H1]
- **비용/부담:** 조회 시 H3 출력은 768P **$0.08/초**, 2K **$0.13/초**. 첫 이미지 1장·출력 5초면 기본 출력료는 각각 **$0.40 / $0.65**이며 추가 Context-IR·재생성·세금 등은 별도다. API key·유료 잔액·이미지 외부 전송 승인이 필요하다. 호출하지 않았다. [H2]
- **로컬과 동일하지 않음:** 현재 공식 HF에는 H3-Base FL2VA/Ref2VA **BF16** 가중치가 있다. **33B transformer + Qwen3-VL-32B encoder**이며 카드 예시는 4-GPU serving이다. 검토한 카드에 3060 12GB 저VRAM 실행 보장은 없다. Context-IR와 Regenerate-2K는 해당 카드 기준 공개 로컬 구성에 포함되지 않아 전체 공식 2K 경로는 API를 섞는다. 오래된 발표문의 “가중치 공개 예정”을 현재 상태로 인용하면 틀린다. [H3]
- **권리:** 공개 가중치의 Community License는 코드·모델을 포괄하며 **한국·미국·EU·영국을 기본 허용 지역에서 제외**, 출력 사용·표시에도 지역 제한을 둔다. 별도 허가 없이 지역 제한을 우회하는 로컬 옵션으로 삼지 않는다. encoder는 Apache-2.0이라고 별도 명시한다. 반면 공식 Q&A는 **API는 전 세계 제공, 공개 가중치와 다른 접근**이라고 설명한다. [H4,H5]
- **API 출력 공개:** 서비스 약관은 법이 허용하는 범위에서 입력·생성 콘텐츠 소유권 유지, 제공자 개선 목적 사용 가능성, 합성 표시 및 제3자 권리 준수 의무를 명시한다. 무조건적인 저작권 보증이나 비공개 처리를 약속하는 조건은 아니다. 기본 폴백은 유료 API가 아니라 초상화다. [H6]

## 코드·모델·출력 라이선스 구분

법률 자문이나 원 학습 데이터의 권리 보증이 아니다. **자산 PNG/영상만 공개하는 것과 도구·가중치를 재배포하는 것은 별개**다.

| 경로 | 코드 | 가중치·의존 가중치 | 생성 자산 공개 판단 |
|---|---|---|---|
| SDXL + CSS | 선택 런타임 Diffusers **Apache-2.0**; 브라우저 native 사용에 추가 라이브러리 없음 [C1,B1] | SDXL **CreativeML Open RAIL++-M**. 포함된 두 encoder를 구분: OpenAI CLIP 저장소 MIT, OpenCLIP bigG 모델 카드 MIT. OpenAI HF 카드 자체에는 별도 가중치 라이선스 표기가 없어, 그것만으로 MIT라고 단정하지 않음 [S1,S4,S5] | SDXL 라이선스 §III 출력 조항은 제공자 권리 주장 없음, 제한 준수·출력 책임은 사용자. 카드의 연구용 의도도 보존. 허구 NPC를 검수하여 사전 자산으로 공개하는 경로 권고 [S4] |
| Wan / Comfy | ComfyUI **GPL-3.0** [C2] | Wan 모델/VAE **Apache-2.0**, UMT5 원 모델 **Apache-2.0**; 선택 양자화 파일은 Comfy 공식 배포본 [W1,W3,W5] | Wan 카드는 출력에 권리를 주장하지 않는다고 명시. 일반 생성 영상이 도구를 사용했다는 이유만으로 GPL이 되는 것은 아님; 도구를 묶어 배포하면 별도 의무 [W3,C2 §2] |
| LTX 0.9.8 | 공식 코드 **Apache-2.0** [L1] | **LTXV Open Weights License 0.X**: v0.9.6 이후 적용, 연매출 $10M 이상 기업 상업 이용은 별도 유료 허가. 선택 텍스트 encoder 배포처 PixArt 카드는 Open RAIL++ 및 T5 출처를 명시; T5 원 배포의 별도 권리 텍스트는 이번 조회에서 확보 못 함. enhancer 가중치는 미채택 [L2,L4,L5] | 출력 권리 주장 없음이나 **AI 생성이라는 명시적·이해 가능한 표시 의무**(Attachment A(e)). 예전 0.9.5 OpenRAIL-M이나 코드 Apache를 0.9.8 가중치에 적용하면 안 됨. 의존 가중치 확인 후 채택 [L4] |
| LivePortrait | MIT [P4] | 자체 HF 카드 MIT, **InsightFace 가중치는 비상업 연구 전용** [P4,P5] | 자체 모델 허가가 검출 가중치·driving 영상의 권리를 덮지 않음. 사전 렌더라도 이 검토를 건너뛸 수 없어 기본 경로 제외 |
| H3 | 공개 배포는 Community License, API는 서비스 약관 [H4,H6] | 지역·상업·용도 제한; Qwen encoder 별도 Apache-2.0 [H4] | 로컬 출력도 지역 제한 대상. API는 다른 서비스 조건과 합성 표시 의무를 확인해 별도 승인 [H4–H6] |

공통: 실제 인물·기존 캐릭터·무단 driving 영상을 쓰지 않는다. 공개 자산에 모델 ID/버전·제작 방식·AI 생성 표시를 남기고, 필요한 원문 라이선스·고지는 도구/가중치 재배포 여부에 맞춰 보존한다. 모든 전이 의존성의 전체 법적 실사를 완료했다는 뜻은 아니다.

## 기존 실험을 흐리지 않는 최소 연결 — 제안

1. 네 비교군에 **같은 그림·같은 표정 매핑·같은 전환 시간**을 적용한다. 표정은 모델 행동을 표현하는 UI 연출이지 학습된 감정이나 정답 증거가 아니다.
2. 원래 `action`과 규칙 엔진의 최종 처리를 계속 분리한다. **보상 지급 효과는 실제 승인 뒤에만** 보여준다. 잘못된 JSON은 기본 표정 + 원시 응답/실패 사유로 남기며 연출 때문에 보정·재시도하지 않는다.
3. 상태 컨트롤·대사·행동·정답 표시가 주인공이다. idle은 선택된 상세 패널 하나만 재생하고 네 칸 동시 움직임은 피한다. 저장된 결과를 쓰면 라이브 추론처럼 표현하지 않는다.
4. 반복 영상은 무음·정지 기능·초상화 poster를 준비한다. `prefers-reduced-motion`이면 CSS는 정지하고 영상도 재생하지 않는 별도 처리를 한다. CSS 설정만으로 video가 자동 정지되지는 않는다. [B1; 적용 판단]

## 승인 후에만 실행할 제한된 스모크 테스트

**A. 기본안: 총 60분, 최대 6회 이미지 생성/편집.** 권리 확인된 원본이 있으면 재사용. 아니면 SDXL base FP16 + CPU offload, 1024×1024, batch 1, refiner 없이 기준 1장과 표정 2장을 만든다. 버전·seed·steps·peak VRAM·peak host RAM·로딩 시간·장당 wall time·파일 크기를 기록한다. 환경 준비도 60분에 포함하고 초과하면 기존/별도 확보한 사용 허가 초상화로 종료한다. **합격:** 세 그림의 얼굴·복장·구도가 일치하고 표정이 구분되며, 4개 비교 카드의 출력/실패 표시가 가려지지 않는다. 미달이면 한 장 + 배지로 축소한다.

**B. 선택 보강: 별도 승인, 총 90분, Wan 한 경로만 최대 2회.**

- 먼저 설치·다운로드 허용 여부와 host RAM/디스크를 확인한다. 가중치만 약 18.15GB이며 **12GB GPU만 확인하고 시작하지 않는다**. 환경·캐시·로딩 임시 메모리까지 감당할 예산이 없으면 생략한다. 문서에 없는 최소 RAM을 임의의 공식 요구사항으로 만들지 않는다.
- 환경 준비/다운로드 최대 **30분**. 별도 환경, 공식 core template, 확산 FP16 + FP8 UMT5 + native offload. LLM 학습·추론과 동시에 실행하지 않는다.
- 자체 초상화 1장, 정면·고정 카메라·입 다문 작은 호흡, **512×512, 97프레임, 24fps, 20 steps, batch 1**로 최대 2회, 회당 **20분 wall-time 상한**. 이는 약 4.04초 파일을 위한 **축소 시험 제안**이지 공식 8GB 벤치마크 설정이 아니다. OOM이면 반복 튜닝하지 않고 중단한다.
- 나머지 **20분**에 얼굴/눈/손 왜곡·카메라 이동·이음새를 검수하고 10회 반복 재생한다. 짧은 끝부분 crossfade까지 허용하되 눈깜박임 역재생을 기본 루프 해결책으로 쓰지 않는다.
- **합격:** 초상화보다 명확히 생동감 있고, 눈에 띄는 인물 변형/루프 점프가 없으며, 정지·fallback·표정 전환이 정상이다. 실패하거나 정해진 학습 일정에 영향을 주면 영상 없이 완료한다. 추가 모델 탐색·API 호출은 자동 폴백이 아니다.

## 조회한 1차 출처

링크는 실제 본문/파일 메타데이터 조회에 사용했다. `main` 문서는 변할 수 있으므로 구현 때 선택 revision을 고정한다. 숫자는 해당 문서의 주장 또는 표시값이며 로컬 측정치가 아니다.

- **B1** Mozilla MDN: [prefers-reduced-motion 및 CSS transform/opacity 예제](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion).
- **S1** Stability AI: [SDXL 1.0 base 모델 카드 — standalone, FP16, CPU offload, encoders](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0).
- **S2** Hugging Face: [SDXL 가이드 — 해상도, img2img/inpaint, optimizations](https://huggingface.co/docs/diffusers/main/en/using-diffusers/sdxl).
- **S3** Stability AI: [single-file 크기 6.94GB](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/sd_xl_base_1.0.safetensors) — 메타데이터만 조회.
- **S4** Stability AI: [SDXL LICENSE, §III / Attachment A](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/raw/main/LICENSE.md).
- **S5** [OpenAI CLIP LICENSE](https://raw.githubusercontent.com/openai/CLIP/main/LICENSE), [OpenAI ViT-L/14 카드](https://huggingface.co/openai/clip-vit-large-patch14/raw/main/README.md), [LAION OpenCLIP bigG 카드](https://huggingface.co/laion/CLIP-ViT-bigG-14-laion2B-39B-b160k/raw/main/README.md).
- **W1** Comfy: [Wan 2.2 — 5B 8GB native offload 안내, 지정 파일](https://docs.comfy.org/tutorials/video/wan/wan2_2).
- **W2** Comfy: [공식 5B 템플릿 — node 55/57/3의 크기·fps·steps](https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/video_wan2_2_5B_ti2v.json).
- **W3** Wan-AI: [TI2V-5B 카드 — 원본 24GB 실행, 5초/9분, 출력 권리](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B).
- **W4** Comfy HF 파일 크기: [확산 10GB](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/blob/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors), [VAE 1.41GB](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/blob/main/split_files/vae/wan2.2_vae.safetensors), [UMT5 6.74GB](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/blob/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors) — 메타데이터만 조회.
- **W5** Google: [UMT5-XXL 모델 카드 / Apache-2.0](https://huggingface.co/google/umt5-xxl/raw/main/README.md).
- **W6** Hugging Face: [Wan 파이프라인 — 2.1 1.3B 설명과 T2V/I2V 구분](https://huggingface.co/docs/diffusers/en/api/pipelines/wan).
- **L1** Lightricks: [공식 LTX-Video README — Models, Installation, FP8 Kernels, Community LTX-VideoQ8](https://github.com/Lightricks/LTX-Video).
- **L2** Lightricks: [2B 0.9.8 distilled 공식 YAML](https://raw.githubusercontent.com/Lightricks/LTX-Video/main/configs/ltxv-2b-0.9.8-distilled.yaml).
- **L3** Lightricks: [HF 파일 목록과 크기](https://huggingface.co/Lightricks/LTX-Video/tree/main) — 목록만 조회.
- **L4** Lightricks: [Open Weights License 0.X — 적용 버전, §2, §5, Attachment A(e)](https://huggingface.co/Lightricks/LTX-Video/raw/main/LTX-Video-Open-Weights-License-0.X.txt).
- **L5** PixArt: [선택 text encoder 배포 저장소 카드](https://huggingface.co/PixArt-alpha/PixArt-XL-2-1024-MS/raw/main/README.md). 카드가 연결한 DeepFloyd T5의 README 조회는 `Entry not found`; 별도 원문 권리 확인은 유보.
- **P1** LivePortrait: [공식 README — humans 설치, 구동 방식, compile, 의존성](https://github.com/KlingAIResearch/LivePortrait) — 구 KwaiVGI URL에서 이동.
- **P2** LivePortrait: [공식 속도 표](https://raw.githubusercontent.com/KlingAIResearch/LivePortrait/main/assets/docs/speed.md), [실제 FP16/256px 측정 스크립트](https://raw.githubusercontent.com/KlingAIResearch/LivePortrait/main/speed.py).
- **P3** LivePortrait: [기본 inference config](https://raw.githubusercontent.com/KlingAIResearch/LivePortrait/main/src/config/inference_config.py).
- **P4** LivePortrait: [MIT + InsightFace 가중치 예외 LICENSE](https://raw.githubusercontent.com/KlingAIResearch/LivePortrait/main/LICENSE).
- **P5** LivePortrait: [자체 가중치 HF 카드의 MIT 표기](https://huggingface.co/KlingTeam/LivePortrait/raw/main/README.md). 설치 설명은 더 최신인 GitHub README를 우선했다.
- **H1** MiniMax: [공식 video API 가이드 — H3/H3-Max 규격, 비동기 처리](https://platform.minimax.io/docs/guides/video-generation).
- **H2** MiniMax: [Pay-as-you-go 가격 — Video](https://platform.minimax.io/docs/guides/pricing-paygo#video).
- **H3** MiniMax: [현재 H3 모델 카드 — 구성·BF16·로컬/API 범위](https://huggingface.co/MiniMaxAI/MiniMax-H3); [초기 발표](https://www.minimax.io/blog/minimax-h3)는 공개 예정이라는 과거 설명으로만 대조.
- **H4** MiniMax: [H3 Community License — 2026-08-02, §I/IV/V/VI 및 encoder 예외](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/LICENSE).
- **H5** MiniMax: [License Q&A — API와 공개 가중치의 지역 조건 차이](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/docs/QA-about-License.md).
- **H6** MiniMax: [API 서비스 약관 — 2026-03-30, User Rights / Intellectual Property](https://platform.minimax.io/protocol/terms-of-service).
- **C1** Hugging Face: [Diffusers Apache-2.0 LICENSE](https://raw.githubusercontent.com/huggingface/diffusers/main/LICENSE).
- **C2** Comfy: [ComfyUI GPL-3.0 LICENSE — §2 출력, 재배포 조건](https://raw.githubusercontent.com/Comfy-Org/ComfyUI/master/LICENSE).
