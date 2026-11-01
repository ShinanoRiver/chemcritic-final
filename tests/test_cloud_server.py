import base64
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest

from app.chemcritic.cloud_server import create_cloud_server


class CloudDemoTests(unittest.TestCase):
    def test_protected_routes_and_same_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            server = create_cloud_server(None,'https://demo.example','team','test-only-password-long',0,Path(temp)/'db')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            token='Basic '+base64.b64encode(b'team:test-only-password-long').decode()
            def request(path,auth=True,origin=None,method='GET',host='demo.example'):
                connection=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                headers={'Host':host,'Content-Type':'application/json'}
                if auth:headers['Authorization']=token
                if origin:headers['Origin']=origin
                connection.request(method,path,body=b'{}' if method=='POST' else None,headers=headers)
                response=connection.getresponse();status=response.status;response.read();connection.close();return status
            try:
                self.assertEqual(request('/healthz',False),200)
                self.assertEqual(request('/',False),401)
                self.assertEqual(request('/api/history',False),401)
                self.assertEqual(request('/'),200)
                self.assertEqual(request('/api/bootstrap'),200)
                self.assertEqual(request('/api/history'),200)
                self.assertEqual(request('/',host='evil.example'),403)
                self.assertEqual(request('/api/agent/reviews',origin='https://evil.example',method='POST'),403)
                self.assertEqual(request('/api/agent/reviews',method='POST'),403)
                for i in range(6):
                    self.assertEqual(request('/api/agent/reviews',origin='https://demo.example',method='POST'),503)
                self.assertEqual(request('/api/agent/reviews',origin='https://demo.example',method='POST'),429)
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_invalid_configuration(self):
        for origin,password in [('http://demo.example','long-test-password'),('https://demo.example/path','long-test-password'),('https://demo.example','short')]:
            with self.assertRaises(ValueError):create_cloud_server(None,origin,'team',password)
