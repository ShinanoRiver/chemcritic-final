import unittest
from app.chemcritic.cloud_server import configured_origin


class RailwayConfigTests(unittest.TestCase):
    def test_generated_domain(self):
        self.assertEqual(configured_origin({'RAILWAY_PUBLIC_DOMAIN':'demo.up.railway.app'}),
                         'https://demo.up.railway.app')

    def test_explicit_and_render_compatibility(self):
        self.assertEqual(configured_origin({'PUBLIC_ORIGIN':'https://example.org/',
                                           'RAILWAY_PUBLIC_DOMAIN':'demo.up.railway.app'}),
                         'https://example.org')
        self.assertEqual(configured_origin({'RENDER_EXTERNAL_URL':'https://demo.onrender.com'}),
                         'https://demo.onrender.com')

    def test_missing_domain_fails_closed(self):
        with self.assertRaises(KeyError): configured_origin({})
