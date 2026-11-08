"""Build burned-in branding after the portrait crop, before encoding."""
import json
from pathlib import Path


def build_branding(config_dir, portrait_filter, seconds):
    config_dir = Path(config_dir)
    config_file = config_dir / 'branding.json'
    config = json.loads(config_file.read_text(encoding='utf-8-sig')) if config_file.exists() else {}

    def logo_path(value):
        path = Path(value)
        if not path.is_absolute():
            path = config_dir / path
        if not path.is_file():
            raise ValueError(f'Logo nao encontrada: {path}')
        return str(path.resolve())

    vibe = logo_path(config.get('vibe_logo', '../assets/branding/vibe.png'))
    left = config.get('sponsors_left', [])
    right = config.get('sponsors_right', [])
    if not isinstance(left, list) or not isinstance(right, list):
        raise ValueError('sponsors_left e sponsors_right devem ser listas de arquivos')
    # Each slot has its own list. Only logos visible during this replay are loaded.
    slots = [(vibe, '(W-w)/2', None)]
    visible = max(1, (seconds + 9) // 10)
    for logos, x in ((left, '(W/3-w)/2'), (right, '2*W/3+(W/3-w)/2')):
        for index, value in enumerate(logos[:visible]):
            slots.append((logo_path(value), x, (index, len(logos))))

    inputs = []
    filters = [f'[0:v:0]{portrait_filter},setpts=PTS-STARTPTS[base0]']
    for index, (path, x, schedule) in enumerate(slots, 1):
        # Decode/scale each static image once; overlay reuses its final frame.
        inputs.extend(['-i', path])
        filters.append(
            f'[{index}:v]scale=260:120:force_original_aspect_ratio=decrease,'
            f'format=rgba,setsar=1[logo{index}]'
        )
        enable = ''
        if schedule is not None:
            position, count = schedule
            enable = f":enable='eq(mod(floor(t/10),{count}),{position})'"
        filters.append(
            f'[base{index-1}][logo{index}]overlay=x={x}:y=H-180+(120-h)/2:'
            f'eof_action=repeat{enable}[base{index}]'
        )
    return inputs, ';'.join(filters), f'[base{len(slots)}]'
