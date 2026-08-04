#!/usr/bin/env python3
"""Plan or apply the active Git-declared Omada configuration.

The default is read-only. Secrets are accepted only as one bounded SOPS JSON
document on standard input and are never printed, persisted, or accepted in
arguments or environment variables.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DESIRED_STATE = REPOSITORY_ROOT / "deployments/homelab/cloud/omada-network.yaml"
MAX_SECRET_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
HTTP_TIMEOUT = 15.0
POSTFLIGHT_ATTEMPTS = 15
POSTFLIGHT_DELAY = 2.0
PAGE = "page=1&pageSize=1000"
BANDS = {"2.4GHz": 1, "dual": 3}
# Required policy fields documented by Omada OpenAPI. Network membership is
# the only profile behavior this reconciler owns.
PROFILE_REQUIRED_POLICY_FIELDS = frozenset(
    {
        "poe", "dot1x", "portIsolationEnable", "lldpMedEnable",
        "bandWidthCtrlType", "spanningTreeEnable", "loopbackDetectEnable",
    }
)


class SafeError(RuntimeError):
    """An operator-facing error guaranteed not to contain secret material."""


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
class Profile:
    name: str
    native_vlan: int
    tagged_vlans: tuple[int, ...]


@dataclass(frozen=True)
class Ssid:
    name: str
    band: int
    vlan: int
    psk_ref: str


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
    ap_name: str
    ap_mac: str
    ap_model: str
    ap_address: str
    ap_netmask: str
    ap_gateway: str
    ap_dns: str
    ap_port: int
    wlan_group: str
    ssids: tuple[Ssid, ...]


@dataclass(frozen=True)
class Snapshot:
    site_id: str
    networks_by_vlan: Mapping[int, Mapping[str, Any]]
    network_vlans_by_id: Mapping[str, int]
    profiles_by_name: Mapping[str, Mapping[str, Any]]
    ports: Mapping[int, Mapping[str, Any]]
    wlan_id: str
    ssid_ids: Mapping[str, str]
    ssid_details: Mapping[str, Mapping[str, Any]]
    ap_ready: bool
    unexpected_ssids: tuple[str, ...]


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
        if root["version"] != 1 or root["wireless"]["policy"] != "standard":
            raise ValueError
        switch, ap, wireless = root["switch"], root["accessPoint"], root["wireless"]
        networks = tuple(
            Network(str(name), _vlan(vlan, "network VLAN"))
            for name, vlan in switch.get("networks", {}).items()
        )
        profiles = tuple(
            Profile(str(name), _vlan(item["nativeVlan"], "profile VLAN"),
                    tuple(_vlan(vlan, "tagged VLAN") for vlan in item["taggedVlans"]))
            for name, item in switch["profiles"].items()
        )
        ports = {int(port): str(profile) for port, profile in switch["ports"].items()}
        interface = ipaddress.IPv4Interface(ap["address"])
        gateway, dns = ipaddress.IPv4Address(ap["gateway"]), ipaddress.IPv4Address(ap["dns"])
        ssids = tuple(
            Ssid(str(item["name"]), BANDS[item["band"]], _vlan(item["vlan"], "SSID VLAN"),
                 str(item["pskSecretRef"]))
            for item in wireless["ssids"]
        )
        desired = Desired(
            site=str(root["site"]), switch_name=str(switch["name"]),
            switch_mac=normalize_mac(switch["mac"]), switch_model=str(switch["model"]),
            profile_template=str(switch["profileTemplate"]), networks=networks,
            profiles=profiles, ports=ports,
            ap_name=str(ap["name"]), ap_mac=normalize_mac(ap["mac"]),
            ap_model=str(ap["model"]), ap_address=str(interface.ip),
            ap_netmask=str(interface.netmask), ap_gateway=str(gateway), ap_dns=str(dns),
            ap_port=int(ap["switchPort"]), wlan_group=str(wireless["group"]), ssids=ssids,
        )
        profile_map = {profile.name: profile for profile in profiles}
        ap_profile = profile_map[ports[desired.ap_port]]
        valid = (
            profiles and ports and ssids and ap["managementVlanMode"] == "default"
            and ap_profile.native_vlan == _vlan(ap["managementVlan"], "AP VLAN")
            and {ssid.vlan for ssid in ssids} == set(ap_profile.tagged_vlans)
            and gateway in interface.network and dns in interface.network
            and len({network.name for network in networks}) == len(networks)
            and len({network.vlan for network in networks}) == len(networks)
            and all(profile.native_vlan not in profile.tagged_vlans
                    and len(profile.tagged_vlans) == len(set(profile.tagged_vlans))
                    for profile in profiles)
            and set(ports.values()).issubset(profile_map)
            and len({ssid.name for ssid in ssids}) == len(ssids)
            and len({ssid.psk_ref for ssid in ssids}) == len(ssids)
        )
        if not valid:
            raise ValueError
        return desired
    except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError, ValueError,
            ipaddress.AddressValueError, ipaddress.NetmaskValueError) as error:
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


def _secret(document: Mapping[str, Any], reference: str) -> str:
    value: Any = document
    for part in reference.split("."):
        value = _mapping(value, "wireless secret parent").get(part)
    secret = _string(value, "wireless PSK")
    if not 8 <= len(secret) <= 63 or any(not 0x20 <= ord(character) <= 0x7E for character in secret):
        raise SafeError("a wireless PSK violates the Omada constraints")
    return secret


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
        quoted = (*[self._segment(value) for value in values], "", "", "")
        controller = urllib.parse.quote(self.credentials.controller_id, safe="")
        routes = {
            "sites": ("site inventory", self._v1("sites"), True),
            "devices": ("device inventory", self._v1(f"sites/{quoted[0]}/devices"), True),
            "ap": ("AP detail", self._v1(f"sites/{quoted[0]}/aps/{quoted[1]}"), False),
            "ap-ip": ("AP IP inventory", self._v1(f"sites/{quoted[0]}/aps/{quoted[1]}/ip-setting"), False),
            "ap-vlan": ("AP VLAN inventory", f"/openapi/v2/{controller}/sites/{quoted[0]}/aps/{quoted[1]}/vlan", False),
            "networks": ("LAN network inventory", self._v1(f"sites/{quoted[0]}/lan-networks"), True),
            "profiles": ("LAN profile inventory", self._v1(f"sites/{quoted[0]}/lan-profiles"), True),
            "ports": ("switch port inventory", self._v1(f"sites/{quoted[0]}/switches/ports/overview"), True),
            "wlan-groups": ("WLAN group inventory", self._v1(f"sites/{quoted[0]}/wireless-network/wlans"), True),
            "ssids": ("SSID inventory", self._v1(f"sites/{quoted[0]}/wireless-network/wlans/{quoted[1]}/ssids"), True),
            "ssid": ("SSID detail", self._v1(f"sites/{quoted[0]}/wireless-network/wlans/{quoted[1]}/ssids/{quoted[2]}"), False),
        }
        if resource not in routes:
            raise SafeError("internal Omada read resource is invalid")
        operation, path, listed = routes[resource]
        result = self._call(operation, "GET", f"{path}?{PAGE}" if listed and resource != "wlan-groups" else path)
        return _items(result, operation) if listed else _mapping(result, operation)

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
            "port-assign": ("switch port assignment", "PUT", self._v1(f"sites/{quoted[0]}/switches/{quoted[1]}/ports/{quoted[2]}/profile")),
            "ssid-create": ("SSID creation", "POST", self._v1(f"sites/{quoted[0]}/wireless-network/wlans/{quoted[1]}/ssids")),
            "ssid-update": ("SSID update", "PATCH", self._v1(f"sites/{quoted[0]}/wireless-network/wlans/{quoted[1]}/ssids/{quoted[2]}/update-basic-config")),
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


def inspect(api: OmadaApi, desired: Desired) -> Snapshot:
    sites = [site for site in api.read("sites") if site.get("name") == desired.site]
    if len(sites) != 1:
        raise SafeError("the exact Omada site is missing or ambiguous")
    site_id = _string(sites[0].get("siteId"), "site ID")
    devices = api.read("devices", site_id)
    switch, ap = (_one_device(devices, mac, label) for mac, label in (
        (desired.switch_mac, "switch"), (desired.ap_mac, "access point")
    ))
    if (
        (switch.get("name"), switch.get("model"), str(switch.get("type", "")).lower())
        != (desired.switch_name, desired.switch_model, "switch")
    ):
        raise SafeError("the exact switch identity differs from Git")
    if (
        (ap.get("name"), ap.get("model"), str(ap.get("type", "")).lower(),
         ap.get("status"), ap.get("detailStatus"))
        != (desired.ap_name, desired.ap_model, "ap", 1, 14)
    ):
        raise SafeError("the exact access-point identity or health differs from Git")
    ap_detail = api.read("ap", site_id, desired.ap_mac)
    if (
        (normalize_mac(ap_detail.get("mac")), ap_detail.get("name"),
         str(ap_detail.get("type", "")).lower())
        != (desired.ap_mac, desired.ap_name, "ap")
    ):
        raise SafeError("the exact access-point detail identity differs from Git")

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
    vlan_by_id = {
        network_id: _integer(network.get("vlan"), "network VLAN")
        for network_id, network in networks_by_id.items()
    }
    profiles = _index_by(
        api.read("profiles", site_id),
        lambda item: _string(item.get("name"), "profile name"),
        "profile",
    )
    _index_by(list(profiles.values()), _profile_id, "profile")

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

    groups = [group for group in api.read("wlan-groups", site_id)
              if group.get("name") == desired.wlan_group]
    if len(groups) != 1:
        raise SafeError("the exact WLAN group is missing or ambiguous")
    wlan_id = _string(groups[0].get("wlanId"), "WLAN group ID")
    summaries = _index_by(
        api.read("ssids", site_id, wlan_id),
        lambda item: _string(item.get("name"), "SSID name"),
        "SSID",
    )
    _index_by(list(summaries.values()), lambda item: _string(item.get("ssidId"), "SSID ID"), "SSID")
    ssid_ids = {name: _string(summary.get("ssidId"), "SSID ID") for name, summary in summaries.items()}
    desired_names = {ssid.name for ssid in desired.ssids}
    details = {
        name: api.read("ssid", site_id, wlan_id, ssid_id)
        for name, ssid_id in ssid_ids.items()
        if name in desired_names
    }
    ap_ip = api.read("ap-ip", site_id, desired.ap_mac)
    ap_vlan = api.read("ap-vlan", site_id, desired.ap_mac)
    static = ap_ip.get("staticIpSetting")
    mvlan = ap_vlan.get("mvlanSetting")
    ap_ready = (
        ap.get("ip") == desired.ap_address
        and ap_detail.get("ip") == desired.ap_address
        and ap_ip.get("mode") == "static"
        and isinstance(static, Mapping)
        and (
            static.get("configIp"), static.get("configMask"),
            static.get("configGate"), static.get("preferredDNS"),
            static.get("alternateDNS", ""),
        ) == (
            desired.ap_address, desired.ap_netmask, desired.ap_gateway,
            desired.ap_dns, "",
        )
        and isinstance(mvlan, Mapping)
        and mvlan.get("mode") == 0
    )
    return Snapshot(
        site_id=site_id,
        networks_by_vlan=networks,
        network_vlans_by_id=vlan_by_id,
        profiles_by_name=profiles,
        ports=ports,
        wlan_id=wlan_id,
        ssid_ids=ssid_ids,
        ssid_details=details,
        ap_ready=ap_ready,
        unexpected_ssids=tuple(sorted(set(ssid_ids) - desired_names)),
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


def _profile_payload(source: Mapping[str, Any], desired: Profile, snapshot: Snapshot) -> dict[str, Any]:
    if not PROFILE_REQUIRED_POLICY_FIELDS.issubset(source):
        raise SafeError("the Omada profile template lacks required policy fields")
    missing_vlans = {desired.native_vlan, *desired.tagged_vlans} - set(snapshot.networks_by_vlan)
    if missing_vlans:
        raise SafeError("a desired profile references a missing LAN network")
    payload = {field: source[field] for field in PROFILE_REQUIRED_POLICY_FIELDS}
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


def _ssid_fields(ssid: Ssid) -> dict[str, Any]:
    return {
        "name": ssid.name,
        "deviceType": 1,
        "band": ssid.band,
        "guestNetEnable": False,
        "security": 3,
        "broadcast": True,
        "vlanEnable": True,
        "vlanId": ssid.vlan,
        "pskSetting": {
            "versionPsk": 2,
            "encryptionPsk": 3,
            "gikRekeyPskEnable": True,
            "rekeyPskInterval": 3600,
            "intervalPskType": 0,
        },
        "mloEnable": False,
        "pmfMode": 3,
        "enable11r": False,
        "hidePwd": True,
        "greEnable": False,
        "prohibitWifiShare": False,
    }


def _ssid_matches(ssid: Ssid, detail: Mapping[str, Any]) -> bool:
    expected = _ssid_fields(ssid)
    psk = expected.pop("pskSetting")
    hide_password = expected.pop("hidePwd")
    gre = expected.pop("greEnable")
    actual_psk = detail.get("pskSetting")
    readable = all(detail.get(key) == value for key, value in expected.items())
    return (
        readable and isinstance(actual_psk, Mapping)
        and all(actual_psk.get(key) == value for key, value in psk.items())
        and detail.get("hidePwd", hide_password) is hide_password
        and detail.get("greEnable", gre) is gre
    )


def _ssid_payload(ssid: Ssid, psk: str, *, create: bool) -> dict[str, Any]:
    payload = _ssid_fields(ssid)
    payload["pskSetting"]["securityKey"] = psk
    if not create:
        payload.pop("deviceType")
    return payload


def make_plan(desired: Desired, snapshot: Snapshot, *, include_write_only: bool = False) -> tuple[Action, ...]:
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
        elif _profile_signature(actual, snapshot) == (
            profile.native_vlan, tuple(sorted(profile.tagged_vlans)), (profile.native_vlan,), None
        ):
            operation, detail = "noop", "VLAN membership matches"
        else:
            operation, detail = "update", "VLAN membership differs"
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

    actions.append(Action(
        "access-point", desired.ap_name, "noop" if snapshot.ap_ready else "blocked",
        "final static management state matches" if snapshot.ap_ready
        else "management state differs; use the adoption runbook",
    ))

    if snapshot.unexpected_ssids:
        actions.append(Action("wireless", "SSID set", "blocked", "undeclared SSIDs exist"))
    for ssid in desired.ssids:
        detail = snapshot.ssid_details.get(ssid.name)
        if detail is None:
            operation, reason = "create", "SSID is absent"
        elif detail.get("deviceType") != 1:
            operation, reason = "blocked", "device scope cannot be updated safely"
        elif not _ssid_matches(ssid, detail):
            operation, reason = "update", "readable settings differ"
        elif include_write_only:
            operation, reason = "update", "explicitly rewrite the write-only PSK"
        else:
            operation, reason = "noop", "readable settings match; PSK is write-only"
        actions.append(Action("wireless", ssid.name, operation, reason))
    return tuple(actions)


def _wait(
    api: OmadaApi,
    desired: Desired,
    predicate: Callable[[tuple[Action, ...]], bool],
    attempts: int,
    delay: float,
    sleeper: Callable[[float], None],
) -> Snapshot:
    for attempt in range(attempts):
        try:
            snapshot = inspect(api, desired)
            if predicate(make_plan(desired, snapshot)):
                return snapshot
        except SafeError:
            pass
        if attempt + 1 < attempts:
            sleeper(delay)
    raise SafeError("Omada mutations did not reach semantic readiness")


def apply(
    api: OmadaApi,
    desired: Desired,
    snapshot: Snapshot,
    actions: Sequence[Action],
    secret_document: Mapping[str, Any],
    *,
    include_write_only: bool,
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
        snapshot = _wait(
            api, desired,
            lambda plan: all(
                action.operation == "noop" for action in plan
                if action.domain == "network"
            ),
            attempts, delay, sleeper,
        )
        actions = make_plan(desired, snapshot, include_write_only=include_write_only)
        if any(action.blocked for action in actions):
            raise SafeError("apply became blocked after LAN network reconciliation")

    wireless = [action for action in actions if action.domain == "wireless" and action.mutates]
    if wireless and not include_write_only:
        raise SafeError("wireless changes require explicit --include-write-only")

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

    desired_ssids = {ssid.name: ssid for ssid in desired.ssids}
    ssid_payloads = {
        action.target: _ssid_payload(
            desired_ssids[action.target],
            _secret(secret_document, desired_ssids[action.target].psk_ref),
            create=action.operation == "create",
        )
        for action in wireless
    }

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
        snapshot = _wait(
            api, desired,
            lambda plan: all(action.operation == "noop" for action in plan if action.domain == "profile"),
            attempts, delay, sleeper,
        )

    ports = [action for action in make_plan(desired, snapshot) if action.domain == "port"]
    if any(action.blocked for action in ports):
        raise SafeError("port assignment became blocked during apply")
    ports = [action for action in ports if action.mutates]
    for action in ports:
        profile_name = desired.ports[int(action.target)]
        profile = snapshot.profiles_by_name.get(profile_name)
        if profile is None:
            raise SafeError("desired profile disappeared before port assignment")
        api.write(
            "port-assign", (snapshot.site_id, desired.switch_mac, action.target),
            {"profileId": _profile_id(profile)},
        )

    for action in wireless:
        ssid_id = snapshot.ssid_ids.get(action.target)
        values = (snapshot.site_id, snapshot.wlan_id)
        if action.operation == "create":
            resource = "ssid-create"
        else:
            if ssid_id is None:
                raise SafeError("SSID disappeared before apply")
            resource, values = "ssid-update", (*values, ssid_id)
        api.write(resource, values, ssid_payloads[action.target])

    _wait(
        api, desired,
        lambda plan: all(action.operation == "noop" for action in plan),
        attempts, delay, sleeper,
    )
    return len(networks) + len(profiles) + len(ports) + len(wireless)


def render(actions: Sequence[Action]) -> None:
    print("Omada identity preflight: exact site, switch, and access point verified")
    for action in actions:
        suffix = " (requires write-only PSK)" if action.domain == "wireless" and action.mutates else ""
        print(f"  {action.domain} {action.target}: {action.operation} - {action.detail}{suffix}")
    print(
        f"Summary: {sum(action.mutates for action in actions)} mutation(s), "
        f"{sum(action.blocked for action in actions)} blocker(s)"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desired", type=Path, default=DEFAULT_DESIRED_STATE)
    parser.add_argument("--credentials-stdin", action="store_true", help="read SOPS JSON from stdin")
    parser.add_argument("--apply", action="store_true", help="apply the reviewed plan")
    parser.add_argument(
        "--include-write-only",
        action="store_true",
        help="include SSID PSKs in the plan; required for SSID create/update/rotation",
    )
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
    secret_document = _read_secret_document(stdin)
    credentials = credentials_from_document(secret_document)
    api = (api_factory or OmadaApi)(credentials)
    api.authorize()
    snapshot = inspect(api, desired)
    actions = make_plan(desired, snapshot, include_write_only=args.include_write_only)
    render(actions)
    if not args.apply:
        print("Read-only plan complete; no controller mutation was requested")
        return 0
    mutations = apply(
        api,
        desired,
        snapshot,
        actions,
        secret_document,
        include_write_only=args.include_write_only,
    )
    print(f"Semantic postflight passed after {mutations} mutation(s)")
    return 0


def main() -> int:
    try:
        return run()
    except SafeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
