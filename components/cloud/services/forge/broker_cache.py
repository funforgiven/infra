"""Issue optional cache capabilities from trusted queue/descriptor metadata."""
from http.client import HTTPException
import json
from pathlib import Path
import re
import time
import urllib.request

CONTROL = 'http://forge-cache.forge-cache.svc:8082'
DESCRIPTOR = 'http://forgejo.forge.svc:8083'
TOKEN = Path('/run/cache/broker-token')
REPOSITORY = 'funforgiven/atollion'
LANES = {'linux-quality': {'linux', 'linux-x86_64'},
         'windows-build': {'linux', 'linux-x86_64'},
         'macos-native': {'macos', 'macos-x86_64'}}
LEASE_ANNOTATION = 'forge.fahrican.com/cache-lease'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def require(value):
    if not value:
        raise ValueError('Invalid cache authority')


def claim(repository, job, descriptor, now):
    """Forgejo15 prepares the positive attempt before the job enters the queue."""
    require(repository == REPOSITORY and job.get('status') == 'waiting')
    require(type(job.get('id')) is int and job['id'] > 0)
    require(type(job.get('attempt')) is int and job['attempt'] > 0)
    lane = job.get('name')
    require(lane in LANES and isinstance(job.get('runs_on'), list)
            and job['runs_on'] and set(job['runs_on']) <= LANES[lane])
    require(isinstance(descriptor, dict) and descriptor.get('repository') == repository
            and type(descriptor.get('job_id')) is int and type(descriptor.get('attempt')) is int
            and descriptor.get('job_id') == job['id']
            and descriptor.get('attempt') == job['attempt']
            and descriptor.get('name') == lane
            and descriptor.get('runs_on') == job['runs_on'])
    require(type(descriptor.get('run_id')) is int and descriptor['run_id'] > 0)
    require(isinstance(descriptor.get('head'), str)
            and re.fullmatch(r'[0-9a-f]{40}', descriptor['head']))
    event, ref = descriptor.get('event_name'), descriptor.get('ref')
    require(isinstance(ref, str))
    if event == 'pull_request':
        require(re.fullmatch(r'refs/pull/[1-9][0-9]*/(?:head|merge)', ref))
    else:
        require(event in {'push', 'workflow_dispatch'}
                and re.fullmatch(r'refs/heads/[A-Za-z0-9_./-]+', ref))
    return {'repository': repository, 'job_id': job['id'], 'attempt': job['attempt'],
            'run_id': descriptor['run_id'], 'head': descriptor['head'],
            'event_name': event, 'ref': ref, 'cache_lane': lane,
            'expires_unix': int(now) + 7200}


def carrier(lease, now):
    require(isinstance(lease, dict)
            and set(lease) == {'lease_id', 'actions_cache_url', 'cache_mode', 'expires_unix'})
    require(isinstance(lease['lease_id'], str) and re.fullmatch(r'[0-9a-f]{32}', lease['lease_id']))
    require(isinstance(lease['actions_cache_url'], str)
            and re.fullmatch(r'https://cache\.fahrican\.com/[0-9a-f]{64}/', lease['actions_cache_url']))
    require(lease['cache_mode'] == 'broker-scoped-v1'
            and type(lease['expires_unix']) is int and now < lease['expires_unix'] <= now + 7200)
    return {key: lease[key] for key in ('actions_cache_url', 'cache_mode', 'expires_unix')}


class CacheBroker:
    def request(self, method, address, value=None):
        token = TOKEN.read_text().strip()
        require(len(token) >= 32 and not any(c.isspace() for c in token))
        request = urllib.request.Request(address, method=method,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
            data=None if value is None else json.dumps(value).encode())
        with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
            require(response.geturl() == address)
            data = response.read(16385)
            require(len(data) <= 16384)
            return json.loads(data) if data else None

    def issue(self, repository, job):
        # No compiler cache lease for aggregate or Windows execution-only jobs.
        if repository != REPOSITORY or job.get('name') not in LANES:
            return None
        try:
            require(type(job.get('id')) is int and job['id'] > 0
                    and type(job.get('attempt')) is int and job['attempt'] > 0)
            metadata = self.request('GET', DESCRIPTOR + '/v1/jobs/' + str(job['id'])
                                    + '?attempt=' + str(job['attempt']))
            value = claim(repository, job, metadata, time.time())
            lease = self.request('POST', CONTROL + '/v1/leases', value)
            carrier(lease, time.time())
            require(lease['expires_unix'] == value['expires_unix'])
            return lease
        except InterruptedError:
            raise
        except (HTTPException, OSError, ValueError, KeyError, TypeError):
            # Never print exceptions, request bodies, capabilities or credentials.
            print('Optional compiler cache unavailable; continuing with a cold job.', flush=True)
            return None

    def revoke(self, identity):
        if not identity:
            return
        try:
            require(isinstance(identity, str) and re.fullmatch(r'[0-9a-f]{32}', identity))
            self.request('DELETE', CONTROL + '/v1/leases/' + identity)
        except InterruptedError:
            raise
        except (HTTPException, OSError, ValueError, KeyError, TypeError):
            print('Optional cache revocation unavailable; bounded lease expiry remains enforced.', flush=True)
