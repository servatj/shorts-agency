"""Fixed loopback transport for the stateless, JSON-only MCP service."""
import http.client


def forward(method, headers, body, *, port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    try:
        outgoing = {name: headers[name] for name in (
            'Host', 'Origin', 'Authorization', 'Accept', 'Content-Type',
            'MCP-Protocol-Version', 'MCP-Session-Id',
        ) if name in headers}
        connection.request(method, '/mcp', body=body, headers=outgoing)
        response = connection.getresponse()
        # This transport deliberately does not support SSE: the companion
        # service must use stateless_http=True and json_response=True.
        kind = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
        if kind == 'text/event-stream':
            return 502, b'{"error":"mcp_bad_response"}', 'application/json', {}
        lengths = response.headers.get_all('Content-Length', [])
        if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or int(lengths[0]) > 2 * 1024 * 1024)):
            return 502, b'{"error":"mcp_bad_response"}', 'application/json', {}
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or (data and kind != 'application/json'):
            return 502, b'{"error":"mcp_bad_response"}', 'application/json', {}
        if lengths and method != 'HEAD' and response.status not in (204, 304) and len(data) != int(lengths[0]):
            return 502, b'{"error":"mcp_bad_response"}', 'application/json', {}
        response_headers = {name: response.getheader(name) for name in (
            'WWW-Authenticate', 'Allow', 'MCP-Session-Id',
        ) if response.getheader(name) is not None}
        return response.status, data, response.getheader('Content-Type', 'application/json'), response_headers
    except TimeoutError:
        return 504, b'{"error":"mcp_timeout"}', 'application/json', {}
    except http.client.HTTPException:
        return 502, b'{"error":"mcp_bad_response"}', 'application/json', {}
    except OSError:
        return 503, b'{"error":"mcp_unavailable"}', 'application/json', {}
    finally:
        connection.close()
