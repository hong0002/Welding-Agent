"""Offline module boundary fixtures: no native processes, HTTP or Simulator."""
from dataclasses import replace
from pathlib import Path
from PIL import Image, ImageDraw
from backend.model_clients.contracts import ModelArtifact, Provenance
from backend.model_clients.guided_workflow import WorkflowGuidedVLAClient
from backend.model_clients.native import CAMERAS, read_json
from backend.model_clients.native_rough3d import NativeRough3DClient
from backend.orchestrator.workflow import Workflow
from backend.services.scene_dataset import DatasetScenes
from backend.services.storage import LocalStorage
from tests.test_guided_vla import create_inputs, response, save


class OfflineGuided:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or response()
        self.health_calls = 0

    def health(self):
        self.health_calls += 1
        return {'status': 'ready', 'waypoints': 9, 'dimensions': 3, 'model': 'offline-guided'}

    def post(self, url, **kwargs):
        self.calls.append(kwargs)
        return self.result


class OfflineViews:
    def segment_views(self, image, *, instruction=''):
        outputs = {}
        for view in ('F', 'R', 'S4'):
            mask = Image.new('L', image.size)
            ImageDraw.Draw(mask).line([(10, 20), (90, 20)], fill=255, width=5)
            mask.info['model_provenance'] = Provenance(model_name='offline-segment', model_version='1',
                latency_ms=0, reference_mode='native', native_session_id='offline-segment', instruction=instruction)
            outputs[view] = mask
        return outputs


class OfflineRough3D:
    def __init__(self, directory):
        self.directory = directory
        self.received_masks = []

    def predict(self, image, mask, instruction, components, *, language=''):
        self.received_masks.append(mask.copy())
        saved = NativeRough3DClient.load_saved(self.directory, image.info['native_binding'].sample_id)
        files = {p.relative_to(self.directory).as_posix(): True for p in self.directory.rglob('*') if p.is_file()}
        artifact = ModelArtifact(kind='rough', provenance=Provenance(model_name='offline-trajectory2',
            model_version='1', latency_ms=0, reference_mode='native', native_session_id=self.directory.name,
            native_artifacts=files))
        return replace(saved, artifact=artifact)


def module_workflow(root):
    settings, _, _, _, rough_dir, binding, _ = create_inputs(Path(root))
    label = Path(read_json(settings.inputs)['dataset_root']) / '2.데이터(NIA)/Training/02.라벨링데이터/TL_Butt/03/SAMPLE_1/SAMPLE_1.json'
    records = []
    for i, view in enumerate(CAMERAS):
        image = Image.new('RGB', (100, 100), (40+i*16, 80, 100))
        path = binding.image.parent / f'SAMPLE_1_{view}_Color.png'
        image.save(path)
        records.append({'filename': path.name, 'rgb_width': 100, 'rgb_height': 100})
    save(label, {'info': {'gid': 'SAMPLE_1'}, 'rgb_images': records})
    transport = OfflineGuided()
    guided = WorkflowGuidedVLAClient(replace(settings, api_token=''), transport=transport)
    workflow = Workflow(LocalStorage(Path(root)/'workflow'), dataset=DatasetScenes(Path(root)/'dataset'),
        segmentation=OfflineViews(), rough3d=OfflineRough3D(rough_dir), guided_vla=guided)
    return workflow, transport
