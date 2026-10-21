import copy
import datetime
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonpatch
import yaml

ROOT=Path(__file__).resolve().parents[5]
MATRIX=ROOT/'deployments/homelab/cluster/apps/matrix'
spec=importlib.util.spec_from_file_location('matrix_restore_controller',ROOT/'components/homelab/services/matrix/restore_controller.py')
controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)

class RestoreContractTests(unittest.TestCase):
    def test_inert_verifiers_preserve_all_filesystem_helper_mounts(self):
        docs=list(yaml.safe_load_all((MATRIX/'restore.yaml').read_text()))
        rules=yaml.safe_load(docs[0]['data']['resource-modifiers.yaml'])['resourceModifierRules']
        workloads=[x for x in yaml.safe_load_all((MATRIX/'workloads.yaml').read_text()) if x and x['kind']=='StatefulSet' and x['metadata']['name'] in ['matrix-dumps','matrix-synapse','matrix-relay']]
        self.assertEqual(len(workloads),3)
        for workload in workloads:
            name=workload['metadata']['name']+'-0'
            with self.subTest(pod=name):
                pod={'metadata':copy.deepcopy(workload['spec']['template']['metadata']),'spec':copy.deepcopy(workload['spec']['template']['spec'])}
                exclusions=set(pod['metadata'].get('annotations',{}).get('backup.velero.io/backup-volumes-excludes','').split(','))
                selected=[v['name'] for v in pod['spec']['volumes'] if v['name'] not in exclusions and not set(v).intersection({'secret','configMap','projected','hostPath','downwardAPI'})]
                self.assertIn('tmp',selected)
                helper={'name':'restore-wait','image':'velero/velero:v1.18.2','args':['restore-helper'],'env':[{'name':'POD_UID','value':'disposable-test-uid'}],'volumeMounts':[{'name':v,'mountPath':'/restores/'+v} for v in selected]}
                pod['spec']['initContainers']=[copy.deepcopy(helper)]+pod['spec'].get('initContainers',[])
                rule=next(x for x in rules if x['conditions'].get('resourceNameRegex')=='^'+name+'$')
                patches=[]
                for item in rule['patches']:
                    operation={'op':item['operation'],'path':item['path']}
                    if 'from' in item:operation['from']=item['from']
                    if 'value' in item:
                        value=item['value']
                        operation['value']=json.loads(value) if isinstance(value,str) and value.startswith(('{','[','"')) else value
                    patches.append(operation)
                restored=jsonpatch.apply_patch(pod,patches)
                volumes={x['name'] for x in restored['spec']['volumes']}
                for c in restored['spec']['initContainers']+restored['spec']['containers']:
                    self.assertTrue({x['name'] for x in c.get('volumeMounts',[])}<=volumes)
                actual=copy.deepcopy(restored['spec']['initContainers'][0]);actual.pop('securityContext',None)
                self.assertEqual(actual,helper)
                self.assertEqual([c['command'] for c in restored['spec']['containers']],[['sleep','infinity']])
                self.assertFalse(restored['spec']['automountServiceAccountToken'])
                self.assertFalse(restored['spec'].get('hostNetwork',False))
                self.assertEqual(restored['spec']['initContainers'][0]['securityContext']['runAsUser'],1000)

    def test_filesystem_restore_requests_both_volume_types_and_new_bindings(self):
        captured=[]
        class CapturedRestore(Exception):pass
        def apply(document):
            if document['kind']=='Restore':captured.append(document);raise CapturedRestore()
        def get(namespace,kind,name=None):
            if kind=='backups.velero.io':return {'items':[{'metadata':{'name':'today','labels':{'velero.io/schedule-name':'services-daily'}},'spec':{'includedNamespaces':['matrix']},'status':{'phase':'Completed','completionTimestamp':datetime.datetime.now(datetime.timezone.utc).isoformat()}}]}
            if kind=='secret':return {'apiVersion':'v1','kind':'Secret','metadata':{'name':'matrix-registry'},'data':{}}
            raise AssertionError('Unexpected input')
        with patch.object(controller,'get',side_effect=get),patch.object(controller,'apply',side_effect=apply),patch.object(controller,'run',return_value=b''),patch.object(Path,'read_text',return_value='pass'):
            with self.assertRaises(CapturedRestore):controller.main()
        restore=captured[0]['spec']
        self.assertEqual(set(restore['includedResources']),{'pods','persistentvolumeclaims','persistentvolumes'})
        self.assertTrue(restore['restorePVs'])
        self.assertFalse(restore['includeClusterResources'])
        self.assertEqual(restore['namespaceMapping'],{'matrix':'matrix-restore'})

if __name__=='__main__':unittest.main()
