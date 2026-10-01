"""Bounded exact dataset identity lookup, never similarity search or model I/O."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import re
from dotenv import dotenv_values
from PIL import Image
from backend.model_clients.config import ROOT
from backend.model_clients.native import CAMERAS,NativeBinding,read_json
from backend.model_clients.guided_vla import resolve_split,GuidedVLAError
from backend.orchestrator.state_machine import WorkflowError


@dataclass(frozen=True)
class ResolvedScene:
    sample_id: str
    split: str
    images: dict[str,Path]
    label: Path


class DatasetScenes:
    def __init__(self, root): self.root=Path(root).resolve() if root else None

    @classmethod
    def configured(cls):
        values=dotenv_values(ROOT/'.env',interpolate=False)
        root=os.getenv('WELD_DATASET_ROOT',values.get('WELD_DATASET_ROOT') or '')
        if not root:
            try:root=read_json(ROOT/'.cache/native-models/guided-vla-inputs.json')['dataset_root']
            except (OSError,ValueError,KeyError):pass
        return cls(root)

    def resolve(self,sample_id):
        if not re.fullmatch(r'[A-Za-z0-9_]{1,128}',sample_id):
            raise WorkflowError('Sample ID 형식이 올바르지 않습니다.')
        if self.root is None:raise WorkflowError('Backend dataset root 설정이 필요합니다.',503)
        nia=self.root/'2.데이터(NIA)';matches=[]
        parts=sample_id.split('_');thickness=parts[2] if len(parts)>=4 else ''
        try:
            # At most two split/category/thickness directory levels; no rglob,
            # sample-directory walk, full dataset scan or basename fallback.
            for split in ('Training','Validation'):
                source=nia/split/'01.원천데이터'
                if not source.is_dir():continue
                for category in sorted(source.iterdir()):
                    if not category.is_dir() or not category.name.startswith(('TS_','VS_')):continue
                    for size in category.glob(thickness+'*'):
                        directory=size/sample_id
                        if size.is_dir() and directory.is_dir():matches.append(directory)
            if len(matches)!=1:raise WorkflowError('Dataset sample이 없거나 split identity가 중복됩니다.',409)
            directory=matches[0].resolve()
            if not directory.is_relative_to(nia.resolve()):raise WorkflowError('Dataset binding이 올바르지 않습니다.',409)
            images={view:directory/f'{sample_id}_{view}_Color.png' for view in CAMERAS}
            if any(not p.is_file() or not p.resolve().is_relative_to(directory) for p in images.values()):
                raise WorkflowError('Canonical 9-view 이미지가 모두 필요합니다.',409)
            binding=NativeBinding(sample_id=sample_id,camera='F',image=images['F'])
            proof=resolve_split(self.root,binding);label=Path(proof['label']);data=read_json(label)
            for view,path in images.items():
                records=[r for r in data['rgb_images'] if r['filename']==path.name]
                with Image.open(path) as image:
                    if len(records)!=1 or image.size!=(records[0]['rgb_width'],records[0]['rgb_height']):
                        raise WorkflowError('View와 dataset label이 일치하지 않습니다.',409)
            return ResolvedScene(sample_id,proof['split'],images,label)
        except (OSError,ValueError,KeyError,GuidedVLAError):
            raise WorkflowError('Dataset identity/label을 확인할 수 없습니다.',409) from None

    def from_upload(self,data,filename):
        match=re.fullmatch(r'([A-Za-z0-9_]{1,128})_(B|F|L|R|S1|S2|S3|S4|T)_Color\.png',filename or '')
        if not match:return None
        result=self.resolve(match[1]);source=result.images[match[2]]
        if hashlib.sha256(data).digest()!=hashlib.sha256(source.read_bytes()).digest():
            raise WorkflowError('파일 이름은 dataset view이지만 image hash가 다릅니다. 원본 이미지를 사용하세요.',409)
        return result
