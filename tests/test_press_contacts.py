"""Run with python3 -m unittest discover -s tests -p 'test_press_contacts.py'."""
import json
import copy
import refresh_press_contacts
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build_press as press


class ContactSourcesTest(unittest.TestCase):
    def test_contact_only_refresh_preserves_live_roster_and_metadata(self):
        payload = {'people': [{'id': 'one', 'name': 'Jane Example', 'outlet': 'daily', 'story_count': 12}],
                   'counts': {'with_email': 0, 'people': 1}, 'report': {'notes': []},
                   'as_of': '2026-09-17T11:00:00Z', 'outlets': [{'id': 'daily'}], 'beats': {'housing': {}}}
        before = copy.deepcopy(payload)
        contact = {'id': 'one', 'email': 'jane.example@example.org',
                   'email_source_url': 'https://example.org/staff/jane', 'email_evidence': 'Published email'}
        with patch.object(press, 'read_contact_sources', return_value=[contact]):
            self.assertEqual(refresh_press_contacts.enrich(payload), 1)
        self.assertEqual(payload['counts']['with_email'], 1)
        self.assertEqual(len(payload['people']), 1)
        for key in ('as_of', 'outlets', 'beats'):
            self.assertEqual(payload[key], before[key])
        for key, value in before['people'][0].items():
            self.assertEqual(payload['people'][0][key], value)

    def test_only_matching_missing_contacts_are_requested(self):
        people = [
            {'id': 'one', 'name': 'Jane Example', 'outlet': 'daily'},
            {'id': 'two', 'name': 'Jane Example', 'outlet': 'other'},
            {'id': 'three', 'name': 'Jane Example', 'outlet': 'daily', 'email': 'existing@example.org'},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'contact_sources.json').write_text(json.dumps([
                {'name': 'Jane Example', 'outlet': 'daily', 'url': 'https://example.org/staff/jane'}]))
            with patch.object(press, 'PRESS', Path(tmp)), patch.object(press, 'read_author_page', return_value={'email': 'jane.example@example.org'}) as read:
                press.read_contact_sources(people)
                read.assert_called_once_with(('one', 'Jane Example', 'https://example.org/staff/jane'))

    def test_published_address_and_provenance_survive(self):
        html = '<h1>Jane Example</h1><p>Email: jane.example@example.org</p>'
        with patch.object(press, 'curl', return_value=html):
            contact = press.read_author_page(('one', 'Jane Example', 'https://example.org/staff/jane'))
        people = [{'id': 'one', 'name': 'Jane Example'}]
        self.assertEqual(press.apply_contact_sources(people, [contact]), 1)
        self.assertEqual(people[0]['email'], 'jane.example@example.org')
        self.assertEqual(people[0]['email_source_url'], 'https://example.org/staff/jane')
        self.assertIn('jane.example@example.org', people[0]['email_evidence'])
        self.assertEqual(press.apply_contact_sources(people, [dict(contact, email='other@example.org')]), 0)

    def test_unpublished_mismatched_and_generic_addresses_rejected(self):
        for html in ('<h1>Jane Example</h1>', '<p>Email: alex.smith@example.org</p>', '<p>Email: news@example.org</p>'):
            with self.subTest(html=html), patch.object(press, 'curl', return_value=html):
                contact = press.read_author_page(('one', 'Jane Example', 'https://example.org/staff/jane'))
                self.assertNotIn('email', contact)
        people = [{'id': 'one', 'name': 'Jane Example'}]
        self.assertEqual(press.apply_contact_sources(people, [{'id': 'one', 'email': 'jane.example@example.org'}]), 0)


if __name__ == '__main__':
    unittest.main()
