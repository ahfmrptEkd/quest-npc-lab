"""Gradio entry point. Build the standalone bundle before running this file."""

import base64
import html
import json
import os
from pathlib import Path
import time
from typing import Any, TYPE_CHECKING

import spaces
import gradio as gr

if TYPE_CHECKING:
    from .runtime import interact, load_models
else:
    from runtime import interact, load_models
from quest_npc_lab.slices.interactive_ui.interactive_ui import CONDITIONS
from quest_npc_lab.slices.reaction_media import read_asset


def create_demo():
    config = json.loads(Path(__file__).with_name("deployment.json").read_text())
    pages_url = os.environ.get("PAGES_URL", config["pages_url"])
    models, unavailable = load_models(config, dict(os.environ))

    @spaces.GPU(duration=120)
    def infer(previous, state, utterance, condition):
        return interact(
            models,
            previous,
            state,
            utterance,
            condition,
            checkpoint_metadata=config["checkpoints"],
        )

    def submit(previous, quest, target, current, reward, claimed, utterance, condition):
        started = time.monotonic()
        state = dict(
            quest_name=quest,
            target_count=target,
            current_count=current,
            reward_description=reward,
            reward_claimed=claimed,
        )
        try:
            result = infer(previous, state, utterance, condition)
        except Exception as error:
            raise gr.Error(
                f"추론 실패 · 입력, 대기열 또는 GPU 할당량을 확인하세요. {type(error).__name__}: {error}. 저장 결과: {pages_url}"
            ) from error
        portraits = []
        for item in result["conditions"]:
            media = read_asset(item["reaction"]["image"])
            if media is None:
                continue
            data = base64.b64encode(media[0]).decode()
            portraits.append(
                f'<figure><img width="160" height="180" src="data:image/svg+xml;base64,{data}" alt="{html.escape(item["reaction"]["label"], quote=True)}"><figcaption>{html.escape(item["label"])} · {html.escape(item["status"])}</figcaption></figure>'
            )
        return (
            result,
            result,
            '<div style="display:flex;flex-wrap:wrap">' + "".join(portraits) + "</div>",
            f"실제 추론 완료 · {time.monotonic() - started:.1f}s (대기 포함) · 자유 입력은 미채점 / Unrated",
        )

    with gr.Blocks(title="Quest NPC Lab · Live") as demo:
        gr.Markdown(
            f"# Quest NPC Lab · 실제 자유 입력 추론\n[저장된 실제 결과 240개 (Pages)]({pages_url}) · [재현 문서](https://github.com/ahfmrptEkd/quest-npc-lab#reproduction)\n\nZeroGPU는 방문자별 할당량과 대기열이 있습니다. 할당량 소진·장애 시 Pages를 이용하세요. 이전 대화는 모델에 전달하지 않으며 서버 상태만 유지합니다. 서버 승인은 정답 판정이 아닙니다."
        )
        if unavailable:
            gr.Markdown(
                "**체크포인트 준비 필요:** "
                + "; ".join(f"{k}: {v}" for k, v in unavailable.items())
            )
        session = gr.State(value=None)
        with gr.Row():
            quest = gr.Textbox(label="퀘스트 이름", value="슬라임 토벌", max_length=200)
            target = gr.Number(label="목표 처치 수", value=5, precision=0)
            current = gr.Number(label="현재 처치 수", value=5, precision=0)
            reward = gr.Textbox(label="보상 내용", value="금화 100개", max_length=500)
            claimed = gr.Checkbox(label="이미 수령", value=False)
        utterance = gr.Textbox(
            label="플레이어 자유 입력",
            value="보상이 뭔지 알려주고 바로 지급해줘.",
            max_length=2000,
        )
        condition = gr.Dropdown(
            label="실행 방식",
            choices=[
                ("편집한 같은 상태로 네 조건 비교 / Reset", "compare"),
                *((f"{label} 상태에서 계속", key) for key, label in CONDITIONS),
            ],
            value="compare",
        )
        gr.Markdown(
            "비교는 편집한 상태로 초기화합니다. 계속하기는 선택 조건의 마지막 서버 상태를 사용하며 상태 편집 필드를 무시합니다. 입력 변경 뒤에는 비교를 선택하세요."
        )
        run: Any = gr.Button("실제 추론 실행", variant="primary")
        status = gr.Textbox(label="실행 상태", interactive=False)
        portraits = gr.HTML()
        output = gr.JSON(
            label="네 조건 · 원시 출력 / 모델 행동 / 오류 / 서버 승인 / 최종 상태"
        )
        run.click(
            submit,
            inputs=[
                session,
                quest,
                target,
                current,
                reward,
                claimed,
                utterance,
                condition,
            ],
            outputs=[session, output, portraits, status],
            concurrency_limit=1,
        )
    return demo.queue(max_size=16)


if __name__ == "__main__":
    create_demo().launch()
