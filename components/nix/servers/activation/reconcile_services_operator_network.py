#!/usr/bin/env python3
"""Discover the operator egress address and reconcile its mail-management CIDR."""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from runtime_contract import ContractError, RuntimeContract
from sops_credentials import SopsCredentialError, SopsCredentialStore


DISCOVERY_URLS = (
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
)
CREDENTIAL = "MAIL_MANAGEMENT_CIDRS_JSON"


class OperatorNetworkError(RuntimeError):
    """A safe-to-display operator-network reconciliation error."""


def discover_address() -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    addresses = []
    for url in DISCOVERY_URLS:
        request = urllib.request.Request(
            url, headers={"User-Agent": "fahrican-infra-operator-network/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                value = response.read(128).decode("ascii").strip()
            addresses.append(ipaddress.ip_address(value))
        except (
            urllib.error.URLError,
            TimeoutError,
            UnicodeDecodeError,
            ValueError,
        ) as error:
            raise OperatorNetworkError("operator egress discovery failed") from error
    if len(set(addresses)) != 1:
        raise OperatorNetworkError("independent operator egress discoveries disagree")
    return addresses[0]


def address_cidr(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    return f"{address}/{'32' if address.version == 4 else '128'}"


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--repository-root", type=Path)
    return parser


def main() -> int:
    arguments = argument_parser().parse_args()
    try:
        repository_root = (
            arguments.repository_root.resolve()
            if arguments.repository_root
            else Path(
                subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
        )
        contract = RuntimeContract.load(repository_root)
        route = contract.provisioned_credential(CREDENTIAL)
        if route.provisioner != "reconcile-services-operator-network":
            raise OperatorNetworkError("mail-management CIDR has the wrong provisioner")
        store = SopsCredentialStore(repository_root)
        desired = json.dumps([address_cidr(discover_address())], separators=(",", ":"))
        current = store.read(route.secret_file, CREDENTIAL)
        if current == desired:
            print("operator mail-management CIDR: current")
        elif arguments.command == "apply":
            store.write(route.secret_file, {CREDENTIAL: desired})
            print("operator mail-management CIDR: discovered and encrypted")
        else:
            print("operator mail-management CIDR: reconciliation required")
        return 0
    except (
        ContractError,
        OperatorNetworkError,
        SopsCredentialError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
