# Upstream installation and validation provenance

`deployments/homelab/validation/vendors.json` records each vendored installation
manifest's source and local SHA-256. Both schema refresh and offline validation
check local hashes. The installation manifests are upstream release bytes;
KubeVirt's desired CR is the documented local customization. Image, privilege,
RBAC and resource changes are expressed through local Kustomize configuration.

| Local infrastructure file | Upstream source | Source SHA-256 | Local SHA-256 |
| --- | --- | --- | --- |
| `metallb/vendor/install.yaml` | [metallb-native.yaml](https://raw.githubusercontent.com/metallb/metallb/v0.16.1/config/manifests/metallb-native.yaml) | `bf25feebb7582ca7df845efd52ffbc2960d6cbf4cfc972f47fded9f788b67f0b` | `bf25feebb7582ca7df845efd52ffbc2960d6cbf4cfc972f47fded9f788b67f0b` |
| `multus/vendor/multus.yaml` | [multus-daemonset-thick.yml](https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/v4.3.1/deployments/multus-daemonset-thick.yml) | `24fb29530b760d28126bba76bd91fac8fd74100b53d9fc65943c223e3a82be30` | `24fb29530b760d28126bba76bd91fac8fd74100b53d9fc65943c223e3a82be30` |
| `kubevirt/vendor/operator.yaml` | [kubevirt-operator.yaml](https://github.com/kubevirt/kubevirt/releases/download/v1.9.0/kubevirt-operator.yaml) | `f11307caafc3c23ffedf9887d8beb5a4419e2694da242fa68f63d1ec820de2e0` | `f11307caafc3c23ffedf9887d8beb5a4419e2694da242fa68f63d1ec820de2e0` |
| `calico/vendor/operator.yaml` | [tigera-operator.yaml](https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml) | `aef423b36aef8cf86567f92bbe5eea4b4ca105a6fc7dbf43de599c6fa70388ba` | `aef423b36aef8cf86567f92bbe5eea4b4ca105a6fc7dbf43de599c6fa70388ba` |
| `calico/vendor/native-v3.yaml` | [v3_projectcalico_org.yaml](https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/v3_projectcalico_org.yaml) | `5306c2c6d9fd6762d804f9da51c049b8269c33498a364c5df0eed555aba026bd` | `5306c2c6d9fd6762d804f9da51c049b8269c33498a364c5df0eed555aba026bd` |
| `kubevirt/kubevirt.yaml` | [kubevirt-cr.yaml](https://github.com/kubevirt/kubevirt/releases/download/v1.9.0/kubevirt-cr.yaml) | `43106136dbce3312bdbfdeae612aacafc6c12da518d233f90645b4685d84a2af` | `c47d09494887ac735dc95ba164a459b6408df855201ecc48c331adc9f9d4f22d` |

MetalLB uses the official v0.16.1 native release manifest. Kustomize overrides
its image references with verified multi-platform image-index digests:

- `quay.io/metallb/controller:v0.16.1@sha256:f51ab515de9ccd20dc3dccb093e48df8adddac019326c456f449e55ba91b6420`
- `quay.io/metallb/speaker:v0.16.1@sha256:16561e96531e1852d5c229ad7fae6e994dcfa983ff7f4de6b6208b34a4e2ddbc`

Multus v4.3.1-thick is also digest-pinned in its Kustomization. Native Calico v3
CRDs and Tigera Operator are the matching Calico 3.33 release pair. Their CRD
ownership and Kubernetes 1.36 admission-policy requirements are documented in
[ARCHITECTURE.md](ARCHITECTURE.md). KubeVirt uses its versioned 1.9.0 API Swagger;
the single UniFi guest uses a restored raw disk in a filesystem PVC.

The twelve rendered chart archives and their dependencies are recorded in
`deployments/homelab/validation/sources.json`. OCI sources use manifest digests;
Git sources use commits. The public chart cache contains source archives and
derived offline charts, without decrypted values or rendered Secrets.

| Helm release | Immutable reference | Chart archive SHA-256 |
| --- | --- | --- |
| `identity/zitadel` | `b05bb603b2ffd0b3284a4b37bad613871bfed94a` | `40b605788f0edf39e987d8328314a697c1bb7449b5f113ae94df4d7f6e3f1c14` |
| `netbird-routing/netbird-operator` | `41d995671f55d790a4f4e1c37da8c9e41a36abee` | `a7e1523a5ad37f6383afbb8b3edc2b63dacd16e21e25810f8f4d2a4d8388dbbe` |
| `cert-manager/cert-manager` | `sha256:15c0b46d9006ce8eb9ff14d1bf54d1bbfcc587bb9e24cd9fe186fb8fec56af1f` | `c27101f3f3e2349fb4a9e704316105bf7b52ad73b8c8257d3498ef7f2f6a4adc` |
| `envoy-gateway-system/envoy-gateway` | `sha256:cfb34ff4266c87a394cd6be5c13607a2dd47083aef771368302eaeaa99c4a0a9` | `4bb4e46f4d13d234b0ce785bee691c821b39ebd6884d80bdd69205bea9939d71` |
| `cnpg-system/barman-cloud` | `b111f4a8eddc6c66bd61524e3bf0ec06387b78ab` | `4288c4fd3dab2776164591c2983424e9050373b37fb18ad97be83dd86a23852b` |
| `cnpg-system/cloudnative-pg` | `d1b5ad60cee2d9432a9cc05627b42a8d8dc7bbae` | `3018d417ca9ed4a55ac703cafcad5eb220e014b33ab6e11a9403301172912227` |
| `services-observability/fluent-bit-collector` | `sha256:123bfa44d8402367138b3ba39d16e74c5fead51a68daad8082388618115aba92` | `27ade6f7f57a414d0c3166ceeb4d8f5094630a917a6f5e6eb7de14903015753e` |
| `services-observability/kube-prometheus-stack` | `sha256:db4805aa51d6566e6b628d71a6445be8a81ecd49701b99928c1a4cffc4132c1a` | `0998b3fae8660cd9ea224caa1c7c4b5d2040d5a02c64e3cdfd3f48d184b50117` |
| `services-observability/loki` | `sha256:7b785f8096f1eb03499d958280d65c634d6ecb5d9942a14d5302d7517d4c9fc4` | `066756e9541507b665da700f3cf489cb990a9fab17b735845a60138a8e5c35fc` |
| `rook-ceph/ceph-csi-drivers` | `29a66b683aa8873001c729b7b120e18604cdb445` | `83741558073367e05dad5594bd8daeafef728fe14dca83c84ce2ba10824ba9ad` |
| `rook-ceph/rook-ceph` | `sha256:df8ebccb66165ff92aedf035cac9cd07eda9a44b92cb8f7f7570a7d7b5f19d84` | `95bd3966bcf36b383b88e1996132642057e8fe4bc133b9681092c4ddec4dd0b2` |
| `velero/velero` | `12.1.0` | `cd23589ad1b2d25cdd3220f6866b3f6f4c5683c4c09494e76a14700b33f81f83` |

The independent snapshot controller and three v1 snapshot CRDs are vendored
from `kubernetes-csi/external-snapshotter` v8.5.0 under the Rook stage. Their five
source files and the controller's immutable image digest are recorded in
`vendors.json`; Kustomize places the controller in `kube-system`. RBD's CSI
`snapshotPolicy` is explicitly `volumeSnapshot`. Offline validation requires
the CRDs, controller and enabled RBD snapshot policy when snapshot classes exist.
The CSI sidecar alone does not supply the cluster controller. The future live
Ceph qualification must complete a snapshot and fresh-PVC restore before
Forgejo's snapshot backup schedule is released.

The schema bundle incorporates official Kubernetes 1.36.4 OpenAPI, the exact
charts' CRDs, the vendored snapshot CRDs and KubeVirt's versioned API. Its
immutable source references and hashes are recorded alongside chart provenance.

ZITADEL's external values-schema reference is localized in a derived chart.
The approved source is commit `817113f21a2643311cbc3e992bb44ffe1c416c54` of
`yannh/kubernetes-json-schema`, SHA-256
`428559f7d50d8624ce29ea144ba079309a025168e8bb7714e954dcb80d50cd9a`.
Original dependency archives stay intact; original/derived schema hashes and
the external source are recorded in `sources.json`. Helm schema validation
remains enabled. See [VALIDATION.md](VALIDATION.md) for reproduction commands
and the limits of offline checks.
