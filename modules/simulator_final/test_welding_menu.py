import curses
import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from welding_menu import (build_catalog, select_rows, preparation_command,
                          server_running, queue_records, Menu, error_label, sample_label, discover_prediction_roots, prediction_family, prediction_export_label)
from welding_command_queue import submit, process_next


class FakeScreen:
    def __init__(self, keys): self.keys = iter(keys)
    def keypad(self, value): pass
    def timeout(self, value): pass
    def getmaxyx(self): return 24, 100
    def erase(self): pass
    def addnstr(self, *args): pass
    def refresh(self): pass
    def get_wch(self): return next(self.keys)


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_catalog_respects_splits_and_missing_predictions(self):
        data = self.root/'data'
        for split, sample in [('Training','T_PP_03_0001'), ('Validation','L_PR_03_0001')]:
            h5 = data/'1.데이터/Other'/f'{sample}.h5'
            h5.parent.mkdir(parents=True, exist_ok=True); h5.touch()
            label = data/'2.데이터(NIA)'/split/f'{sample}.json'
            label.parent.mkdir(parents=True, exist_ok=True); label.write_text('{}')
        exports = self.root/'predictions'
        for sample, split in [('L_PR_03_0001','val'), ('T_PP_03_0001','val')]:
            episode = exports/sample; episode.mkdir(parents=True)
            (episode/'metadata.json').write_text(json.dumps(dict(episode_id=sample, split=split)))
            (episode/'trajectory.npz').touch()
        rows, warnings = build_catalog(data, [exports])
        self.assertEqual([r['sample'] for r in select_rows(rows,'train','gt')], ['T_PP_03_0001'])
        self.assertEqual(select_rows(rows,'train','predict'), [])
        self.assertEqual(len(select_rows(rows,'valid','predict')), 1)
        self.assertEqual(len(warnings), 1)
        row = select_rows(rows,'valid','predict')[0]
        cmd = preparation_command(row, 'predict', 15, self.root/'queue', exports)
        self.assertIn('--prediction',cmd)
        self.assertEqual(cmd[cmd.index('--dataset-split')+1], 'valid')
        with self.assertRaises(ValueError):
            preparation_command(row, 'predict', 15, prediction_root=self.root/'missing')
        self.assertNotIn('--prediction',preparation_command(row,'gt',15))

    def test_h5_without_split_label_is_visible_as_unassigned(self):
        import h5py
        import numpy as np
        data = self.root/'data'
        path = data/'1.데이터/Other/C_RR_03_0001.h5'
        path.parent.mkdir(parents=True)
        with h5py.File(path, 'w') as handle:
            for key in ('trajectory', 'joint_values', 'original_points'):
                handle[key] = np.zeros((2, 6))
        rows, _ = build_catalog(data, [])
        self.assertEqual(select_rows(rows, 'train', 'gt'), [])
        self.assertEqual(select_rows(rows, 'valid', 'gt'), [])
        self.assertEqual(len(select_rows(rows, 'unassigned', 'gt')), 1)
        self.assertTrue(rows[0]['supported'])
        self.assertIsNone(rows[0]['source_issue'])
        command = preparation_command(rows[0], 'gt', 15)
        self.assertEqual(command[command.index('--dataset-split')+1], 'unassigned')
        with h5py.File(path, 'a') as handle:
            handle['joint_values'][0, 0] = np.nan
        rows, _ = build_catalog(data, [])
        self.assertIn('[invalid H5]', sample_label(rows[0], 'gt'))
        self.assertIn('NaN', rows[0]['source_issue'])

    def test_discovers_project_nested_model_exports(self):
        expected = []
        for name in ('welding_validation_best_all', 'RICL/welding_validation_ricl_all',
                     'OpenVLA/experiment/checkpoint_42', 'RICL/train_results'):
            root = self.root/name
            episode = root/'0000_L_PR_03_0001'
            episode.mkdir(parents=True)
            (episode/'metadata.json').write_text('{}')
            (episode/'trajectory.npz').touch()
            expected.append(root.resolve())
        bank = self.root/'RICL/welding_validation_ricl_all/retrieval_bank/example'
        bank.mkdir(parents=True)
        (bank/'metadata.json').write_text('{}')
        (bank/'trajectory.npz').touch()
        accidental = self.root/'RICL/welding_validation_ricl_all/welding_train_ricl_all/0000_T_PP_03_0001'
        accidental.mkdir(parents=True)
        (accidental/'metadata.json').write_text('{}')
        (accidental/'trajectory.npz').touch()
        (self.root/'welding_empty').mkdir()
        self.assertEqual(discover_prediction_roots(self.root), sorted(expected))
        self.assertEqual(prediction_family(self.root/'OpenVLA/experiment/checkpoint_42', self.root), 'OpenVLA')
        self.assertEqual(prediction_family(self.root/'RICL/train_results', self.root), 'RICL')
        self.assertEqual(prediction_export_label(self.root/'RICL/train_results', self.root), 'RICL/train_results')

    def test_refresh_rediscovers_exports_and_preserves_manual_folder(self):
        from unittest.mock import patch
        menu = Menu(FakeScreen([]))
        menu.header = lambda text: None
        menu.manual_prediction_roots = [self.root/'manual']
        first, second = self.root/'first', self.root/'second'
        with patch('welding_menu.discover_prediction_roots', side_effect=[[first], [second]]), \
             patch('welding_menu.build_catalog', return_value=([], [])):
            menu.refresh()
            self.assertEqual(set(menu.prediction_roots), {first, self.root/'manual'})
            menu.refresh()
            self.assertEqual(set(menu.prediction_roots), {second, self.root/'manual'})

    def test_arrow_and_search_navigation(self):
        menu = Menu(FakeScreen([curses.KEY_DOWN, '\n']))
        self.assertEqual(menu.choose('split',['Train','Valid']), 1)
        menu = Menu(FakeScreen(['T','_','P','P','\n']))
        self.assertEqual(menu.choose('sample',['L_PR_03_0001','T_PP_03_0001'],True),1)
        menu = Menu(FakeScreen(['\x1b']))
        self.assertIsNone(menu.choose('back',['a']))

    def test_error_units_and_unknown_values(self):
        self.assertEqual(error_label(dict(source_units='m', metrics=dict(
            ade_source_units=.0137957, fde_source_units=.018074))),
            '(ADE 13.80 mm / FDE 18.07 mm / PRE-END N/A)')
        self.assertEqual(error_label(dict(source_units='mm', metrics=dict(
            ade_source_units=float('nan'), fde_source_units=-1))), '(ADE N/A / FDE N/A / PRE-END N/A)')
        self.assertEqual(error_label({}), '(ADE N/A / FDE N/A / PRE-END N/A)')

    def test_selected_export_error_is_not_taken_from_another_model(self):
        old, best = self.root/'old', self.root/'best'
        row = dict(sample='L_PR_03_0001', split='valid', supported=True, prediction_roots=[old,best],
                   prediction_metrics={old:'(ADE 47.87 mm / FDE 92.74 mm)',
                                       best:'(ADE 3.00 mm / FDE 4.00 mm)'})
        self.assertIn('3.00 mm',sample_label(row,'predict',best))
        self.assertNotIn('47.87',sample_label(row,'predict',best))
        self.assertEqual(sample_label(row,'gt'),row['sample'])
        cmd = preparation_command(row,'predict',15,prediction_root=best)
        self.assertEqual(cmd[cmd.index('--prediction-root')+1],str(best))

    def test_queue_states_keep_mode_and_split_on_failure(self):
        queue = self.root/'queue'
        request_id = submit(queue,self.root/'solution.npz',self.root/'scene.usda',15,
                            'L_PR_03_0001',playback_mode='model_predict',dataset_split='valid')
        self.assertEqual(queue_records(queue)[0]['state'],'queued')
        def fail(request): raise RuntimeError('IK failed')
        self.assertTrue(process_next(queue,fail))
        record = queue_records(queue)[0]
        self.assertEqual(record['id'],request_id)
        self.assertEqual(record['state'],'failed')
        self.assertEqual(record['playback_mode'],'model_predict')
        self.assertEqual(record['dataset_split'],'valid')
        self.assertIn('IK failed',record['error'])

    def test_server_presence_uses_lock_not_stale_file(self):
        queue = self.root/'queue'; queue.mkdir()
        self.assertFalse(server_running(queue))
        with (queue/'server.lock').open('w') as handle:
            self.assertFalse(server_running(queue))
            fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(server_running(queue))
        self.assertFalse(server_running(queue))


if __name__ == '__main__': unittest.main()
