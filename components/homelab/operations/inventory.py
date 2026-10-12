#!/usr/bin/env python3
"""Map the frozen source inventory and captured PVC/PV metadata; no live calls."""
import argparse
import collections
import json
from pathlib import Path
import subprocess
import yaml

BASE = 'deployments/homelab/cluster/'

# Each rule is an architectural disposition, not an inference from the absence
# of a file. Object-specific exceptions below take precedence.
RULES = {
 'management/20-gitops': ('consolidated', ['bootstrap/flux'], 'One Flux installation owns the single bare-metal cluster; the guest management cluster is retired.'),
 'management/30-backup': ('replaced', ['deployments/homelab/hosts/backup.nix'], 'NixOS exports embedded-etcd snapshots and recovery keys off-server; CAPI management-cluster backup machinery is no longer required.'),
 'management/35-private-dns': ('consolidated', ['infrastructure/dns'], 'One retained private DNS VIP serves the existing homelab zones and aliases.'),
 'management/40-capi': ('removed', ['deployments/homelab/hosts'], 'K3s runs directly on the three NixOS hosts; Cluster API, CAPO, ORC, kubeadm providers, addon controller and their qualification objects no longer manage guest clusters.'),
 'management/bootstrap': ('consolidated', ['bootstrap/flux'], 'Bootstrap credentials and Git source are consolidated into the single target Flux installation.'),
 'undercloud/20-backup': ('replaced', ['deployments/homelab/hosts/backup.nix'], 'The physical Kubernetes control plane is replaced by K3s embedded etcd and host-level off-server recovery backups.'),
 'undercloud/20-gitops': ('consolidated', ['bootstrap/flux', 'deployments/homelab/cluster/waves.yaml'], 'Three old Flux/control-plane graphs become one semantic graph with explicit dependencies and a restore overlay.'),
 'undercloud/30-rook-ceph': ('replaced', ['infrastructure/rook', 'infrastructure/ceph', 'infrastructure/storage'], 'Rook-Ceph is retained with direct RBD/CephFS CSI; new Ceph identities/pools replace cloud pools after independently verified data exports.'),
 'undercloud/32-identity-controllers': ('retained', ['infrastructure/databases'], 'CloudNativePG and its Barman plugin retain PostgreSQL backup, restore and failover lifecycles.'),
 'undercloud/33-identity-data': ('retained', ['apps/identity/database'], 'ZITADEL PostgreSQL restores its original database and owner from the verified source backup/WAL archive.'),
 'undercloud/34-identity': ('retained', ['apps/identity/server'], 'ZITADEL, its master key, login material, domain and surviving client IDs remain.'),
 'undercloud/34-identity-configuration': ('replaced', ['components/homelab/providers/identity', 'deployments/homelab/credentials'], 'Workstation OpenTofu with preserved state replaces in-cluster OpenTofu reconciliation and output-copy wrappers.'),
 'undercloud/34-identity-qualification': ('replaced', ['apps/identity/database/restore-test.yaml', 'docs/migration/RUNBOOK.md'], 'Native database recovery qualification plus explicit OIDC/API checks replace tests against retired control planes.'),
 'undercloud/35-observability': ('consolidated', ['infrastructure/observability'], 'A single monitoring stack retains Grafana/Loki and monitoring functions; existing duplicate Prometheus/Alertmanager data is migrated or archived explicitly in the volume map.'),
 'undercloud/36-observability-integrations': ('consolidated', ['infrastructure/observability', 'apps/matrix'], 'One Alertmanager retains Telegram, Matrix and email integration credentials and routing.'),
 'undercloud/37-service-network': ('replaced', ['infrastructure/cilium', 'infrastructure/metallb', 'infrastructure/load-balancers', 'deployments/homelab/hosts/common.nix'], 'Cilium pod networking and kube-proxy replacement, MetalLB announcements and NixOS VLANs replace cloud service-network staging and host-cloud reconciliation.'),
 'undercloud/38-service-api-foundation': ('consolidated', ['infrastructure/controllers', 'infrastructure/dns', 'infrastructure/gateway', 'infrastructure/load-balancers'], 'One cert-manager/Envoy/MetalLB/DNS installation retains application endpoints, ACME account and management TLS; cloud API endpoints are retired separately.'),
 'undercloud/40-openstack-infrastructure': ('removed', ['deployments/homelab/hosts', 'infrastructure/cilium'], 'OpenStack MariaDB, RabbitMQ, OVN databases and cloud shared infrastructure are unnecessary when apps and CSI run directly on bare-metal Kubernetes; archive their state for rollback.'),
 'undercloud/50-openstack-core': ('removed', ['deployments/homelab/hosts', 'infrastructure/storage'], 'Keystone, Nova, Neutron, Glance, Placement and their cloud APIs/control plane are retired; Kubernetes scheduling, native networking and direct CSI provide the retained workloads.'),
 'undercloud/55-external-network': ('removed', ['deployments/homelab/hosts/common.nix', 'infrastructure/load-balancers'], 'Neutron/OVN external-network machinery is replaced by host VLANs, bridges, MetalLB and the retained RouterOS network policy.'),
 'undercloud/60-openstack-services': ('removed', ['infrastructure/storage', 'infrastructure/load-balancers'], 'Cinder, Manila, Octavia and cloud service plumbing are replaced by direct RBD/CephFS CSI and MetalLB/Envoy; source bytes must be exported before cloud retirement.'),
 'undercloud/70-capi-management-infrastructure': ('removed', ['deployments/homelab/hosts'], 'No guest management Kubernetes cluster is needed; the three bare-metal K3s servers own application lifecycles.'),
 'undercloud/71-magnum': ('removed', ['deployments/homelab/hosts'], 'Magnum no longer provisions guest Kubernetes clusters; NixOS declares the single physical cluster.'),
 'undercloud/72-management-uis': ('removed', ['docs/migration/RUNBOOK.md'], 'OpenStack dashboard/UI functions are retired with the cloud APIs; SSH, Kubernetes/Flux and retained Grafana provide target operations.'),
 'undercloud/80-magnum-workload': ('removed', ['deployments/homelab/hosts'], 'Guest workload-cluster provisioning is replaced by the single bare-metal cluster; no application is removed by this wrapper retirement.'),
 'undercloud/81-services-foundation': ('replaced', ['deployments/homelab/credentials', 'components/homelab/operations', 'infrastructure/storage'], 'Cloud tenant/flavor/quota and in-cluster OpenTofu foundation abstractions are retired; encrypted concrete app inputs, independent provider state and direct storage remain.'),
 'undercloud/82-services-cluster': ('replaced', ['deployments/homelab/hosts', 'bootstrap/flux'], 'NixOS/K3s and one Flux bootstrap replace CAPI/Magnum guest worker/control-plane lifecycle and associated enrollment jobs.'),
 'undercloud/83-services-hosts': ('replaced', ['apps/home-automation', 'apps/unifi', 'components/nix/servers/mail-aws.nix'], 'Home automation is a Kubernetes workload, UniFi retains one supported KubeVirt Ubuntu guest, and independent AWS mail remains; generic cloud-host deployment wrappers are removed.'),
 'undercloud/84-mail-aws': ('replaced', ['components/homelab/providers/mail-aws', 'components/nix/servers/mail-aws.nix'], 'Existing AWS EC2/EIP/RDS/S3/IAM/monitoring resources keep preserved provider state; workstation OpenTofu replaces the cluster-hosted reconciler.'),
 'undercloud/85-service-dns': ('replaced', ['components/homelab/providers/dns'], 'Existing Cloudflare records remain under workstation OpenTofu with their original state, names and addresses.'),
 'undercloud/85-unifi': ('replaced', ['apps/unifi'], 'The cold-exported supported UniFi Ubuntu guest becomes one KubeVirt VM with the same services address and native UOS data.'),
 'undercloud/86-forge-foundation': ('removed', ['apps/forge'], 'The CI cloud tenant, flavors, network and quota foundation is unnecessary for Linux Kubernetes job runners; Forgejo, cache and artifact services remain.'),
 'undercloud/87-forge-runners': ('removed', ['apps/forge'], 'Native Windows/macOS VM runners and their OpenStack provisioning are removed at the owner’s explicit request; Linux CI remains.'),
 'undercloud/88-netbird-policy': ('replaced', ['components/homelab/providers/netbird', 'apps/netbird'], 'NetBird account, groups, policies and DNS remain under workstation OpenTofu with preserved state and restored server database.'),
 'services/10-platform-controllers': ('consolidated', ['infrastructure/controllers'], 'Duplicate platform controllers become one cert-manager/Envoy installation for the single cluster.'),
 'services/11-iot-network': ('retained', ['infrastructure/multus', 'apps/home-automation/network-attachment.yaml'], 'Multus and physical IoT VLAN attachment remain; old guest-node policy is replaced by NixOS host networking.'),
 'services/12-observability': ('consolidated', ['infrastructure/observability'], 'The workload and physical-cluster monitoring stacks become one stack; all source persistent data has a separate disposition.'),
 'services/15-backup-controller': ('retained', ['infrastructure/velero'], 'Velero/Kopia and the existing B2 destination retain application backup lifecycles using direct CSI classes.'),
 'services/16-backup-policy': ('retained', ['infrastructure/backups'], 'Application schedules, hooks and restore qualification remain; cloud storage handles are never rebound to a different CSI driver.'),
 'services/20-platform-gateway': ('retained', ['infrastructure/gateway'], 'Private/public Envoy gateways retain names, VIPs, TLS and application routes with MetalLB ownership.'),
 'services/24-unifi': ('retained', ['apps/unifi'], 'Native UniFi OS application, controller identity, AP adoption, TLS, metrics and backups remain in the supported KubeVirt guest.'),
 'services/25-home-automation': ('retained', ['apps/home-automation'], 'Home Assistant/Matter/MQTT/Zigbee/Thread state, integrations, static IoT addresses and radios remain; network attachment is rebuilt through Multus/macvlan.'),
 'services/30-factorio': ('retained', ['apps/factorio'], 'Factorio worlds, credentials, mods and the port-preserving external address remain.'),
 'services/31-valheim': ('retained', ['apps/valheim'], 'Valheim worlds, identity and external ports remain with direct RBD storage and restore qualification.'),
 'services/40-media': ('retained', ['apps/media'], 'Navidrome, SFTPGo, Beets, AudioMuse/PostgreSQL/Redis, Discord music and the shared media library remain; Manila NFS becomes direct CephFS.'),
 'services/45-wallos': ('retained', ['apps/wallos'], 'Wallos SQLite database, uploaded logos and existing OIDC client remain.'),
 'services/46-forge': ('retained', ['apps/forge'], 'Forgejo repositories/database/LFS/packages, signing, Linux/Atollion CI, cache and app recovery remain; native Windows/macOS objects have explicit exceptions.'),
 'services/47-matrix': ('retained', ['apps/matrix'], 'Synapse, MAS, Element, PostgreSQL, media, signing/session keys and encrypted relay state remain.'),
 'services/48-netbird': ('retained', ['apps/netbird'], 'NetBird server/PostgreSQL, STUN, Kubernetes operator, routing/DNS and access policies remain.'),
 'services/50-synthetic-monitoring': ('retained', ['infrastructure/synthetic-monitoring'], 'Application and public-edge availability probes remain in the consolidated monitoring stack.'),
 'host-runtime/atollion-agents.sops.yaml': ('retained', ['deployments/homelab/credentials', 'apps/forge'], 'Atollion agent/recovery credentials remain encrypted and available for Linux CI recovery.'),
 'host-runtime/matrix-forge-macos.sops.yaml': ('removed', ['apps/matrix'], 'The retired macOS runner bot/runtime is unnecessary after the owner-authorized runner removal; general Matrix alerts remain.'),
 'host-runtime/unifi.sops.yaml': ('retained', ['deployments/homelab/credentials', 'apps/unifi'], 'Existing UniFi native guest runtime credentials are delivered through its encrypted cloud-init configuration.'),
}

def target_path(value):
    return value if value.startswith(('components/', 'deployments/', 'docs/')) else BASE+value

def group(source):
    suffix=source.removeprefix('deployments/homelab/cloud/')
    return '/'.join(suffix.split('/')[:2])

def disposition(item):
    key=group(item['source'])
    if key in RULES:
        status, targets, reason=RULES[key]
    elif key.endswith(('kustomization.yaml', 'waves.yaml', 'namespaces.yaml')):
        status, targets, reason=('consolidated', ['deployments/homelab/cluster'],
          'Numbered old cluster wrappers, namespaces and waves are consolidated into one semantic Flux dependency graph; service-specific mappings identify preserved functions.')
    else:
        raise ValueError('Unmapped source group: '+key)
    name=item.get('name') or ''
    source=item['source']
    if key=='management/40-capi' and ('cert-manager' in source or name in ['zitadel-infra-admin','zitadel-infra-viewer']):
        status,targets,reason=('consolidated',['infrastructure/controllers','deployments/homelab/cluster/access.yaml'],
          'cert-manager and the surviving ZITADEL administrator/viewer Kubernetes bindings remain in the single cluster; duplicate guest installation/qualification wrappers are consolidated.')
    if key=='services/46-forge' and (any(word in name for word in ['macos','windows']) or Path(source).name in ['native-brokers.yaml','native-monitoring.yaml']):
        status,targets,reason=('removed',['apps/forge'],
          'The owner explicitly permits removing native Windows/macOS runners; their broker, qualification, metrics, quota and credential objects are retired. Linux runners and application recovery remain.')
    if key=='undercloud/38-service-api-foundation' and (name in ['private-envoy','private-api','private','private-https-redirect'] or 'metallb-fallback' in source or item['kind']=='CiliumLoadBalancerIPPool'):
        status,targets,reason=('replaced',['infrastructure/load-balancers','infrastructure/dns','infrastructure/gateway'],
          'The OpenStack API VIP and dual Cilium/MetalLB fallback staging are retired; MetalLB directly owns retained DNS/application VIPs and the surviving management gateway.')
    if item['apiVersion']=='kustomize.config.k8s.io/v1beta1':
        status='consolidated' if status!='removed' else status
        reason+=' This entry is a local Kustomize configuration document, not a live API object.'
    return {'disposition':status,'targets':[target_path(t) for t in targets], 'reason':reason}

def claim_plan(cluster, namespace, name):
    identity=namespace+'/'+name
    if namespace=='openstack':
        return {'action':'archive-then-retire','target':None,'method':'Cold filesystem exports plus final native MariaDB/OVN state exports; preserve control-plane metadata with rollback package.',
                'reason':'These databases and queue volumes exist solely for the retired OpenStack control plane; no application database is removed.'}
    if namespace.endswith('-restore') or namespace=='backup-qualification':
        return {'action':'rebuild-qualification','target':identity,'method':'Archive the old qualification evidence; create clean direct-CSI test claims and rerun restores.',
                'reason':'These are disposable restore/canary copies, not authoritative production state. Their cleanup never authorizes deleting a production/source backup.'}
    if namespace in ['identity','netbird'] and name.startswith(('zitadel-postgres-', 'netbird-postgres-')):
        return {'action':'database-recovery','target':identity,'method':'Restore the final verified native CNPG/Barman base backup plus complete WAL; the operator creates three new ceph-block claims.',
                'reason':'Recover one consistent database identity and rebuild replicas; do not copy or attach three live PostgreSQL data directories independently.'}
    if cluster=='infrastructure' and namespace=='observability':
        target='services-observability/'+name
        if name.startswith('prometheus-'):
            return {'action':'archive-history','target':None,'method':'Save cold TSDB directories from both physical-cluster replicas, including block metadata and WAL, as separate identified archives.',
                    'reason':'The consolidated 20Gi Prometheus instance continues workload-cluster history. Old physical-cluster replica histories remain independently restorable; overlapping replica blocks are not blindly merged.'}
        if name.startswith('alertmanager-'):
            return {'action':'archive-and-merge-silences','target':'services-observability/'+name.rsplit('-',1)[0]+'-0',
                    'method':'Archive all three old data directories; export silences via native API and import verified active silences into the retained single Alertmanager.',
                    'reason':'Three HA copies become one Alertmanager. Retain every original archive, deduplicate silence UUIDs and verify receiver routing.'}
        return {'action':'filesystem-restore','target':target,'method':'Cold full filesystem archive with numeric ownership, modes, xattrs and checksums into a new ceph-block claim.',
                'reason':'Grafana database/plugins and Loki historical files remain; only their monitoring namespace changes.'}
    method='Cold full filesystem archive with numeric ownership, modes, xattrs and checksums into a new ceph-block claim.'
    if namespace=='media' and name=='media-library':
        method='Quiesce media writers, export every Manila/NFS file with numeric ownership/xattrs, and restore into the new ceph-filesystem RWX claim.'
    if namespace=='matrix' and name=='matrix-postgres':
        method='Final native PostgreSQL 17 dump of all app databases and roles; restore into an empty PostgreSQL 17 ceph-block claim before Synapse/MAS start.'
    if namespace=='media' and name=='audiomuse-postgres':
        method='Final native PostgreSQL 15 dump and role export; restore before AudioMuse starts. Archive the cold old filesystem as rollback evidence.'
    if namespace=='home-automation':
        method='Run existing app-native automation/Thread backups, stop every writer, archive all state and backup files, and restore before HA/Matter/MQTT/Zigbee/OTBR start.'
    if namespace=='forge' and name=='forgejo-data':
        method='Final Forgejo native dump plus cold complete data export including SQLite, repositories, LFS, packages, config/signing keys and numeric ownership.'
    if namespace=='matrix' and name=='matrix-relay':
        method='Cold export of the complete SQLite database, WAL/SHM where present, relay session and E2E crypto store; retain stable device ID and tokens.'
    return {'action':'filesystem-restore' if 'PostgreSQL' not in method else 'database-recovery',
            'target':identity,'method':method,'reason':'Preserve existing application or workload-monitoring bytes on a freshly provisioned direct CSI claim; source CSI handles are archived, never rewritten.'}

def generate(root,kustomize):
    directory=root/'docs/migration'
    source=json.loads((directory/'source-inventory.json').read_text())
    mapped=[dict(item,**disposition(item)) for item in source['objects']]
    stages=[dict(item,**disposition(item)) for item in source['fluxStages']]
    providers=[]
    for item in source['providerFiles']:
        path=item['source'];target=None
        for old,new in [('/identity/tofu/','identity'),('/dns/tofu/','dns'),('/mail-aws/tofu/','mail-aws'),('/netbird/tofu/','netbird')]:
            if old in path:target='components/homelab/providers/'+new+'/'+Path(path).name
        providers.append(dict(item,disposition='retained' if target else 'removed',target=target,
             reason='Preserved external provider resources and original state; workstation OpenTofu replaces Kubernetes backend/controller.' if target else
             'OpenStack tenant/host/runner provisioning is retired. Linux CI uses Kubernetes, UniFi uses KubeVirt and IoT uses Multus; archive old provider state before source deletion.'))
    claims=[dict(item,**claim_plan('infrastructure' if '/undercloud/' in item['source'] else 'services',item['namespace'],item['name'])) for item in source['claims']]
    targets=[]
    for path in sorted((root/'deployments/homelab').rglob('kustomization.yaml')):
        if 'routeros' in path.parts:continue
        rendered=subprocess.run([kustomize,'build','--load-restrictor','LoadRestrictionsNone',str(path.parent)],capture_output=True,check=True)
        for d in yaml.safe_load_all(rendered.stdout):
            if d:targets.append({'apiVersion':d['apiVersion'],'kind':d['kind'],'namespace':d['metadata'].get('namespace',''), 'name':d['metadata']['name'],'entrypoint':str(path.parent.relative_to(root))})
    for item in mapped:
        ns=item.get('namespace') or ''
        expected_ns='services-observability' if ns=='observability' else ns
        candidates=[t for t in targets if t['kind']==item['kind'] and t['name']==item['name'] and t['namespace']==expected_ns]
        item['matchingTargetObjects']=list({(t['apiVersion'],t['kind'],t['namespace'],t['name']):t for t in candidates}.values()) if item['disposition']!='removed' else []
    live=json.loads((directory/'live-volume-inventory.json').read_text())
    pvcs=[];pvs=[]
    for cluster in ['services','infrastructure']:
        active={d['spec']['volumeName'] for d in live[cluster+'_pvc']}
        for d in live[cluster+'_pvc']:
            ns=d['metadata']['namespace'];name=d['metadata']['name']
            pvcs.append({'sourceCluster':cluster,'namespace':ns,'name':name,'capacity':d['spec']['resources']['requests']['storage'],
                         'sourcePV':d['spec']['volumeName'],'sourceClass':d['spec']['storageClassName'],**claim_plan(cluster,ns,name)})
        for d in live[cluster+'_pv']:
            claim=d['spec'].get('claimRef',{})
            plan=claim_plan(cluster,claim.get('namespace',''),claim.get('name','')) if d['metadata']['name'] in active else {
                'action':'archive-and-inspect-released-volume','target':None,
                'method':'Identify source CSI handle and export/inspect the retained bytes with the old driver while it still exists; record checksums and historical claim identity.',
                'reason':'A Released PV is not proof that its bytes are disposable. Preserve its independent export or documented authoritative-backup equivalence before any retirement.'}
            pvs.append({'sourceCluster':cluster,'name':d['metadata']['name'],'phase':d['status']['phase'],
                        'capacity':d['spec']['capacity']['storage'],'claim':claim.get('namespace','')+'/'+claim.get('name',''),
                        'driver':d['spec'].get('csi',{}).get('driver'),'handle':d['spec'].get('csi',{}).get('volumeHandle'),**plan})
    cloud_path=directory/'live-cloud-volume-inventory.json'
    cloud=json.loads(cloud_path.read_text()) if cloud_path.exists() else {}
    known_handles={d['handle']:d for d in pvs if d.get('handle')}
    cloud_plans=[]
    for volume in cloud.get('volumes',[]):
        identifier=volume['id'];name=volume.get('name','')
        known=known_handles.get(identifier)
        image=volume.get('imageMetadata',{}).get('image_name','')
        if known:
            plan={key:known[key] for key in ['action','target','method','reason']}
            plan['sourceClaim']=known['claim']
        elif name=='unifi-root':
            plan={'action':'cold-guest-disk-restore','target':'unifi/unifi-root',
                  'method':'Stop the guest; export the 64Gi source boot device to independently verified raw disk.img; restore into the 80Gi filesystem RBD claim with UID/GID 107 and prepare restored cloud-init/netplan before first boot.',
                  'reason':'Preserve the supported Ubuntu 24.04 guest, native UOS state, origin CA/private keys, poller account, adoption identity and backups. The new services NIC owns the same .127 address directly.'}
        elif name.startswith('forge-macos') or 'forge-windows' in image:
            plan={'action':'owner-approved-runner-retirement','target':None,
                  'method':'Archive registration/provider/provenance metadata and preserve authoritative repositories/artifacts in Forgejo; remove runner boot-image data only after the source retirement gate.',
                  'reason':'The owner explicitly permits ditching native Windows/macOS runners. These boot devices are identified by guest name or source image metadata, not inferred from being unattached.'}
        elif name.startswith('capi-management-'):
            plan={'action':'archive-control-plane-then-retire','target':None,
                  'method':'Take final CAPI management-cluster etcd/state/key exports and an independent cold boot-volume archive for the rollback package.',
                  'reason':'The three management VMs are replaced by the single bare-metal K3s control plane; they contain no target application workload.'}
        else:
            plan={'action':'archive-and-inspect-unclaimed-cloud-volume','target':None,
                  'method':'Export the entire source volume independently, record its checksum and historical owner/application identity, and inspect before any deletion.',
                  'reason':'This Cinder device is not represented by a captured Kubernetes PV. Absence of a PV/attachment does not establish that its bytes are disposable.'}
        cloud_plans.append(dict(volume,**plan))
    guest_plans=[]
    for guest in cloud.get('servers',[]):
        name=guest['name']
        if name=='unifi':action='replace-with-supported-KubeVirt-guest';target='unifi/unifi';reason='Preserve the cold-exported boot disk and native controller identity.'
        elif name.startswith('forge-macos'):action='owner-approved-runner-retirement';target=None;reason='Native macOS runner retirement is explicitly authorized; preserve Forgejo app data and registration/provenance archives.'
        else:action='archive-source-control-plane-and-retire-guest';target='three NixOS K3s hosts';reason='CAPI/Magnum management, guest control planes and workers are consolidated into one physical cluster. Export app volumes separately, and record every local/RBD ephemeral Nova root disk for source recovery before Ceph retirement.'
        guest_plans.append(dict(guest,action=action,target=target,reason=reason))
    image_plans=[]
    for image in cloud.get('images',[]):
        name=image['name']
        if 'forge-macos' in name or 'forge-windows' in name:
            action='owner-approved-runner-image-retirement';reason='Image only supports the explicitly retired native Windows/macOS runners.'
        elif name.startswith(('s_rally_','Cirros')):
            action='retire-cloud-qualification-image';reason='Cloud API benchmark/qualification image has no retained application data or target compute-cloud function.'
        else:
            action='archive-source-image-and-retire-Glance-object';reason='Archive the original image/provenance for source recovery. Physical hosts use NixOS; guest Kubernetes provisioning is retired; active UniFi preserves its separate cold boot device.'
        image_plans.append(dict(image,action=action,target=None,reason=reason))
    owner_capture=json.loads((directory/'live-address-owner-inventory.json').read_text())
    port_owners={entry['id']:entry for entry in owner_capture['ports']}
    loadbalancers={entry['vip_port_id']:entry for entry in owner_capture['loadbalancers']}
    retained_addresses={
      '10.21.40.122':('services Envoy / Forge SSH', 'services/HTTPS and TCP 2222 retain the original address under MetalLB.'),
      '10.21.40.123':('games/factorio', 'Retain Factorio world identity and UDP 34197 under MetalLB.'),
      '10.21.40.124':('games/valheim', 'Retain Valheim world identity and UDP 2456/2457 under MetalLB.'),
      '10.21.40.127':('unifi/unifi services NIC', 'The cold-restored supported guest owns the same services address directly through its bridge NIC.'),
      '10.21.40.128':('public Envoy / Matrix and NetBird HTTPS', 'Retain the public HTTPS VIP and existing RouterOS WAN forwarding under MetalLB.'),
      '10.21.40.129':('netbird/netbird-stun', 'Retain STUN UDP 3478 and existing WAN forwarding under MetalLB.'),
    }
    floating_plans=[]
    for item in cloud.get('floatingips',[]):
        address=item['floating_ip_address'];port=port_owners[item['port_id']]
        lb=loadbalancers.get(item['port_id'])
        if address in retained_addresses:
            target,reason=retained_addresses[address];action='preserve-address-transfer-ownership'
        elif address in {'10.21.40.125','10.21.40.126'}:
            target=None;action='owner-approved-native-runner-address-retirement'
            reason='The captured port identifies the explicitly retired Windows/macOS runner; no retained application takes its address.'
        elif address in {'10.21.40.101','10.21.40.102','10.21.40.103'} and port['name'].startswith('capi-management-'):
            target=None;action='archive-management-guest-then-retire-address'
            reason='This is a source CAPI management VM endpoint. Preserve its guest/control-plane recovery archive, then retire the VM; physical NixOS host management addresses remain.'
        elif address=='10.21.40.100' and lb and lb['name']=='capi-management-api':
            target='10.21.20.128';action='replace-cloud-control-plane-endpoint'
            reason='The source CAPI API is retired after etcd/PKI recovery export; the physical K3s API is the replacement control plane.'
        elif address=='10.21.40.197' and lb and lb['name'].endswith('-kubeapi'):
            target='10.21.20.128';action='replace-cloud-control-plane-endpoint'
            reason='Read-only Octavia/Neutron inspection identifies this as the actual Magnum services guest Kubernetes API, not an unowned app VIP. Archive its control-plane state, then retire guest provisioning and use the physical K3s API.'
        else:
            raise ValueError('Unmapped source floating IP requires an explicit ownership disposition')
        floating_plans.append(dict(item,sourcePort=port,sourceLoadBalancer=lb,action=action,target=target,reason=reason))
    result={'sourceCommit':source['commit'],'volumeCaptureTime':live['capturedAt'],'objects':mapped,'fluxStages':stages,
            'providerFiles':providers,'declaredClaims':claims,'liveClaims':pvcs,'liveVolumes':pvs,'cloudVolumes':cloud_plans,'novaGuests':guest_plans,'glanceImages':image_plans,'manilaShares':cloud.get('shares',[]),'floatingIPs':floating_plans,'addressOwnerCaptureTime':owner_capture['capturedAt'],'cloudInventoryErrors':cloud.get('errors',[]),
            'additionalRequiredSources':['Cold UniFi VM boot volume and its source Nova/Cinder identity.',
              'All other Nova/Glance/Cinder/Manila volumes and snapshots, including unattached or released data not represented by a Kubernetes PVC.',
              'All old provider backend states, Ceph FSID/mon maps/keyrings/CRDs and /var/lib/rook monitor state on OS disks.',
              'Complete host disk/OS recovery archives before reinstall; old cluster etcd snapshots and bootstrap credentials.',
              'Generated TLS certificate/private-key Secrets and app signing/session credentials absent from desired-state YAML.']}
    (directory/'inventory-map.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Existing services and migration inventory','',
     'The source is commit `'+source['commit']+'`. `inventory-map.json` maps every one of its '+str(len(mapped))+' source document entries, including local Kustomize files, '+str(len(stages))+' Flux stages, '+str(len(providers))+' provider files and '+str(len(claims))+' explicit claims. It also maps all '+str(len(pvcs))+' captured live claims and '+str(len(pvs))+' PVs individually, including released volumes and implicit chart/operator claims. These are declarative/read-only inventories, not proof of backup completeness or used-byte measurements.','',
     'Every removed entry has an explicit reason. A target path describes the surviving function; `matchingTargetObjects` records direct name/kind matches where they exist. Namespace changes, controller-managed resources and replaced cloud objects are identified by the architectural rule rather than falsely claiming identical API objects.','',
     '## Source function mapping','', '| Source group | Disposition | Replacement / justification |','| --- | --- | --- |']
    groups=collections.Counter(group(d['source']) for d in mapped)
    for key in sorted(groups):
        sample=next(d for d in mapped if group(d['source'])==key)
        lines.append('| `'+key+'` ('+str(groups[key])+') | '+sample['disposition']+' | '+sample['reason'].replace('|','/')+' Targets: '+', '.join('`'+t+'`' for t in sample['targets'])+' |')
    lines+=['','## Every live claim','',
       'Production files restore into newly provisioned `ceph-block` or `ceph-filesystem` claims. Native PostgreSQL recovery creates its own new claims. The source handle belongs to its old storage driver and must never be repointed to direct Rook CSI. The machine-readable file also gives every PV handle and its disposition.','',
       '| Source cluster | Claim | Requested size | Action | Destination |','| --- | --- | --- | --- | --- |']
    for d in pvcs:lines.append('| '+d['sourceCluster']+' | `'+d['namespace']+'/'+d['name']+'` | '+d['capacity']+' | '+d['action']+' | '+('`'+d['target']+'`' if d['target'] else 'Independent archive')+' |')
    lines+=['','## Cloud disks, guests and images','',
      'Read-only cloud inspection also captured '+str(len(cloud_plans))+' Cinder volumes, '+str(len(guest_plans))+' Nova guests, '+str(len(image_plans))+' Glance images, '+str(len(cloud.get('shares',[])))+' Manila share and '+str(len(cloud.get('floatingips',[])))+' floating IPs. Every volume/guest/image has an individual disposition in `inventory-map.json`. This includes unclaimed volumes absent from the PV list and the unattached Windows boot device identified by its source image metadata. No byte exports have been performed.','',
      'The UniFi root is `a7dbe35a-ddfa-41fe-ae76-13481f3bc8c6`, 64Gi, attached to Nova guest `294f80d3-6e79-4760-a527-29f49296938f`. The shared 1Ti media share is `fcbda35a-8a7e-443c-97fa-5f9732a1ba85`; its old NFS export is recorded in `live-cloud-volume-inventory.json`. Source guest roots not shown as Cinder devices require their Nova/libvirt backend identity before source Ceph can be retired.','',
      'Forty-one TLS Secrets, twelve provider state Secrets and the ACME account key are captured in `secrets/source-certificates-and-state.sops.yaml`. Public fingerprints, expiry and state serial/lineage metadata are in `live-certificate-state-inventory.json`. Seed only surviving app TLS/account material before cert-manager starts; cluster-specific webhook/database/control-plane certificates regenerate. Do not apply the entire source archive as a Kubernetes bundle.','']
    lines+=['','## Every cloud floating IP','',
      'The port/load-balancer ownership is captured in `live-address-owner-inventory.json`. All thirteen addresses have individual dispositions; a Neutron port marked DOWN can still represent an ONLINE OVN/Octavia VIP and does not prove ARP ownership is gone. The actual guest workload API uses `.40.197`; `.40.121` is an obsolete desired/reserved guest-API endpoint, not the observed allocated floating IP.','',
      '| Source address | Captured owner | Action | Target |', '| --- | --- | --- | --- |']
    for item in floating_plans:
        owner=(item.get('sourceLoadBalancer') or item['sourcePort'])['name']
        lines.append('| `'+item['floating_ip_address']+'` | `'+owner+'` | '+item['action']+' | '+str(item['target'] or 'Retired after archive/owner gate')+' |')
    lines+=['','## Sources outside the PVC list','']+['- '+item for item in result['additionalRequiredSources']]
    lines+=['','These additional exports are mandatory cutover gates. The prepared inventory does not claim that live VM disks, monitor-state archives have already been copied. Generated TLS/account/provider Secrets are captured in the separately encrypted source archive; refresh them immediately before cutover. Independent AWS mail is retained in place, with existing provider state, RDS/S3 recovery and stable EIP; its storage is not a local Ceph migration.','',
     '## Address and certificate ownership','', '| Address / identity | Target owner and migration treatment |','| --- | --- |',
     '| `10.21.20.10–12`, `10.21.30.10–12` | Same three physical hosts; NixOS management/Ceph VLANs. Preserve Ed25519 SSH host identity. |',
     '| `10.21.20.128` | K3s API, host keepalived. Stop the old API owner before reuse. Existing kubeconfig CA changes with the rebuilt cluster. |',
     '| `10.21.20.129` | Private CoreDNS, MetalLB. Same DNS forwarder address and service zones. |',
     '| `10.21.20.131` | Retained management HTTPS Envoy gateway for ZITADEL/Grafana. Preserve ACME account and certificate/key. |',
     '| `10.21.20.130` | Retired OpenStack API gateway. No application is moved onto this obsolete endpoint. Retire its DNS/certificate after archive verification. |',
     '| `10.21.40.120` | Home Assistant HTTP-only LAN Service on 8123. IoT address is separate. The old Ubuntu guest SSH endpoint is retired. |',
     '| `10.21.40.121` | Retired guest Kubernetes API; the physical API is `10.21.20.128`. Do not reuse while an old owner remains. |',
     '| `10.21.40.122` | Private application HTTPS Envoy gateway. Preserve names, public/private DNS and corresponding TLS Secrets. |',
     '| `10.21.40.123`, `.124` | Factorio/Valheim MetalLB Services, same UDP ports and RouterOS WAN/hairpin mappings. |',
     '| `10.21.40.125`, `.126` | Retired native Windows/macOS runner addresses. Forgejo SSH and cache remain on the services gateway at `.122`; remove old runner access rules and reserve these retired addresses outside MetalLB pools. |',
     '| `10.21.40.127` | UniFi guest services NIC on `br-services`; reserve outside MetalLB pools and remove the old Neutron FIP owner first. |',
     '| `10.21.40.128` | Public Envoy for Matrix/NetBird, existing WAN 80/443 forwarding. |',
     '| `10.21.40.129` | NetBird STUN UDP Service. |',
     '| `10.21.50.10`, `.11`, `.20`, `.21` | HA pod, separate OTBR pod, Zigbee RCP and Thread RCP. Preserve VLAN/radio addresses and pairing/network datasets. |',
     '| Cloudflare / AWS mail / OIDC IDs | Retain existing state and external identities. Never apply these providers against an empty state. |',
     '| Generated app TLS, signing/session and E2E keys | Export encrypted before shutdown, restore before applications, verify fingerprint/identity. A source manifest alone does not contain every generated key. |','']
    (directory/'INVENTORY.md').write_text('\n'.join(lines))
    print(json.dumps({'sourceEntries':len(mapped),'fluxStages':len(stages),'providerFiles':len(providers),'declaredClaims':len(claims),'liveClaims':len(pvcs),'liveVolumes':len(pvs),'dispositions':dict(collections.Counter(d['disposition'] for d in mapped))}))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root',type=Path,default=Path(__file__).resolve().parents[3])
    parser.add_argument('--kustomize',default='kustomize')
    args=parser.parse_args()
    generate(args.repository_root,args.kustomize)

if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Inventory generation failed ('+type(error).__name__+'); value-bearing diagnostics suppressed.') from None
