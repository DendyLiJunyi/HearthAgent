"""Create a conservative adaptation candidate without overwriting either checkpoint."""
import argparse
import json
import shutil
from pathlib import Path


def blend(base, adapted, output, alpha):
    import torch
    from safetensors.torch import load_file, save_file
    if not 0 < alpha < 1 or output.exists():
        raise ValueError('alpha must be in (0, 1) and output must be new')
    config = json.loads((base / 'rl_agent_config.json').read_text(encoding='utf-8'))
    other = json.loads((adapted / 'rl_agent_config.json').read_text(encoding='utf-8'))
    for key in ('encoder', 'head_layers', 'max_prefixes'):
        if config.get(key) != other.get(key):
            raise ValueError(f'incompatible checkpoint config: {key}')
    weights = load_file(str(base / 'model.safetensors'))
    updates = load_file(str(adapted / 'model.safetensors'))
    if weights.keys() != updates.keys():
        raise ValueError('incompatible checkpoint tensors')
    for key, tensor in weights.items():
        update = updates[key]
        if tensor.shape != update.shape or tensor.dtype != update.dtype:
            raise ValueError(f'incompatible tensor: {key}')
        if tensor.is_floating_point():
            weights[key] = (tensor.float() * (1 - alpha) + update.float() * alpha).to(tensor.dtype).contiguous()
        elif not torch.equal(tensor, update):
            raise ValueError(f'non-floating buffer changed: {key}')
    output.mkdir(parents=True)
    for folder in ('encoder', 'tokenizer'):
        shutil.copytree(base / folder, output / folder)
    shutil.copyfile(base / 'questions.json', output / 'questions.json')
    provenance = {'base': str(base.resolve()), 'adapted': str(adapted.resolve()), 'alpha': alpha,
                  'calibration': 'Retains base temperature and tokenizer. Not recalibrated or deployed by this command.'}
    config['adaptation_blend'] = provenance
    (output / 'rl_agent_config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    (output / 'blend_report.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    save_file(weights, str(output / 'model.safetensors'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--adapted', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--alpha', type=float, default=0.25)
    args = p.parse_args()
    blend(args.base, args.adapted, args.output, args.alpha)
    print('Blended candidate saved; evaluate before deployment.', flush=True)


if __name__ == '__main__':
    main()
