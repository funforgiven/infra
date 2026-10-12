#!/usr/bin/env python3
"""Fetch only public pinned upstream sources; decrypted Helm values stay in memory."""
from pathlib import Path
import argparse, concurrent.futures, gzip, hashlib, io, json, os, re, subprocess, sys, tarfile
import requests, yaml
from helm_values_schema import derived_chart
yaml.SafeLoader.add_constructor('tag:yaml.org,2002:value', lambda loader, node: loader.construct_scalar(node))


def main():
    parser = argparse.ArgumentParser(description="Refresh pinned schemas and a local Helm chart cache; no cluster calls.")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--kustomize", default="kustomize")
    parser.add_argument("--helm", default="helm")
    args = parser.parse_args()
    root=args.repository_root.resolve()
    cache=args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    kustomize=args.kustomize
    helm=args.helm
    sys.path.insert(0,str(root/'components/homelab/operations'))
    from encrypted_inputs import decrypt, values

    def fetch(url):
        digest=hashlib.sha256(url.encode()).hexdigest()
        target=cache/(digest+'.download')
        if not target.exists():
            response=requests.get(url,timeout=120);response.raise_for_status()
            target.write_bytes(response.content)
        return target.read_bytes()

    def unpack(payload,target):
        if not target.exists():
            target.mkdir()
            with tarfile.open(fileobj=io.BytesIO(payload)) as archive: archive.extractall(target,filter='data')
        return next(p for p in target.iterdir() if p.is_dir())

    def oci(source):
        location=source['spec']['url'].removeprefix('oci://')
        registry,repository=location.split('/',1)
        if registry=='docker.io': registry='registry-1.docker.io'
        digest=source['spec']['ref']['digest']
        session=requests.Session()
        def get(path):
            response=session.get('https://'+registry+'/v2/'+repository+'/'+path,headers={'Accept':'application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'},timeout=120)
            if response.status_code==401:
                params=dict(re.findall(r'(\w+)="([^"]+)"',response.headers['WWW-Authenticate']))
                token=requests.get(params.pop('realm'),params=params,timeout=60);token.raise_for_status()
                session.headers['Authorization']='Bearer '+token.json()['token']
                response=session.get(response.url,headers={'Accept':'application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'},timeout=120)
            response.raise_for_status();return response.content
        manifest_path=cache/(digest.removeprefix('sha256:')+'.manifest.json')
        if manifest_path.exists(): manifest_bytes=manifest_path.read_bytes()
        else: manifest_bytes=get('manifests/'+digest);manifest_path.write_bytes(manifest_bytes)
        assert 'sha256:'+hashlib.sha256(manifest_bytes).hexdigest()==digest
        manifest=json.loads(manifest_bytes)
        layer=next(l for l in manifest['layers'] if l['mediaType']=='application/vnd.cncf.helm.chart.content.v1.tar+gzip')
        layer_path=cache/(layer['digest'].removeprefix('sha256:')+'.tgz')
        if layer_path.exists(): payload=layer_path.read_bytes()
        else: payload=get('blobs/'+layer['digest']);layer_path.write_bytes(payload)
        assert 'sha256:'+hashlib.sha256(payload).hexdigest()==layer['digest']
        return unpack(payload,cache/(layer['digest'].removeprefix('sha256:')+'.chart')), {'url':source['spec']['url'],'ref':digest,'archiveSHA256':hashlib.sha256(payload).hexdigest()}

    vendors = json.loads((root/'deployments/homelab/validation/vendors.json').read_text())
    for entry in vendors['files']:
        if hashlib.sha256((root/entry['file']).read_bytes()).hexdigest() != entry['localSHA256']:
            raise ValueError('vendored manifest checksum mismatch: ' + entry['file'])

    native=[]
    entrypoints=[]
    for path in sorted((root/'deployments/homelab').rglob('kustomization.yaml')):
        if 'routeros' in path.parts: continue
        result=subprocess.run([kustomize,'build','--load-restrictor','LoadRestrictionsNone',str(path.parent)],capture_output=True,check=True)
        documents=[d for d in yaml.safe_load_all(result.stdout) if d]
        entrypoints.append({'path':str(path.parent.relative_to(root)),'resources':len(documents)})
        native.extend(documents)
    objects={(d['kind'],d['metadata'].get('namespace',''),d['metadata']['name']):d for d in native}
    releases=[d for d in objects.values() if d['kind']=='HelmRelease']
    decrypted={}
    for path in (root/'deployments/homelab/cluster').rglob('*.sops.yaml'):
        for d in decrypt(path):
            if d.get('kind') in ['Secret','ConfigMap']: decrypted[(d['kind'],d['metadata'].get('namespace',''),d['metadata']['name'])]=d

    def chart(release):
        spec=release['spec'];namespace=release['metadata']['namespace']
        if 'chartRef' in spec: reference=spec['chartRef'];chart_spec=None
        else: chart_spec=spec['chart']['spec'];reference=chart_spec['sourceRef']
        source=objects[(reference['kind'],reference.get('namespace',namespace),reference['name'])]
        if source['kind']=='OCIRepository': path,provenance=oci(source)
        elif source['kind']=='GitRepository':
            repo=source['spec']['url'].removeprefix('https://github.com/').removesuffix('.git');commit=source['spec']['ref']['commit']
            url='https://codeload.github.com/'+repo+'/tar.gz/'+commit
            payload=fetch(url);path=unpack(payload,cache/commit)/chart_spec['chart']
            provenance={'url':url,'ref':commit,'archiveSHA256':hashlib.sha256(payload).hexdigest()}
        else:
            index=yaml.safe_load(fetch(source['spec']['url']+'/index.yaml'))
            entry=next(e for e in index['entries'][chart_spec['chart']] if e['version']==chart_spec['version'])
            url=entry['urls'][0]
            if not url.startswith('https://'): url=source['spec']['url']+'/'+url
            payload=fetch(url);assert hashlib.sha256(payload).hexdigest()==entry['digest']
            path=unpack(payload,cache/entry['digest']);provenance={'url':url,'ref':entry['version'],'archiveSHA256':entry['digest']}
        config=yaml.safe_load((path/'Chart.yaml').read_text())
        if source['kind']=='GitRepository' and config.get('dependencies'):
            dependencies=yaml.safe_load((path/'Chart.lock').read_text())['dependencies']
            (path/'charts').mkdir(exist_ok=True)
            for dependency in dependencies:
                index=yaml.safe_load(fetch(dependency['repository']+'/index.yaml'))
                item=next(e for e in index['entries'][dependency['name']] if e['version']==dependency['version'])
                url=item['urls'][0]
                target=path/'charts'/(dependency['name']+'-'+dependency['version']+'.tgz')
                if url.startswith('oci://'):
                    if not target.exists():
                        location=url.rsplit(':',1)[0]
                        pulled=subprocess.run([helm,'pull',location,'--version',dependency['version'],
                                               '--destination',str(path/'charts')],capture_output=True)
                        if pulled.returncode:raise ValueError('Pinned public OCI dependency download failed')
                    archive=target.read_bytes()
                else:
                    if not url.startswith('https://'):url=dependency['repository'].rstrip('/')+'/'+url
                    archive=target.read_bytes() if target.exists() else fetch(url)
                assert hashlib.sha256(archive).hexdigest()==item['digest']
                if not target.exists():target.write_bytes(archive)
                provenance.setdefault('dependencies',[]).append({'url':url,'version':dependency['version'],'archiveSHA256':item['digest']})
        return release,path,provenance

    charts=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for release,path,provenance in executor.map(chart,releases):
            charts.append((release,path,provenance))
            print('Fetched pinned chart '+release['metadata']['name'],flush=True)

    def merge(left,right):
        for k,v in right.items():
            if isinstance(v,dict) and isinstance(left.get(k),dict): merge(left[k],v)
            else:left[k]=v

    rendered=[]
    chart_map={}
    for release,path,provenance in charts:
        path, schema_changes = derived_chart(path, cache, fetch)
        if schema_changes:
            provenance["offlineValuesSchemas"] = schema_changes
        config={}
        for reference in release['spec'].get('valuesFrom',[]):
            key=(reference['kind'],release['metadata']['namespace'],reference['name'])
            d=decrypted.get(key,objects.get(key))
            if d is None and reference.get('optional'):continue
            if d is None:raise ValueError('Missing valuesFrom object: '+str(key))
            payload=values(d)[reference.get('valuesKey','values.yaml')] if d['kind']=='Secret' else d['data'][reference.get('valuesKey','values.yaml')]
            if reference.get('targetPath'):raise ValueError('Explicit targetPath support required')
            merge(config,yaml.safe_load(payload) or {})
        merge(config,release['spec'].get('values',{}))
        cmd=[helm,'template',release['spec'].get('releaseName',release['metadata']['name']),str(path),'--namespace',release['metadata']['namespace'],'--kube-version','1.36.4','--include-crds','--values','/dev/stdin','--api-versions','monitoring.coreos.com/v1','--api-versions','monitoring.coreos.com/v1/ServiceMonitor','--api-versions','monitoring.coreos.com/v1/PodMonitor']
        result=subprocess.run(cmd,input=yaml.safe_dump(config).encode(),capture_output=True)
        if result.returncode:raise RuntimeError('Helm render failed for '+release['metadata']['name']+' (diagnostics suppressed)')
        documents=[d for d in yaml.safe_load_all(result.stdout) if d]
        rendered.extend(documents)
        chart_map[release['metadata']['namespace']+'/'+release['metadata']['name']]={'path':str(path),'source':provenance,'renderedResources':len(documents)}
        print('Rendered '+release['metadata']['name']+': '+str(len(documents))+' resources',flush=True)

    # KubeVirt's operator creates its workload CRDs at runtime; collect the pinned
    # upstream CRDs rather than accepting unvalidated virtual-machine manifests.
    payload=fetch('https://codeload.github.com/kubevirt/kubevirt/tar.gz/refs/tags/v1.9.0')
    kv=unpack(payload,cache/'kubevirt-1.9.0')
    # Use KubeVirt's versioned API Swagger. Test fixtures with stale/minimal CRDs
    # are deliberately excluded so they cannot override the actual API schema.
    kv_swagger_path=kv/'api/openapi-spec/swagger.json'
    kv_swagger=json.loads(kv_swagger_path.read_text())

    swagger_url='https://raw.githubusercontent.com/kubernetes/kubernetes/v1.36.4/api/openapi-spec/swagger.json'
    swagger=json.loads(fetch(swagger_url))
    schemas={}
    for name,definition in swagger['definitions'].items():
        for gvk in definition.get('x-kubernetes-group-version-kind',[]):
            version=(gvk['group']+'/' if gvk['group'] else '')+gvk['version']
            schemas[version+':'+gvk['kind']]={'$ref':'#/definitions/'+name}
    swagger['definitions'].update(kv_swagger['definitions'])
    for kind in ['KubeVirt', 'VirtualMachine', 'VirtualMachineInstance', 'VirtualMachineInstanceMigration']:
        definition='v1.'+kind
        if definition not in kv_swagger['definitions']:
            raise ValueError('Missing versioned KubeVirt definition: '+definition)
        schemas['kubevirt.io/v1:'+kind]={'$ref':'#/definitions/'+definition}
    for document in native+rendered:
        if document['kind']!='CustomResourceDefinition':continue
        for version in document['spec']['versions']:
            schema=version.get('schema',{}).get('openAPIV3Schema')
            if schema:schemas[document['spec']['group']+'/'+version['name']+':'+document['spec']['names']['kind']]=schema

    output=root/'deployments/homelab/validation'
    output.mkdir(exist_ok=True)
    bundle={'definitions':swagger['definitions'],'schemas':schemas}
    (output/'schemas.json.gz').write_bytes(gzip.compress(json.dumps(bundle,separators=(',',':')).encode(),mtime=0))
    provenance={'kubernetes':{'url':swagger_url,'sha256':hashlib.sha256(fetch(swagger_url)).hexdigest()},'kubevirt':{'version':'v1.9.0','archiveSHA256':hashlib.sha256(payload).hexdigest(),'swaggerSHA256':hashlib.sha256(kv_swagger_path.read_bytes()).hexdigest()},'charts':{k:v['source'] for k,v in chart_map.items()},'vendors':vendors,'entrypoints':entrypoints,'schemaCount':len(schemas)}
    (output/'sources.json').write_text(json.dumps(provenance,indent=2)+'\n')
    (cache/'charts.json').write_text(json.dumps(chart_map,indent=2)+'\n')
    print('Wrote pinned validation schema bundle with '+str(len(schemas))+' GVKs; '+str(len(rendered))+' Helm resources rendered. Plaintext values remained in memory.',flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import traceback
        frames=traceback.extract_tb(error.__traceback__)
        print('Refresh call locations: '+', '.join(Path(frame.filename).name+':'+str(frame.lineno)+' '+frame.name for frame in frames))
        if isinstance(error, requests.HTTPError) and error.response is not None:
            from urllib.parse import urlsplit
            parsed=urlsplit(error.response.url)
            print('Public upstream HTTP status '+str(error.response.status_code)+' for '+str(parsed.hostname)+parsed.path)
        site=frames[-1]
        raise SystemExit('Schema refresh failed ('+type(error).__name__+') at '+Path(site.filename).name+':'+str(site.lineno)+'; value-bearing diagnostics suppressed.') from None
