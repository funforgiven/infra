"""Onecta OAuth using the callback registered for this Home Assistant instance.

Installed over the upstream application_credentials.py by install-onecta.py.
Uses HA's documented custom OAuth implementation extension; other integrations
can continue using My Home Assistant.
"""
from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


class DirectCallbackImplementation(AuthImplementation):
    @property
    def redirect_uri(self) -> str:
        return "https://home.fahrican.com/auth/external/callback"


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> AuthImplementation:
    return DirectCallbackImplementation(
        hass,
        auth_domain,
        credential,
        AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN),
    )
