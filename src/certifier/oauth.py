"""OAuth for the Claude custom connector (open beta).

Claude registers itself (Dynamic Client Registration) and sends the person to /oauth/login, which
runs in their own browser. "Continue as beta guest" binds the issued tokens to a keyed hash of that
browser's IP ("ip:<key>"), so connector lookups draw on the same daily allowance as the website from
that IP; reconnecting from the same IP doesn't reset it. An admin code (CERTIFIER_ACCESS_CODES) binds
the tokens to that admin instead, bypassing the allowances. The MCP SDK serves discovery, /register,
/authorize, /token and /revoke; this provider supplies storage and the login step. Tokens are stored
hashed; revoking an admin code invalidates its tokens at once.
"""

from __future__ import annotations

import hashlib
import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .access import AccessCodes
from .store import Store

ACCESS_TTL = 3600  # one hour; Claude refreshes automatically
REFRESH_TTL = 30 * 24 * 3600  # 30 days
CODE_TTL = 600
PENDING_TTL = 900
SCOPE = "certify"


def _h(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class BetaOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, store: Store, codes: AccessCodes, base_url: str):
        self.store = store
        self.codes = codes
        self.base_url = base_url.rstrip("/")
        self.resource = f"{self.base_url}/mcp"

    # --- clients ------------------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self.store.get("client", client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.store.put("client", client_info.client_id, client_info.model_dump(mode="json"))

    # --- authorization: hand off to the access-code page ---------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = secrets.token_urlsafe(24)
        self.store.put("pending", request_id, {"client_id": client.client_id,
                                               "params": params.model_dump(mode="json")}, PENDING_TTL)
        return f"{self.base_url}/oauth/login?request={request_id}"

    def pending(self, request_id: str) -> dict | None:
        return self.store.get("pending", request_id)

    def complete_login(self, request_id: str, access_code: str) -> str | None:
        """Admin sign-in: exchange a valid admin code for an authorization code; returns the redirect URL."""
        subject = self.codes.verify(access_code)
        return self._complete(request_id, subject) if subject is not None else None

    def complete_guest(self, request_id: str, ip_key: str) -> str | None:
        """Beta guest sign-in: bind the tokens to the keyed hash of the signing-in browser's IP."""
        return self._complete(request_id, "ip:" + ip_key)

    def _active(self, subject: str) -> bool:
        return subject.startswith("ip:") or self.codes.is_active(subject)

    def _complete(self, request_id: str, subject: str) -> str | None:
        pending = self.store.get("pending", request_id)
        if pending is None:
            return None
        self.store.delete("pending", request_id)
        params = AuthorizationParams.model_validate(pending["params"])
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code, scopes=params.scopes or [SCOPE], expires_at=time.time() + CODE_TTL,
            client_id=pending["client_id"], code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource or self.resource, subject=subject)
        self.store.put("code", code, auth_code.model_dump(mode="json"), CODE_TTL)
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        data = self.store.get("code", authorization_code)
        if not data or data["client_id"] != client.client_id:
            return None
        return AuthorizationCode.model_validate(data)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        self.store.delete("code", authorization_code.code)
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.subject)

    # --- refresh ------------------------------------------------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        data = self.store.get("refresh", _h(refresh_token))
        if not data or data["client_id"] != client.client_id or not self._active(data.get("subject") or ""):
            return None
        return RefreshToken.model_validate({**data, "token": refresh_token})

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        self.store.delete("refresh", _h(refresh_token.token))  # rotate
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.subject)

    # --- access tokens ------------------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        # A raw access code is accepted directly (web page, API, Claude request headers).
        subject = self.codes.verify(token)
        if subject is not None:
            return AccessToken(token=token, client_id="access-code", scopes=[SCOPE], expires_at=None,
                               resource=self.resource, subject=subject)
        data = self.store.get("access", _h(token))
        if not data or not self._active(data.get("subject") or ""):
            return None
        return AccessToken.model_validate({**data, "token": token})

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self.store.delete("access", _h(token.token))
        self.store.delete("refresh", _h(token.token))

    def _issue(self, client_id: str, scopes: list[str], subject: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        common = {"client_id": client_id, "scopes": scopes, "resource": self.resource, "subject": subject}
        self.store.put("access", _h(access), {**common, "token": "", "expires_at": now + ACCESS_TTL}, ACCESS_TTL)
        self.store.put("refresh", _h(refresh), {**common, "token": "", "expires_at": now + REFRESH_TTL}, REFRESH_TTL)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL, scope=" ".join(scopes),
                          refresh_token=refresh)

