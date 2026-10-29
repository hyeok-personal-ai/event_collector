import os
import unittest
from unittest.mock import patch
from app.sources import SOURCES, extract_links
from app.core import canonical
from app.batch_common import public_event
from app.batch_key import read_key

class PublicCollectorTests(unittest.TestCase):
    def test_catalog_replacements_are_active(self):
        sources={s.id:s for s in SOURCES}
        self.assertEqual(len(sources),len(SOURCES))
        for s in SOURCES:
            if not s.enabled:
                self.assertTrue(s.note)
                self.assertTrue(s.replacements)
            for replacement in s.replacements:
                self.assertTrue(sources[replacement].enabled)

    def test_luma_navigation_is_not_an_event(self):
        source=next(s for s in SOURCES if s.id=='openai')
        items=extract_links('<a href="/ai?k=t">Featured in AI</a><a class="event-link" aria-label="Codex workshop" href="/workshop"></a>',source.url,source)
        self.assertEqual([e['title'] for e in items],['Codex workshop'])
        self.assertEqual(items[0]['status'],'CHECK_REQUIRED')

    def test_public_payload_excludes_private_fields(self):
        payload=public_event({'title':'Public event','canonical_url':'https://example.com/event','profile':{'age':25},'saved':True,'raw_excerpt':'private','secret':'private'})
        self.assertFalse({'profile','saved','raw_excerpt','secret'} & payload.keys())

    def test_credentials_require_environment(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):read_key()

    def test_tracking_does_not_duplicate_event(self):
        self.assertEqual(canonical('https://www.meetup.com/awskrug/events/123/?eventOrigin=group'),'https://www.meetup.com/awskrug/events/123')

if __name__=='__main__':unittest.main()
