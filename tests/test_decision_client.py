import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from aiden_decisions.decision_client import DecisionClient
from aiden_decisions.decisions import DecisionInputError, DecisionBackendError
from tests.test_decisions import request, response


class ClientTests(unittest.TestCase):
    def test_loopback_only_and_short_timeout(self):
        for url in ['https://example.invalid', 'http://localhost:8841',
                    'http://127.0.0.1:8841/next', 'http://user:secret@127.0.0.1:8841']:
            with self.assertRaises(DecisionInputError):
                DecisionClient(url)
        with self.assertRaises(DecisionInputError):
            DecisionClient(timeout=30)

    def test_proxy_and_redirect_handlers_are_closed(self):
        client = DecisionClient()
        from aiden_decisions.decision_client import _NoRedirect
        self.assertTrue(any(isinstance(h, _NoRedirect) for h in client.opener.handlers))
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'http://untrusted.invalid'))

    def test_compact_route_keeps_review_and_draft_boundary(self):
        client = DecisionClient()
        fake = {'route': 'tv', 'source': 'local_decision_model', 'draft_intent': None,
                'needs_review': False, 'device_action_authority': 'none',
                'answers': {'room': {'choice': 'living_room'}}, 'private_extra': 'not copied',
                'aiden': {'cache_hit': True}}
        with patch.object(client, '_request', return_value=fake):
            result = client.route('Put Bluey on the living room TV')
        self.assertTrue(result['needs_review'])
        self.assertTrue(result['cache_hit'])
        self.assertEqual(result['room'], 'living_room')
        self.assertNotIn('private_extra', result)
        self.assertEqual(result['device_action_authority'], 'none')

    def test_generic_answers_are_validated_and_compacted(self):
        client = DecisionClient()
        result = response()
        result['aiden'] = {'device_action_authority': 'none', 'needs_review': True}
        with patch.object(client, '_request', return_value=result):
            compact = client.decide(request()['state'], request()['questions'])
        self.assertEqual(compact['answers'], result['answers'])
        self.assertFalse(compact['confidence_calibrated'])
        result['answers']['topic']['choice'] = 'run_shell'
        with patch.object(client, '_request', return_value=result), self.assertRaises(DecisionBackendError):
            client.decide(request()['state'], request()['questions'])

    def test_non_read_only_authority_rejected(self):
        client = DecisionClient()
        with patch.object(client, '_request', return_value={'device_action_authority': 'control'}):
            with self.assertRaises(DecisionBackendError): client.health()

    def test_invalid_input_and_endpoints_do_not_contact_backend(self):
        client = DecisionClient()
        with patch.object(client.opener, 'open') as opened:
            with self.assertRaises(DecisionInputError): client.route('x' * 4001)
            with self.assertRaises(DecisionInputError): client.decide('', {})
            with self.assertRaises(DecisionInputError): client._request('/execute', {})
            opened.assert_not_called()

    def test_timeout_is_not_retried_or_exposed(self):
        client = DecisionClient()
        with patch.object(client.opener, 'open', side_effect=TimeoutError('PRIVATE_FAKE')) as opened:
            with self.assertRaises(DecisionBackendError) as error:
                client.health()
            self.assertNotIn('PRIVATE_FAKE', str(error.exception))
            opened.assert_called_once()

    def test_http_error_body_is_not_exposed(self):
        client = DecisionClient()
        error = HTTPError('http://127.0.0.1:8841/health', 503, 'PRIVATE_FAKE', {}, io.BytesIO(b'PRIVATE_FAKE'))
        with patch.object(client.opener, 'open', side_effect=error):
            with self.assertRaises(DecisionBackendError) as caught: client.health()
            self.assertNotIn('PRIVATE_FAKE', str(caught.exception))


if __name__ == '__main__': unittest.main()
