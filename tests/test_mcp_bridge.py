"""Optional MCP protocol acceptance tests; synthetic isolated SQLite only."""
import importlib.util
import unittest

HAS_MCP = importlib.util.find_spec('mcp') is not None

@unittest.skipUnless(HAS_MCP, 'optional requirements-mcp.txt not installed')
class ProtocolTests(unittest.TestCase):
    def setUp(self):
        import test_web
        from synthetic_inventory import inventory
        import json
        self.fixture = test_web.WebTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        (self.fixture.root / 'data/social-inventory.json').write_text(json.dumps(inventory()))

    def test_instructions_allow_external_production_without_claiming_render_tools(self):
        from mcp_bridge.server import create_server
        from mcp_bridge.config import Config
        server = create_server(Config('http://127.0.0.1:8765', 'synthetic-0123456789-abcdefghijk'))
        instructions = server.create_initialization_options().instructions
        self.assertIn('separately approved external tools', instructions)
        self.assertNotIn('Never publish, fabricate metrics, run commands or render', instructions)

    def test_redirect_never_forwards_credentials(self):
        import asyncio, threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from mcp_bridge.api import Api, BridgeError
        from mcp_bridge.config import Config
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(302)
                self.send_header('Location','http://127.0.0.1:%s/stolen'%self.server.server_port)
                self.end_headers()
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            api=Api(Config('http://127.0.0.1:%s'%server.server_port,'synthetic-secret-0123456789abcdefghijk'))
            with self.assertRaisesRegex(BridgeError,'upstream_redirect_rejected'):
                asyncio.run(api.request('GET','/v1/shorts'))
            self.assertEqual(seen,['/v1/shorts'])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_race_redirect_sanitization_and_output_bound(self):
        import asyncio, json
        from unittest.mock import patch
        from mcp import Client
        from mcp_bridge.server import create_server
        from mcp_bridge.config import Config
        from mcp_bridge.api import Api
        from synthetic_credentials import TEST_TOKEN
        from web_store import WebStore
        store=WebStore(self.fixture.root / 'data/agency.db')
        created=store.create_short({'title':'Before','status':'draft'})
        config=Config('http://127.0.0.1:%s'%self.fixture.server.server_port,TEST_TOKEN)
        original=Api.request
        async def racing(api,method,path,body=None):
            if method == 'PATCH': store.patch_short(created['id'],{'status':'published'})
            return await original(api,method,path,body)
        async def exercise():
            async with Client(create_server(config)) as client:
                with patch.object(Api,'request',racing):
                    result=await client.call_tool('shorts_update_draft',{'video_id':created['id'],'changes':{'title':'After'}})
                    self.assertTrue(result.is_error)
                self.assertEqual(store.get_short(created['id'])['title'],'Before')
                async def failure(*args,**kwargs): raise RuntimeError(TEST_TOKEN)
                with patch.object(Api,'request',failure):
                    result=await client.call_tool('shorts_list_accounts',{})
                    self.assertTrue(result.is_error)
                    self.assertNotIn(TEST_TOKEN,str(result))
                async def giant(*args,**kwargs): return {'script':'x'*2100000}
                with patch.object(Api,'request',giant):
                    result=await client.call_tool('shorts_get_video',{'video_id':1})
                    self.assertTrue(result.is_error)
        asyncio.run(exercise())

    def test_stdio_and_http_real_transports(self):
        import asyncio, os, sys, socket, subprocess, time, http.client, json
        from mcp import Client, StdioServerParameters
        from mcp.client.streamable_http import streamable_http_client
        import httpx2
        from synthetic_credentials import TEST_TOKEN
        token = 'synthetic-mcp-token-' + 'b7' * 20
        env = {**os.environ, 'SHORTS_API_TOKEN':TEST_TOKEN, 'SHORTS_API_BASE_URL':'http://127.0.0.1:%s' % self.fixture.server.server_port, 'SHORTS_MCP_TOKEN':token}
        async def stdio():
            async with Client(StdioServerParameters(command=sys.executable,args=['-m','mcp_bridge.server','--transport','stdio'],env=env)) as client:
                self.assertEqual(len((await client.list_tools()).tools),13)
                self.assertFalse((await client.call_tool('shorts_list_accounts',{})).is_error)
        asyncio.run(stdio())
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        proc=subprocess.Popen([sys.executable,'-m','mcp_bridge.server','--transport','http','--port',str(port)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.addCleanup(lambda: (proc.terminate(),proc.communicate(timeout=5)))
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1): break
            except OSError: time.sleep(.05)
        def request(headers,body=b'{}'):
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            conn.request('POST','/mcp',body,headers)
            response=conn.getresponse(); result=(response.status,response.read());conn.close();return result
        auth={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        self.assertEqual(request({})[0],401)
        self.assertEqual(request({'Authorization':'Bearer wrong'})[0],401)
        self.assertEqual(request({**auth,'Origin':'null'})[0],403)
        self.assertEqual(request({**auth,'Host':'evil.example'})[0],403)
        self.assertEqual(request(auth,b'x'*262145)[0],413)
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        conn.request('GET','/mcp',headers=auth)
        response=conn.getresponse()
        self.assertEqual(response.status,405)
        self.assertIn('application/json',response.getheader('Content-Type',''))
        response.read();conn.close()
        for name,value in [('Authorization','Bearer '+token),('Origin','https://example.org')]:
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            conn.putrequest('POST','/mcp')
            conn.putheader('Authorization','Bearer '+token)
            conn.putheader(name,value)
            if name == 'Origin': conn.putheader('Origin',value)
            conn.putheader('Content-Length','2');conn.endheaders(b'{}')
            response=conn.getresponse()
            self.assertIn(response.status,(401,403));response.read();conn.close()
        async def http():
            async with httpx2.AsyncClient(headers=auth) as http_client:
                async with Client(streamable_http_client('http://127.0.0.1:%s/mcp'%port,http_client=http_client)) as client:
                    self.assertEqual(len((await client.list_tools()).tools),13)
                    self.assertFalse((await client.call_tool('shorts_list_accounts',{})).is_error)
                    self.assertTrue((await client.read_resource('shorts://workflow')).contents)
                    self.assertTrue((await client.list_prompts()).prompts)
        asyncio.run(http())
        # Exercise the parent's exact /mcp forwarding route against the real SDK.
        from web_backend import build_server
        from api_server import make_server
        import threading
        proxy=build_server(make_server(self.fixture.store,TEST_TOKEN),'127.0.0.1',0,root=self.fixture.root,mcp_port=port)
        thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
        async def via_proxy():
            async with httpx2.AsyncClient(headers={**auth,'Host':'127.0.0.1:%s'%port}) as http_client:
                async with Client(streamable_http_client('http://127.0.0.1:%s/mcp'%proxy.server_port,http_client=http_client),mode='legacy') as client:
                    self.assertFalse((await client.call_tool('shorts_list_accounts',{})).is_error)
        try: asyncio.run(via_proxy())
        finally: proxy.shutdown();proxy.server_close();thread.join()

    def test_editorial_protocol_roundtrip(self):
        import asyncio
        from mcp import Client
        from mcp_bridge.server import create_server
        from mcp_bridge.config import Config
        from synthetic_credentials import TEST_TOKEN
        from web_store import WebStore
        config = Config('http://127.0.0.1:%s' % self.fixture.server.server_port, TEST_TOKEN)
        store = WebStore(self.fixture.root / 'data/agency.db')
        async def exercise():
            async with Client(create_server(config)) as client:
                tools = await client.list_tools()
                self.assertEqual(len(tools.tools), 13)
                async def call(name, **args):
                    result = await client.call_tool(name, args)
                    self.assertFalse(result.is_error, result)
                    import json
                    return json.loads(result.content[0].text)
                created = await call('shorts_create_draft', title='Synthetic draft', account_id='youtube:sample_account_00', notes='Keep notes')
                key = created['id']
                self.assertEqual(store.get_short(key), created)
                await call('shorts_update_draft', video_id=key, changes={'script':'Narration', 'channel':'Freeform'})
                await call('shorts_attach_assets', video_id=key, preview_url='https://example.org/clip.mp4')
                saved = await call('shorts_submit_for_review', video_id=key)
                self.assertEqual(saved, store.get_short(key))
                self.assertEqual((saved['notes'],saved['channel'],saved['script'],saved['status']), ('Keep notes','Freeform','Narration','review'))
                listing = await call('shorts_list_videos', limit=1, offset=0)
                self.assertNotIn('script',listing['items'][0])
                self.assertEqual(listing['returned'],1)
                accounts = await call('shorts_list_accounts',platform='youtube',limit=1)
                self.assertEqual((accounts['total'],accounts['original_total'],accounts['returned']),(1,3,1))
                self.assertEqual((await call('shorts_list_accounts',offset=3))['returned'],0)
                for limit in [0,101,True]:
                    self.assertTrue((await client.call_tool('shorts_list_videos',{'limit':limit})).is_error)
                for args in [{'title':'Bad','account_id':'missing'}, {'title':'Bad','account_id':'youtube:sample_account_00','status':'published'}]:
                    self.assertTrue((await client.call_tool('shorts_create_draft',args)).is_error)
                self.assertTrue((await client.call_tool('shorts_attach_assets',{'video_id':key,'preview_url':'javascript:alert(1)'})).is_error)
                from test_references import ReferenceTests
                from reference_store import ReferenceStore
                references=ReferenceStore(self.fixture.root / 'data/agency.db')
                references.import_references({'items':[ReferenceTests.item(self)],'run':ReferenceTests.run_info(self)})
                refs=await call('shorts_list_references',q='Science',content_type='short',limit=1)
                self.assertEqual((refs['total'],refs['returned']),(1,1))
                self.assertNotIn('description',refs['items'][0])
                ref=await call('shorts_get_reference',reference_id=refs['items'][0]['id'])
                self.assertEqual(ref,references.get_reference(ref['id']))
                await call('shorts_get_templates')
                await call('shorts_get_template_prompts',template_id='synthetic')
                self.assertEqual((await call('shorts_get_metrics',video_id=key))['items'], [])
                for changes in [{'status':'published'},{'x':1},{'account_id':'unknown'}]:
                    self.assertTrue((await client.call_tool('shorts_update_draft',{'video_id':key,'changes':changes})).is_error)
                for value in [True, -1, 1.0, '1e0']:
                    self.assertTrue((await client.call_tool('shorts_get_video',{'video_id':value})).is_error)
                store.patch_short(key, {'status':'published'})
                self.assertTrue((await client.call_tool('shorts_attach_assets', {'video_id':key,'thumbnail_url':'https://example.org/a.png'})).is_error)
                self.assertTrue((await client.read_resource('shorts://workflow')).contents)
                self.assertTrue((await client.get_prompt('shorts_production_brief', {'channel':'synthetic','topic':'topic','mode':'guide'})).messages)
        asyncio.run(exercise())

@unittest.skipUnless(HAS_MCP, 'optional requirements-mcp.txt not installed')
class ConfigurationTests(unittest.TestCase):
    def test_factory_rejects_weak_direct_config(self):
        from mcp_bridge.config import Config
        from mcp_bridge.server import create_app
        with self.assertRaises(ValueError):
            create_app(Config('http://127.0.0.1:8765','outbound-0123456789abcdefghijklmnop','weak'))

    def test_credentials_and_safe_urls(self):
        from mcp_bridge.config import Config
        token = 'synthetic-upstream-' + 'a9' * 20
        config = Config.from_env({'SHORTS_API_TOKEN': token}, transport='stdio')
        self.assertEqual(config.api_base_url, 'http://127.0.0.1:8765')
        for url in ['http://evil.example', 'https://user:pass@example.org', 'https://example.org/?x=1', 'https://example.org/#x']:
            with self.assertRaises(ValueError):
                Config.from_env({'SHORTS_API_TOKEN': token, 'SHORTS_API_BASE_URL': url}, transport='stdio')
        for incoming in ['', 'short', token]:
            with self.assertRaises(ValueError):
                Config.from_env({'SHORTS_API_TOKEN': token, 'SHORTS_MCP_TOKEN': incoming}, transport='http')
