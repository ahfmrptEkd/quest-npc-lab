"""Run the two cached, original-weight baselines on approved development data."""
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import time
from typing import Any, cast

from . import compare_baselines, format_prompt, load_development_data, load_manifest
from .prompt_evaluation import batched_generator
from quest_npc_lab.slices.guild_receptionist import QuestState


def main():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    config = load_manifest()
    datasets = load_development_data()
    torch.set_num_threads(config['comparison_runtime']['torch_num_threads'])
    set_seed(config['seed'])
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    tokenizer = cast(Any, AutoTokenizer.from_pretrained(
        config['model_name'], revision=config['model_revision'], local_files_only=True,
        padding_side=config['comparison_runtime']['padding_side'],
    ))
    model = cast(Any, AutoModelForCausalLM.from_pretrained(
        config['model_name'], revision=config['model_revision'], local_files_only=True,
        dtype=getattr(torch, config['dtype']),
    )).to(device).eval()
    started = time.monotonic()
    count = 0
    prompts = [
        format_prompt(QuestState(case.quest_name, case.target_count, case.current_count,
                                 case.reward_description, case.reward_claimed),
                      case.player_utterance, baseline=baseline)
        for baseline in ('minimal', 'improved')
        for cases in datasets.values() for case in cases
    ]

    def generate_batch(batch):
        nonlocal count
        inputs = tokenizer.apply_chat_template(
            [[{**message, 'content': message['content'].format(formatted_prompt=prompt)}
              for message in config['chat_template']['messages']] for prompt in batch],
            add_generation_prompt=config['chat_template']['add_generation_prompt'],
            return_tensors='pt', return_dict=True, padding=True,
        ).to(device)
        length = inputs['input_ids'].shape[1]
        if length > config['input_limits']['max_input_tokens']:
            raise ValueError('input token limit exceeded; inputs are never truncated')
        with torch.inference_mode():
            output = model.generate(**inputs, **config['generation'])
        count += len(batch)
        print(f'{count}/480 responses, {time.monotonic() - started:.1f}s', flush=True)
        return tokenizer.batch_decode(output[:, length:], skip_special_tokens=True)

    path = Path(__file__).with_name('artifacts') / 'baseline_comparison_report.json'
    report = compare_baselines(datasets, batched_generator(
        prompts, generate_batch, batch_size=config['comparison_runtime']['batch_size']), path)
    directory = Path(__file__).parent.parent / 'dataset_pipeline' / 'data'
    report['provenance'] = {
        'dataset_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                           for name in ('train_180.jsonl', 'val_60.jsonl')},
        'environment': {name: version(name) for name in ('torch', 'transformers', 'accelerate')},
        'python': platform.python_version(), 'device': device,
        'torch_num_threads': torch.get_num_threads(), 'inference_batch_size': config['comparison_runtime']['batch_size'],
        'gpu': torch.cuda.get_device_name(0) if device == 'cuda' else None,
        'seconds': round(time.monotonic() - started, 2),
        'weights': 'original base model; no adapters or training',
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['summary'], indent=2), flush=True)


if __name__ == '__main__':
    main()
