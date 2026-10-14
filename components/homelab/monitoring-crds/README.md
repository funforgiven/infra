Prometheus Operator schemas are installed by the controllers wave before any monitoring custom resources.

Source: `oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack@sha256:db4805aa51d6566e6b628d71a6445be8a81ecd49701b99928c1a4cffc4132c1a`, operator v0.93.0. The downloaded chart SHA-256 is `0998b3fae8660cd9ea224caa1c7c4b5d2040d5a02c64e3cdfd3f48d184b50117`.

The complete ten schemas were decoded using Kubernetes YAML handling and serialized without changing their specifications. Pruning is disabled to preserve custom resource data during upgrades.
