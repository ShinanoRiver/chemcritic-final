import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_generic_record import ROOT, ENGINE, engine_subject
from app.chemcritic import reaction_profiles, schema_v2
from tools.agent_result_bridge import normalize_unknown_sources, execute

FIXTURE=json.loads((Path(__file__).with_name('form_gc037_fixture.json')).read_text(encoding='utf-8'))

class MappingRepairTests(unittest.TestCase):
    def test_local_method_and_known_input_preserved(self):
        record=schema_v2.normalize(FIXTURE['experiment'])
        view=reaction_profiles.legacy_view(record)
        self.assertEqual(view['results']['assay'],'GC-FID')
        subject=engine_subject(record)
        self.assertEqual(subject['assay']['method'],'GC-FID')
        self.assertIsNone(subject['assay']['internal_standard'])
        self.assertEqual(subject['conditions']['equivalents'],{'aryl_halide':1,'boronic_acid':1.2})
        self.assertEqual(record['conditions']['solvent_system']['water_content'],'aqueous')

    def test_exact_failed_input_replay_and_no_duplicate_execution(self):
        original=copy.deepcopy(FIXTURE['engine_subject'])
        normalized,changes=normalize_unknown_sources(original)
        self.assertEqual(original,FIXTURE['engine_subject'])
        self.assertEqual(normalized['conditions'],original['conditions'])
        self.assertEqual(normalized['assay'],original['assay'])
        self.assertEqual(len(changes),2)
        self.assertEqual(normalized['inputs_source']['conditions.equivalents.boronic_acid'],'user_stated')
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);input_path=folder/'input.json'
            input_path.write_text(json.dumps(original),encoding='utf-8')
            context=execute(ENGINE,input_path,folder/'out')
            self.assertEqual(context['input_audit']['status'],'pass')
            self.assertEqual(context['execution_facts']['engine_exit_code'],0)
            self.assertFalse(context['numeric_comparison_authorized_by_observed_fields'])
            self.assertTrue(execute(ENGINE,input_path,folder/'out')['reused_saved_context'])
            original['outcome']['value']=38
            input_path.write_text(json.dumps(original),encoding='utf-8')
            with self.assertRaises(ValueError):execute(ENGINE,input_path,folder/'out')

    def test_ambiguous_and_false_provenance_rejected(self):
        for variant in ('top_level','conflict','unknown','memory'):
            value=copy.deepcopy(FIXTURE['engine_subject'])
            if variant=='top_level':value['equivalents']={'aryl_halide':5}
            if variant=='conflict':value['inputs_source']['conditions.equivalents.aryl_halide']='unknown'
            if variant in ('unknown','memory'):value['inputs_source']['equivalents.aryl_halide']=variant
            with self.subTest(variant=variant),self.assertRaises(ValueError):normalize_unknown_sources(value)

    def test_known_internal_standard_preserved(self):
        value=copy.deepcopy(FIXTURE['experiment'])
        value['results']['internal_standard']='TEST-STANDARD'
        subject=engine_subject(value)
        self.assertEqual(subject['assay']['internal_standard'],'TEST-STANDARD')
