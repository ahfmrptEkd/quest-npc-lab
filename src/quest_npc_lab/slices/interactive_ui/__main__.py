"""Launch the local comparison UI with python -m."""

import argparse

from .inference import ModelSettings
from .interactive_ui import ComparisonApp
from .server import make_server


def main():
    parser = argparse.ArgumentParser(description="Local Quest NPC comparison UI")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Deterministic test responses; no model loading",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--model-id", default=ModelSettings.model_id)
    parser.add_argument("--revision", default=ModelSettings.revision)
    parser.add_argument(
        "--max-new-tokens", type=int, default=ModelSettings.max_new_tokens
    )
    parser.add_argument(
        "--sft-checkpoint",
        default="artifacts/sft_checkpoint",
        help="Local PEFT adapter directory",
    )
    parser.add_argument(
        "--grpo-checkpoint",
        default="artifacts/grpo_checkpoint",
        help="Local SFT+GRPO PEFT adapter directory",
    )
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or args.max_new_tokens < 1:
        parser.error("port must be 0–65535 and max-new-tokens must be positive")
    app = ComparisonApp(
        offline=args.offline,
        settings=ModelSettings(
            args.model_id, args.revision, args.device, args.max_new_tokens
        ),
        sft_checkpoint=args.sft_checkpoint,
        grpo_checkpoint=args.grpo_checkpoint,
    )
    with make_server(app, port=args.port) as server:
        print(
            f"Quest NPC Lab: http://127.0.0.1:{server.server_port} "
            f"({'OFFLINE test double' if args.offline else 'LIVE local inference'})",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
