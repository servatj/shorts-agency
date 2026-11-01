"""Fixed-route editorial API client. No redirects, proxies, retries or downloads."""
import asyncio
import json
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError


class BridgeError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, config):
        self.config = config

    async def request(self, method, path, body=None):
        return await asyncio.to_thread(self._request, method, path, body)

    def _request(self, method, path, body):
        request = Request(self.config.api_base_url + path,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={'Authorization': 'Bearer ' + self.config.api_token,
                                   'Content-Type': 'application/json', 'Accept': 'application/json'}, method=method)
        try:
            with build_opener(NoRedirect(), ProxyHandler({})).open(request, timeout=10) as response:
                data = response.read(4 * 1024 * 1024 + 1)
                if len(data) > 4 * 1024 * 1024:
                    raise BridgeError('upstream_response_too_large')
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise BridgeError('invalid_upstream_response')
                return result
        except HTTPError as error:
            error.close()
            codes = {400:'upstream_validation_failed',401:'upstream_auth_failed',403:'upstream_forbidden',404:'not_found',409:'conflict',301:'upstream_redirect_rejected',302:'upstream_redirect_rejected',307:'upstream_redirect_rejected',308:'upstream_redirect_rejected'}
            raise BridgeError(codes.get(error.code, 'upstream_unavailable')) from None
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('upstream_unavailable') from None
