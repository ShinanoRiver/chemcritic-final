import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_generic_record import ROOT, engine_subject
from app.chemcritic import schema_v2, reaction_profiles
from app.chemcritic.research_request import build_prompt, prompt_attachments
from app.chemcritic.shared_agent import SharedAgent
from app.chemcritic.storage import ReviewStore
from app.chemcritic.rules import review

FULL=json.loads((Path(__file__).with_name('all_fields_fixture.json')).read_text(encoding='utf-8'))

def leaves(node,path=()):
    if isinstance(node,dict):
        for key,value in node.items():yield from leaves(value,path+(key,))
    elif isinstance(node,list):
        for key,value in enumerate(node):yield from leaves(value,path+(key,))
    else:yield path,node

def get(node,path):
    for key in path:node=node[key]
    return node

class AllFieldTests(unittest.TestCase):
    def test_every_leaf_survives_schema_storage_and_prompt(self):
        normalized=schema_v2.normalize(FULL)
        for path,value in leaves(FULL):
            with self.subTest(path=path):self.assertEqual(get(normalized,path),value)
        text=json.dumps({'experiment':normalized},ensure_ascii=False)
        prompt=build_prompt(text,scope=reaction_profiles.scope(normalized))
        self.assertTrue(prompt.endswith(text))
        with tempfile.TemporaryDirectory() as temp:
            store=ReviewStore(Path(temp)/'db');saved=store.save(normalized,'',review(normalized,[]))
            self.assertEqual(store.get(saved['id'])['experiment'],normalized)

    def test_form_sent_to_agent_preserves_all_fields(self):
        ready=threading.Event()
        class OfflineAgent(SharedAgent):
            def _run(self,job_id,data):
                self.captured=data;ready.set()
        agent=OfflineAgent('test-placeholder',client_factory=lambda:None,execution_mode='research')
        job=agent.start('aaaa1111-1111-4111-8111-111111111111',FULL,None)
        self.assertTrue(ready.wait(5))
        data=json.loads(agent.captured)
        self.assertEqual(data['experiment'],schema_v2.normalize(FULL))
        subject=agent._local_contracts[job['id']]['payload']['engine_input']['subject']
        self.assertEqual(subject['assay']['method'],'GC-FID')
        self.assertEqual(subject['assay']['internal_standard'],'TEST-STANDARD')
        self.assertEqual(subject['conditions']['base_eq'],2)
        self.assertEqual(subject['conditions']['ligand'],'TEST-LIGAND')

    def test_all_reaction_role_additive_and_metric_enums_preserved(self):
        for kind in schema_v2.REACTION_TYPES:
            r=copy.deepcopy(FULL);r['reaction']['type']=kind
            self.assertEqual(schema_v2.normalize(r)['reaction']['type'],kind)
        for role in schema_v2.REACTANT_ROLES:
            r=copy.deepcopy(FULL);r['reaction']['reactants'][1]['role']=role
            self.assertEqual(schema_v2.normalize(r)['reaction']['reactants'][1]['role'],role)
        for kind in schema_v2.ADDITIVE_TYPES:
            r=copy.deepcopy(FULL);r['additives'][1]['type']=kind
            self.assertEqual(schema_v2.normalize(r)['additives'][1]['type'],kind)
        for metric in schema_v2.METRICS:
            r=copy.deepcopy(FULL);r['results']['metric']=metric
            self.assertEqual(schema_v2.normalize(r)['results']['metric'],metric)

    def test_no_silent_first_match_or_unsupported_metric(self):
        for variant in ('reactant','base','ligand','basis','lc'):
            r=copy.deepcopy(FULL)
            if variant=='reactant':
                item=copy.deepcopy(r['reaction']['reactants'][0]);item['limiting']=False;r['reaction']['reactants'].append(item)
            if variant=='base':r['additives'].append({'name':'TEST-BASE','type':'base'})
            if variant=='ligand':r['additives'].append({'name':'OTHER-LIGAND','type':'ligand'})
            if variant=='basis':r['reaction']['equivalents_basis']={'reactant_index':1,'label':'phenylboronic acid'}
            if variant=='lc':r['results']['metric']='lc'
            r=schema_v2.normalize(r);scope=reaction_profiles.scope(r)
            with self.subTest(variant=variant):
                self.assertFalse(scope['in_scope']);self.assertIsNone(reaction_profiles.legacy_view(r));self.assertEqual(prompt_attachments(scope),[])

    def test_limits_zero_unknown_and_presence(self):
        r=copy.deepcopy(FULL);r['conditions']['temperature_C']=-10
        r['results']['value_pct']=0;r['results']['repeat_attempts']=None;r['user_goal']=None
        r=schema_v2.normalize(r);self.assertEqual(r['results']['value_pct'],0);self.assertIsNone(r['user_goal'])
        r['reaction']['reactants'][1]['limiting']=True
        with self.assertRaises(schema_v2.ValidationError):schema_v2.normalize(r)
        r=copy.deepcopy(FULL);r['additives']=[];r['additives_listed_complete']=None
        self.assertEqual(schema_v2.presence_state(r,'base'),'unknown')
        r['additives_listed_complete']=True;self.assertEqual(schema_v2.presence_state(r,'base'),'absent')

    def test_ligand_additive_and_cosolvent_survive_projection(self):
        r=copy.deepcopy(FULL);r['catalyst']['ligand']['name']=None
        r['additives'].append({'name':'ADDED-LIGAND','type':'ligand','loading_mol_pct':2})
        r['conditions']['solvent_system']['primary']=None
        view=reaction_profiles.legacy_view(schema_v2.normalize(r))
        self.assertEqual(view['conditions']['ligand'],'ADDED-LIGAND')
        self.assertEqual(view['conditions']['solvent'],'水')
