"""Operator config preparation only. Never launches models or modifies siblings."""
from pathlib import Path
import yaml
from backend.model_clients.config import ROOT


DATASET = Path('D:/용접로봇데이터/42.용접로봇 행동 생성 데이터/3.개방데이터')


def prepare():
    configs = ROOT/'.cache/native-integration/configs'
    configs.mkdir(parents=True, exist_ok=True)
    baseline = yaml.safe_load((configs/'segment.windows.yaml').read_text(encoding='utf-8'))
    segment = yaml.safe_load((ROOT.parent/'vlm_segment2/config/config.yaml').read_text(encoding='utf-8'))
    rough = yaml.safe_load((ROOT.parent/'vlm_trajectory3/config/config.yaml').read_text(encoding='utf-8'))
    segment['server']['ssh_alias'] = baseline['server']['ssh_alias']
    rough['server']['ssh_alias'] = baseline['server']['ssh_alias']
    segment['mask']['dataset_root'] = str(DATASET/'2.데이터(NIA)')
    segment['mask']['output_dir'] = str(ROOT/'.cache/native-models/outputs/segment2')
    rough['data']['root'] = str(DATASET)
    rough['data']['mask_sessions'] = str(ROOT/'.cache/native-models/approved')
    rough['output']['root'] = str(ROOT/'.cache/native-models/outputs/rough3d_v3')
    rough['action_bundle']['output'] = str(ROOT/'.cache/native-models/action-bundles/trajectory3')
    rough['models']['api_keys_path'] = str(ROOT.parent/'vlm_segment2/api/keys.json')
    for name, value in (('segment2.windows.yaml',segment),('trajectory3.windows.yaml',rough)):
        path = configs/name
        text = yaml.safe_dump(value,allow_unicode=True,sort_keys=False)
        if path.exists():
            if path.read_text(encoding='utf-8') != text:
                raise ValueError('Existing candidate config differs; preserve it for review')
        else:
            with path.open('x',encoding='utf-8') as stream:
                stream.write(text)
    return configs


if __name__ == '__main__':
    print(prepare())
