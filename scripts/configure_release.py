"""Generate ignored backend-owned configs only; no inference, SSH or downloads."""
import argparse
import json
from pathlib import Path
import sys
import yaml

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from backend.services.environment import backend_env_values
from backend.services.scene_dataset import DatasetScenes

def generate(values, scene):
    root=Path(values['WELD_DATASET_ROOT']).expanduser().resolve()
    segment=yaml.safe_load((PROJECT/'configs/segment2.windows.yaml').read_text(encoding='utf-8'))
    rough=yaml.safe_load((PROJECT/'configs/trajectory3.windows.yaml').read_text(encoding='utf-8'))
    for c in (segment,rough):
        c['server']['ssh_alias']=values['WELD_NATIVE_SSH_ALIAS']
        c['server']['remote_root']=values['WELD_NATIVE_REMOTE_ROOT']
        c['yolo']['remote_python']=values['WELD_NATIVE_YOLO_PYTHON']
    segment['retrieval']['remote_python']=values['WELD_NATIVE_REMOTE_PYTHON']
    segment['datasets']=[{'dir':str(root.parent)}]
    segment['mask']['dataset_root']=str(root/'2.데이터(NIA)')
    segment['mask']['output_dir']=str(PROJECT/'.cache/native-models/outputs/segment2')
    rough['server']['remote_python']=values['WELD_NATIVE_REMOTE_PYTHON']
    rough['data']['root']=str(root)
    rough['data']['mask_sessions']=str(PROJECT/'.cache/native-models/approved')
    rough['models']['api_keys_path']=str(PROJECT/'.cache/private/native-api-keys.json')
    rough['action_bundle']['output']=str(PROJECT/'.cache/native-models/action-bundles/trajectory3')
    rough['output']['root']=str(PROJECT/'.cache/native-models/outputs/rough3d_v3')
    return {
        'segment2.windows.yaml':yaml.safe_dump(segment,allow_unicode=True,sort_keys=False),
        'trajectory3.windows.yaml':yaml.safe_dump(rough,allow_unicode=True,sort_keys=False),
        'binding.json':json.dumps(dict(sample_id=scene.sample_id,camera='F',image=str(scene.images['F'])),ensure_ascii=False,indent=2)+'\n',
    }

def save(files, directory):
    directory=Path(directory).resolve()
    if not directory.is_relative_to((PROJECT/'.cache').resolve()):raise ValueError('CONFIG_OUTPUT_NOT_OWNED')
    # Check every existing file before making changes.
    for name,text in files.items():
        p=directory/name
        if p.exists() and p.read_text(encoding='utf-8') != text:
            raise ValueError('CONFIG_EXISTS_AND_DIFFERS: '+name)
    directory.mkdir(parents=True,exist_ok=True)
    for name,text in files.items():
        p=directory/name
        if not p.exists():
            with p.open('x',encoding='utf-8',newline='\n') as f:f.write(text)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-id',required=True)
    args=parser.parse_args()
    values=backend_env_values()
    required=('WELD_DATASET_ROOT','WELD_NATIVE_PYTHON','WELD_NATIVE_SSH_ALIAS',
              'WELD_NATIVE_REMOTE_ROOT','WELD_NATIVE_REMOTE_PYTHON','WELD_NATIVE_YOLO_PYTHON')
    missing=[k for k in required if not values.get(k)]
    if missing:parser.error('Missing root .env variable names: '+', '.join(missing))
    if not Path(values['WELD_NATIVE_PYTHON']).is_file():parser.error('WELD_NATIVE_PYTHON file missing')
    scene=DatasetScenes(values['WELD_DATASET_ROOT']).resolve(args.sample_id)
    save(generate(values,scene),PROJECT/'.cache/native-integration/configs')
    print('CONFIG_READY: owned native configs and exact F binding created; model/SSH/Isaac calls=0')

if __name__=='__main__':main()
