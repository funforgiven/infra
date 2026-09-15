#!/usr/bin/env python3
"""Attach an unnumbered, automation-only IoT NIC to each services worker."""
import hashlib
import json
import subprocess
import sys
import uuid

kubectl = sys.argv[1]


def read(*command):
    return json.loads(subprocess.check_output(command, text=True))


network = read('openstack', 'network', 'show', 'services-iot', '-f', 'json')
if network['provider:physical_network'] != 'physnet-iot' or network['mtu'] != 1500:
    raise SystemExit('IoT provider-network contract mismatch')
nodes = read(kubectl, 'get', 'nodes', '-l', '!node-role.kubernetes.io/control-plane', '-o', 'json')
for node in nodes['items']:
    node_name = node['metadata']['name']
    provider = node['spec']['providerID']
    if not provider.startswith('openstack:///'):
        raise SystemExit('Unexpected node provider')
    instance = str(uuid.UUID(provider.removeprefix('openstack:///')))
    suffix = hashlib.sha256(instance.encode()).hexdigest()[:6]
    mac = 'fa:16:51:' + ':'.join(suffix[i:i + 2] for i in range(0, 6, 2))
    name = 'services-iot-' + instance
    ports = read('openstack', 'port', 'list', '--network', network['id'], '--name', name, '-f', 'json')
    if len(ports) > 1:
        raise SystemExit('Duplicate managed IoT port')
    if not ports:
        port = read('openstack', 'port', 'create', name, '--network', network['id'],
                    '--no-fixed-ip', '--disable-port-security', '--mac-address', mac,
                    '--tag', 'managed-by-services-cluster', '-f', 'json')
    else:
        port = read('openstack', 'port', 'show', ports[0]['ID'], '-f', 'json')
    if port['mac_address'] != mac or port['fixed_ips'] or port['port_security_enabled']:
        raise SystemExit('Managed IoT port contract mismatch')
    if port['device_id'] not in ('', instance):
        raise SystemExit('IoT port is attached to an unexpected server')
    if not port['device_id']:
        subprocess.run(['openstack', 'server', 'add', 'port', instance, port['id']], check=True)
    subprocess.run([kubectl, 'label', 'node', node_name,
                    'fahrican.com.node-restriction.kubernetes.io/iot=true', '--overwrite'], check=True)
    print(f'IoT NIC reconciled for {node_name}')
