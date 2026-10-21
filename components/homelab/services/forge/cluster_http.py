"""HTTP helpers shared by the forge controllers: redirect refusal and in-cluster Kubernetes access."""
import json
import os
from pathlib import Path
import ssl
import urllib.error
import urllib.request

SERVICE_ACCOUNT = Path('/var/run/secrets/kubernetes.io/serviceaccount')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Kubernetes:
    def __init__(self, service_account=SERVICE_ACCOUNT):
        self.service_account = Path(service_account)
        # The service address avoids a DNS dependency for egress-restricted controllers.
        self.base = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ['KUBERNETES_SERVICE_PORT']
        context = ssl.create_default_context(cafile=str(self.service_account / 'ca.crt'))
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def request(self, method, path, body=None, missing=False):
        # Re-read the projected token on each call; the kubelet rotates it during long runs.
        token = (self.service_account / 'token').read_text().strip()
        request = urllib.request.Request(self.base + path, method=method,
            headers={'Authorization': 'Bearer ' + token,
                     'Content-Type': 'application/json-patch+json' if method == 'PATCH' else 'application/json'},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            raise RuntimeError(f'Kubernetes {method} {path.split("?")[0]}: HTTP {error.code}') from None
