#!/usr/bin/env python3
"""Compare the Omada switch with the repository configuration.

The command only reports changes unless --apply is given. Credentials must be
supplied as SOPS JSON on standard input; they are not printed or stored.
UniFi owns the access points and WLANs, so this adapter manages only the
declared switch networks, port profiles and port assignments.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DESIRED_STATE = REPOSITORY_ROOT / "deployments/homelab/network/omada-network.yaml"
MAX_SECRET_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
HTTP_TIMEOUT = 15.0
POSTFLIGHT_ATTEMPTS = 15
POSTFLIGHT_DELAY = 2.0
READ_CONCURRENCY = 4
PAGE = "page=1&pageSize=1000"
# Port profile fields managed through the Omada API. A spanningTree block also
# manages the edge-port and BPDU settings.
PROFILE_REQUIRED_POLICY_FIELDS = frozenset(
    {
        "poe", "dot1x", "portIsolationEnable", "lldpMedEnable",
        "bandWidthCtrlType", "spanningTreeEnable", "loopbackDetectEnable",
    }
)


class SafeError(RuntimeError):
    """An error that can be printed without exposing credentials."""


@dataclass(frozen=True)
class Credentials:
    api_base: str
    controller_id: str
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class Network:
    name: str
    vlan: int


@dataclass(frozen=True)
class SpanningTreePolicy:
    enabled: bool
    edge_port: bool
    bpdu_protect: bool
    bpdu_filter: bool


@dataclass(frozen=True)
class Profile:
    name: str
    native_vlan: int
    tagged_vlans: tuple[int, ...]
    spanning_tree: SpanningTreePolicy | None


@dataclass(frozen=True)
class Desired:
    site: str
    switch_name: str
    switch_mac: str
    switch_model: str
    profile_template: str
    networks: tuple[Network, ...]
    profiles: tuple[Profile, ...]
    ports: Mapping[int, str]


@dataclass(frozen=True)
class Snapshot:
    site_id: str
    networks_by_vlan: Mapping[int, Mapping[str, Any]]
    network_vlans_by_id: Mapping[str, int]
    profiles_by_name: Mapping[str, Mapping[str, Any]]
    ports: Mapping[int, Mapping[str, Any]]


@dataclass(frozen=True)
class Action:
    domain: str
    target: str
    operation: str
    detail: str

    @property
    def mutates(self) -> bool:
        return self.operation in {"create", "update", "assign"}

    @property
    def blocked(self) -> bool:
        return self.operation == "blocked"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SafeError(f"{label} must be a mapping")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SafeError(f"{label} must be a non-empty string")
    return value.strip()


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SafeError(f"{label} must be an integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SafeError(f"{label} must be a boolean")
    return value


def normalize_mac(value: Any, label: str = "MAC address") -> str:
    compact = _string(value, label).replace(":", "").replace("-", "").upper()
    if len(compact) != 12 or any(character not in "0123456789ABCDEF" for character in compact):
        raise SafeError(f"{label} is invalid")
    return "-".join(compact[index : index + 2] for index in range(0, 12, 2))


def _vlan(value: Any, label: str) -> int:
    vlan = _integer(value, label)
    if not 1 <= vlan <= 4094:
        raise SafeError(f"{label} must be between 1 and 4094")
    return vlan


def load_desired(path: Path = DEFAULT_DESIRED_STATE) -> Desired:
    try:
        root = yaml.safe_load(path.read_text(encoding="utf-8"))
        if (
            root["version"] != 2 or root.get("scope") != "switch-only"
            or "accessPoint" in root or "wireless" in root
        ):
            raise ValueError
        switch = root["switch"]
        networks = tuple(
            Network(str(name), _vlan(vlan, "network VLAN"))
            for name, vlan in switch.get("networks", {}).items()
        )
        profiles = []
        for name, item in switch["profiles"].items():
            spanning_tree_data = item.get("spanningTree")
            spanning_tree = None
            if spanning_tree_data is not None:
                spanning_tree = SpanningTreePolicy(
                    enabled=_boolean(spanning_tree_data["enabled"], "spanning tree enabled"),
                    edge_port=_boolean(spanning_tree_data["edgePort"], "edge port"),
                    bpdu_protect=_boolean(spanning_tree_data["bpduProtect"], "BPDU protect"),
                    bpdu_filter=_boolean(spanning_tree_data["bpduFilter"], "BPDU filter"),
                )
            profiles.append(
                Profile(
                    str(name),
                    _vlan(item["nativeVlan"], "profile VLAN"),
                    tuple(_vlan(vlan, "tagged VLAN") for vlan in item["taggedVlans"]),
                    spanning_tree,
                )
            )
        ports = {int(port): str(profile) for port, profile in switch["ports"].items()}
        if not (
            profiles and ports
            and set(ports.values()).issubset({profile.name for profile in profiles})
            and all(1 <= port <= 65535 for port in ports)
            and len({network.name for network in networks}) == len(networks)
            and len({network.vlan for network in networks}) == len(networks)
            and all(profile.native_vlan not in profile.tagged_vlans
                    and len(profile.tagged_vlans) == len(set(profile.tagged_vlans))
                    for profile in profiles)
        ):
            raise ValueError
        return Desired(
            site=_string(root["site"], "site"),
            switch_name=_string(switch["name"], "switch name"),
            switch_mac=normalize_mac(switch["mac"]),
            switch_model=_string(switch["model"], "switch model"),
            profile_template=_string(switch["profileTemplate"], "profile template"),
            networks=networks, profiles=tuple(profiles), ports=ports,
        )
    except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError, ValueError) as error:
        raise SafeError("Omada desired state is invalid") from error


def _read_secret_document(stream: Any) -> Mapping[str, Any]:
    if hasattr(stream, "isatty") and stream.isatty():
        raise SafeError("SOPS JSON must be piped to standard input")
    payload = stream.read(MAX_SECRET_BYTES + 1)
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SafeError("SOPS JSON is not UTF-8") from error
    if len(payload.encode("utf-8")) > MAX_SECRET_BYTES:
        raise SafeError("SOPS JSON exceeds the size limit")
    try:
        return _mapping(json.loads(payload), "SOPS document")
    except json.JSONDecodeError as error:
        raise SafeError("SOPS JSON is invalid") from error


def _https_origin(value: Any) -> str:
    origin = _string(value, "Omada API base")
    parsed = urllib.parse.urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SafeError("Omada API base must be an HTTPS origin without credentials")
    return origin.rstrip("/")


def credentials_from_document(document: Mapping[str, Any]) -> Credentials:
    omada = _mapping(document.get("omada"), "Omada credentials")
    return Credentials(
        api_base=_https_origin(omada.get("api_base")),
        controller_id=_string(omada.get("id"), "Omada controller ID"),
        client_id=_string(omada.get("client_id"), "Omada client ID"),
        client_secret=_string(omada.get("client_secret"), "Omada client secret"),
    )


def _items(result: Any, label: str) -> list[Mapping[str, Any]]:
    if isinstance(result, list):
        values = result
    elif isinstance(result, Mapping) and isinstance(result.get("data"), list):
        values = result["data"]
        total = result.get("totalRows")
        if isinstance(total, int) and total > len(values):
            raise SafeError(f"Omada {label} exceeds the single-page safety limit")
    else:
        raise SafeError(f"Omada {label} result is not a list")
    return [_mapping(value, f"Omada {label} item") for value in values]


def _index_by(
    values: Sequence[Mapping[str, Any]],
    key: Callable[[Mapping[str, Any]], Any],
    label: str,
) -> dict[Any, Mapping[str, Any]]:
    indexed: dict[Any, Mapping[str, Any]] = {}
    for value in values:
        identity = key(value)
        if identity in indexed:
            raise SafeError(f"Omada {label} identities are duplicated")
        indexed[identity] = value
    return indexed


class OmadaApi:
    """Small secret-safe adapter over the documented Omada OpenAPI."""

    def __init__(
        self, credentials: Credentials, timeout: float = HTTP_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self.credentials = credentials
        self.timeout = timeout
        self.session = session or requests.Session()
        self.token: str | None = None

    def _call(
        self,
        operation: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        authorized: bool = True,
    ) -> Any:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if authorized:
            if self.token is None:
                raise SafeError("Omada authorization has not completed")
            headers["Authorization"] = f"AccessToken={self.token}"
        try:
            response = self.session.request(
                method, f"{self.credentials.api_base}{path}", headers=headers,
                json=body, timeout=self.timeout, verify=True, allow_redirects=False,
            )
        except requests.RequestException as error:
            raise SafeError(f"Omada {operation} transport failed") from error
        if response.status_code != 200:
            raise SafeError(f"Omada {operation} failed with HTTP status {response.status_code}")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise SafeError(f"Omada {operation} response exceeds the size limit")
        try:
            document = _mapping(response.json(), f"Omada {operation} response")
        except ValueError as error:
            raise SafeError(f"Omada {operation} returned invalid JSON") from error
        error_code = document.get("errorCode")
        if isinstance(error_code, bool) or not isinstance(error_code, int):
            raise SafeError(f"Omada {operation} response has no numeric error code")
        if error_code != 0:
            raise SafeError(f"Omada {operation} failed with API error {error_code}")
        return document.get("result")

    def _v1(self, suffix: str) -> str:
        controller = urllib.parse.quote(self.credentials.controller_id, safe="")
        return f"/openapi/v1/{controller}/{suffix}"

    @staticmethod
    def _segment(value: str) -> str:
        return urllib.parse.quote(value, safe="")

    def authorize(self) -> None:
        result = _mapping(
            self._call(
                "authorization",
                "POST",
                "/openapi/authorize/token?grant_type=client_credentials",
                {
                    "omadacId": self.credentials.controller_id,
                    "client_id": self.credentials.client_id,
                    "client_secret": self.credentials.client_secret,
                },
                authorized=False,
            ),
            "Omada authorization result",
        )
        self.token = _string(result.get("accessToken"), "Omada access token")

    def read(self, resource: str, *values: str) -> Any:
        quoted = (*[self._segment(value) for value in values], "")
        routes = {
            "sites": ("site inventory", self._v1("sites")),
            "devices": ("device inventory", self._v1(f"sites/{quoted[0]}/devices")),
            "networks": ("LAN network inventory", self._v1(f"sites/{quoted[0]}/lan-networks")),
            "profiles": ("LAN profile inventory", self._v1(f"sites/{quoted[0]}/lan-profiles")),
            "ports": ("switch port inventory", self._v1(f"sites/{quoted[0]}/switches/ports/overview")),
        }
        if resource not in routes:
            raise SafeError("internal Omada read resource is invalid")
        operation, path = routes[resource]
        return _items(self._call(operation, "GET", f"{path}?{PAGE}"), operation)

    def write(self, resource: str, values: Sequence[str], payload: Mapping[str, Any]) -> None:
        quoted = (*[self._segment(value) for value in values], "", "", "")
        controller = urllib.parse.quote(self.credentials.controller_id, safe="")
        routes = {
            "network-create": (
                "LAN network creation", "POST",
                f"/openapi/v2/{controller}/sites/{quoted[0]}/lan-networks",
            ),
            "network-update": (
                "LAN network update", "PATCH",
                f"/openapi/v2/{controller}/sites/{quoted[0]}/lan-networks/{quoted[1]}",
            ),
            "profile-create": ("LAN profile creation", "POST", self._v1(f"sites/{quoted[0]}/lan-profiles")),
            "profile-update": ("LAN profile update", "PATCH", self._v1(f"sites/{quoted[0]}/lan-profiles/{quoted[1]}")),
            "port-assign": ("switch port assignment", "PATCH", self._v1(f"sites/{quoted[0]}/switches/{quoted[1]}/ports/{quoted[2]}")),
        }
        if resource not in routes:
            raise SafeError("internal Omada write resource is invalid")
        operation, method, path = routes[resource]
        self._call(operation, method, path, payload)


def _profile_id(profile: Mapping[str, Any]) -> str:
    return _string(profile.get("id"), "profile ID")


def _network_payload(network: Network) -> dict[str, Any]:
    return {
        "name": network.name,
        "purpose": 0,
        "vlan": network.vlan,
        "application": 1,
        "allLan": True,
        "igmpSnoopEnable": False,
    }


def _one_device(devices: Sequence[Mapping[str, Any]], mac: str, label: str) -> Mapping[str, Any]:
    matches = []
    for device in devices:
        try:
            if normalize_mac(device.get("mac"), f"{label} MAC") == mac:
                matches.append(device)
        except SafeError:
            continue
    if len(matches) != 1:
        raise SafeError(f"the exact {label} is missing or ambiguous")
    return matches[0]


def _read_networks(api: OmadaApi, site_id: str) -> dict[str, Any]:
    networks = _index_by(
        api.read("networks", site_id),
        lambda item: _integer(item.get("vlan"), "network VLAN"),
        "LAN network",
    )
    networks_by_id = _index_by(
        list(networks.values()),
        lambda item: _string(item.get("id"), "network ID"),
        "LAN network",
    )
    return {
        "networks_by_vlan": networks,
        "network_vlans_by_id": {
            network_id: _integer(network.get("vlan"), "network VLAN")
            for network_id, network in networks_by_id.items()
        },
    }


def _read_profiles(api: OmadaApi, site_id: str) -> dict[str, Any]:
    profiles = _index_by(
        api.read("profiles", site_id),
        lambda item: _string(item.get("name"), "profile name"),
        "profile",
    )
    _index_by(list(profiles.values()), _profile_id, "profile")
    return {"profiles_by_name": profiles}


def _read_ports(api: OmadaApi, site_id: str, desired: Desired) -> dict[str, Any]:
    ports: dict[int, Mapping[str, Any]] = {}
    for port in api.read("ports", site_id):
        try:
            port_mac = normalize_mac(port.get("switchMac"))
        except SafeError:
            continue
        if port_mac != desired.switch_mac:
            continue
        number = _integer(port.get("port"), "switch port")
        if number in ports:
            raise SafeError("Omada switch port identities are duplicated")
        if port.get("switchName") != desired.switch_name:
            raise SafeError("switch port inventory belongs to another switch")
        ports[number] = port
    if not set(desired.ports).issubset(ports):
        raise SafeError("one or more declared switch ports are absent")
    return {"ports": ports}


# Reads that refresh one planning domain while apply waits for it to settle.
DOMAIN_READERS: Mapping[str, Callable[[OmadaApi, str], dict[str, Any]]] = {
    "network": _read_networks,
    "profile": _read_profiles,
}


def inspect(api: OmadaApi, desired: Desired) -> Snapshot:
    sites = [site for site in api.read("sites") if site.get("name") == desired.site]
    if len(sites) != 1:
        raise SafeError("the exact Omada site is missing or ambiguous")
    site_id = _string(sites[0].get("siteId"), "site ID")

    # Every read depends only on the site and declared identities, so they are
    # fetched concurrently. The switch identity is checked first so it stays
    # the first reported failure.
    with ThreadPoolExecutor(max_workers=READ_CONCURRENCY) as executor:
        devices = executor.submit(api.read, "devices", site_id)
        networks = executor.submit(_read_networks, api, site_id)
        profiles = executor.submit(_read_profiles, api, site_id)
        ports = executor.submit(_read_ports, api, site_id, desired)
        switch = _one_device(devices.result(), desired.switch_mac, "switch")
        if (
            (switch.get("name"), switch.get("model"), str(switch.get("type", "")).lower())
            != (desired.switch_name, desired.switch_model, "switch")
        ):
            raise SafeError("the exact switch identity differs from Git")
        return Snapshot(
            site_id=site_id, **networks.result(), **profiles.result(), **ports.result(),
        )


def _profile_signature(profile: Mapping[str, Any], snapshot: Snapshot) -> tuple[int, tuple[int, ...], tuple[int, ...], int | None]:
    native_id = _string(profile.get("nativeNetworkId"), "profile native network")
    tagged_ids = profile.get("tagNetworkIds")
    untagged_ids = profile.get("untagNetworkIds")
    if not isinstance(tagged_ids, list) or not isinstance(untagged_ids, list):
        raise SafeError("profile network membership is invalid")
    ids = [native_id, *tagged_ids, *untagged_ids]
    if not all(isinstance(item, str) and item in snapshot.network_vlans_by_id for item in ids):
        raise SafeError("profile references an unknown LAN network")
    voice_id = profile.get("voiceNetworkId")
    voice = None if voice_id in (None, "") else snapshot.network_vlans_by_id.get(voice_id)
    if voice_id not in (None, "") and voice is None:
        raise SafeError("profile references an unknown voice network")
    return (
        snapshot.network_vlans_by_id[native_id],
        tuple(sorted(snapshot.network_vlans_by_id[item] for item in tagged_ids)),
        tuple(sorted(snapshot.network_vlans_by_id[item] for item in untagged_ids)),
        voice,
    )


def _spanning_tree_matches(profile: Mapping[str, Any], desired: Profile) -> bool:
    policy = desired.spanning_tree
    if policy is None:
        return True
    setting = profile.get("spanningTreeSetting")
    return (
        isinstance(setting, Mapping)
        and profile.get("spanningTreeEnable") is policy.enabled
        and setting.get("edgePort") is policy.edge_port
        and setting.get("bpduProtect") is policy.bpdu_protect
        and setting.get("bpduFilter") is policy.bpdu_filter
    )


def _profile_payload(source: Mapping[str, Any], desired: Profile, snapshot: Snapshot) -> dict[str, Any]:
    if not PROFILE_REQUIRED_POLICY_FIELDS.issubset(source):
        raise SafeError("the Omada profile template lacks required policy fields")
    missing_vlans = {desired.native_vlan, *desired.tagged_vlans} - set(snapshot.networks_by_vlan)
    if missing_vlans:
        raise SafeError("a desired profile references a missing LAN network")
    payload = {field: source[field] for field in PROFILE_REQUIRED_POLICY_FIELDS}
    if "spanningTreeSetting" in source:
        payload["spanningTreeSetting"] = copy.deepcopy(source["spanningTreeSetting"])
    if desired.spanning_tree is not None:
        setting = payload.get("spanningTreeSetting")
        if not isinstance(setting, dict):
            raise SafeError("the Omada profile template lacks spanning-tree settings")
        payload["spanningTreeEnable"] = desired.spanning_tree.enabled
        setting.update(
            {
                "edgePort": desired.spanning_tree.edge_port,
                "bpduProtect": desired.spanning_tree.bpdu_protect,
                "bpduFilter": desired.spanning_tree.bpdu_filter,
            }
        )
    native_id = _string(snapshot.networks_by_vlan[desired.native_vlan].get("id"), "network ID")
    payload.update(
        {
            "name": desired.name,
            "nativeNetworkId": native_id,
            "tagNetworkIds": [
                _string(snapshot.networks_by_vlan[vlan].get("id"), "network ID")
                for vlan in desired.tagged_vlans
            ],
            "untagNetworkIds": [native_id],
        }
    )
    return payload


def make_plan(desired: Desired, snapshot: Snapshot) -> tuple[Action, ...]:
    actions: list[Action] = []
    desired_network_vlans = {network.vlan for network in desired.networks}
    desired_network_names = {network.name for network in desired.networks}
    for network in desired.networks:
        actual = snapshot.networks_by_vlan.get(network.vlan)
        same_name = [
            item for item in snapshot.networks_by_vlan.values()
            if item.get("name") == network.name
        ]
        if actual is None and same_name:
            operation, detail = "blocked", "network name exists on another VLAN"
        elif actual is None:
            operation, detail = "create", f"create switch-only VLAN {network.vlan}"
        elif all(actual.get(key) == value for key, value in _network_payload(network).items()):
            operation, detail = "noop", "switch-only VLAN matches"
        elif actual.get("name") in desired_network_names:
            operation, detail = "update", "switch-only VLAN differs"
        else:
            operation, detail = "blocked", "VLAN is owned by another LAN network"
        actions.append(Action("network", network.name, operation, detail))

    profile_names = {profile.name for profile in desired.profiles}
    for profile in desired.profiles:
        missing = (
            {profile.native_vlan, *profile.tagged_vlans}
            - set(snapshot.networks_by_vlan)
            - desired_network_vlans
        )
        actual = snapshot.profiles_by_name.get(profile.name)
        if missing:
            operation, detail = "blocked", f"LAN networks are missing VLANs {sorted(missing)}"
        elif actual is None:
            operation = "create" if desired.profile_template in snapshot.profiles_by_name else "blocked"
            detail = "create from the declared template" if operation == "create" else "profile template is absent"
        elif (
            _profile_signature(actual, snapshot)
            == (profile.native_vlan, tuple(sorted(profile.tagged_vlans)), (profile.native_vlan,), None)
            and _spanning_tree_matches(actual, profile)
        ):
            operation, detail = "noop", "VLAN membership and declared policy match"
        else:
            operation, detail = "update", "VLAN membership or declared policy differs"
        actions.append(Action("profile", profile.name, operation, detail))

    for port, profile_name in desired.ports.items():
        actual_profile = snapshot.profiles_by_name.get(profile_name)
        current = snapshot.ports[port]
        if current.get("profileOverrideEnable") is not False:
            operation, detail = "blocked", "profile override is enabled"
        elif actual_profile is None:
            operation = "assign" if profile_name in profile_names else "blocked"
            detail = f"assign {profile_name} after profile creation"
        elif current.get("profileId") == _profile_id(actual_profile) and current.get("profileName") == profile_name:
            operation, detail = "noop", f"uses {profile_name}"
        else:
            operation, detail = "assign", f"assign {profile_name}"
        actions.append(Action("port", str(port), operation, detail))

    return tuple(actions)


def _wait(
    api: OmadaApi,
    desired: Desired,
    snapshot: Snapshot,
    domain: str | None,
    attempts: int,
    delay: float,
    sleeper: Callable[[float], None],
) -> Snapshot:
    """Poll until every action (or only DOMAIN's actions) is a no-op.

    With a domain, only that domain's resources are re-read and merged into
    SNAPSHOT; otherwise the whole controller state is inspected again.
    """
    for attempt in range(attempts):
        try:
            if domain is None:
                current = inspect(api, desired)
            else:
                current = replace(snapshot, **DOMAIN_READERS[domain](api, snapshot.site_id))
            if all(
                action.operation == "noop" for action in make_plan(desired, current)
                if domain is None or action.domain == domain
            ):
                return current
        except SafeError:
            pass
        if attempt + 1 < attempts:
            sleeper(delay)
    raise SafeError("Omada did not match the requested configuration after applying changes")


def apply(
    api: OmadaApi,
    desired: Desired,
    snapshot: Snapshot,
    actions: Sequence[Action],
    *,
    attempts: int = POSTFLIGHT_ATTEMPTS,
    delay: float = POSTFLIGHT_DELAY,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    if any(action.blocked for action in actions):
        raise SafeError("apply refused because the plan contains blockers")

    networks = [action for action in actions if action.domain == "network" and action.mutates]
    desired_networks = {network.name: network for network in desired.networks}
    for action in networks:
        current = snapshot.networks_by_vlan.get(desired_networks[action.target].vlan)
        values = (snapshot.site_id,)
        if action.operation == "create":
            resource = "network-create"
        else:
            if current is None:
                raise SafeError("LAN network disappeared before apply")
            resource, values = "network-update", (
                *values, _string(current.get("id"), "network ID")
            )
        api.write(resource, values, _network_payload(desired_networks[action.target]))

    if networks:
        snapshot = _wait(api, desired, snapshot, "network", attempts, delay, sleeper)
        actions = make_plan(desired, snapshot)
        if any(action.blocked for action in actions):
            raise SafeError("apply became blocked after LAN network reconciliation")

    profiles = [action for action in actions if action.domain == "profile" and action.mutates]
    desired_profiles = {profile.name: profile for profile in desired.profiles}
    template = snapshot.profiles_by_name.get(desired.profile_template)
    profile_payloads = {}
    for action in profiles:
        current = snapshot.profiles_by_name.get(action.target)
        source = current or template
        if source is None:
            raise SafeError("profile template disappeared before apply")
        profile_payloads[action.target] = _profile_payload(
            source, desired_profiles[action.target], snapshot
        )

    for action in profiles:
        current = snapshot.profiles_by_name.get(action.target)
        values = (snapshot.site_id,)
        if action.operation == "create":
            resource = "profile-create"
        else:
            if current is None:
                raise SafeError("profile disappeared before apply")
            resource, values = "profile-update", (*values, _profile_id(current))
        api.write(resource, values, profile_payloads[action.target])

    if profiles:
        snapshot = _wait(api, desired, snapshot, "profile", attempts, delay, sleeper)

    ports = [action for action in make_plan(desired, snapshot) if action.domain == "port"]
    if any(action.blocked for action in ports):
        raise SafeError("port assignment became blocked during apply")
    ports = [action for action in ports if action.mutates]
    for action in ports:
        profile_name = desired.ports[int(action.target)]
        profile = snapshot.profiles_by_name.get(profile_name)
        if profile is None:
            raise SafeError("desired profile disappeared before port assignment")
        port = snapshot.ports[int(action.target)]
        # The controller's profile-only PUT currently fails name validation.
        # PATCH preserves the port's physical settings while following the
        # selected profile for both general policy and VLAN membership.
        payload = {
            "name": _string(port.get("portName"), "port name"),
            "profileId": _profile_id(profile),
            "profileOverrideEnable": False,
            "profileVlanOverrideEnable": False,
            "linkSpeed": _integer(port.get("linkSpeed"), "port speed"),
            "duplex": _integer(port.get("duplex"), "port duplex"),
            "tagIds": port.get("tagIds", []),
        }
        api.write(
            "port-assign", (snapshot.site_id, desired.switch_mac, action.target),
            payload,
        )

    _wait(api, desired, snapshot, None, attempts, delay, sleeper)
    return len(networks) + len(profiles) + len(ports)


def render(actions: Sequence[Action]) -> None:
    print("Connected to the configured Omada site and switch")
    for action in actions:
        print(f"  {action.domain} {action.target}: {action.operation} - {action.detail}")
    print(
        f"Summary: {sum(action.mutates for action in actions)} change(s), "
        f"{sum(action.blocked for action in actions)} blocker(s)"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--desired",
        type=Path,
        default=DEFAULT_DESIRED_STATE,
        help="desired-state YAML file",
    )
    parser.add_argument(
        "--credentials-stdin",
        action="store_true",
        help="read credentials as SOPS JSON from standard input",
    )
    parser.add_argument("--apply", action="store_true", help="make the planned changes")
    args = parser.parse_args(argv)
    if not args.credentials_stdin:
        parser.error("--credentials-stdin is required")
    return args


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: Any = sys.stdin,
    api_factory: Callable[[Credentials], OmadaApi] | None = None,
) -> int:
    args = parse_args(argv)
    desired = load_desired(args.desired)
    credentials = credentials_from_document(_read_secret_document(stdin))
    api = (api_factory or OmadaApi)(credentials)
    api.authorize()
    snapshot = inspect(api, desired)
    actions = make_plan(desired, snapshot)
    render(actions)
    if not args.apply:
        print("Read-only plan complete; no changes were made")
        return 0
    mutations = apply(api, desired, snapshot, actions)
    print(f"Verified controller state after {mutations} change(s)")
    return 0


def main() -> int:
    try:
        return run()
    except SafeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
