import copy
import unittest
from unittest.mock import patch

from app import llm


class StructuredRequestTest(unittest.TestCase):
    def test_schema_is_sent_and_request_fields_override_extra_body_without_mutation(self):
        schema = {
            'type': 'object',
            'properties': {'selected_quote_id': {'type': ['string', 'null'], 'enum': ['q1', None]}},
            'required': ['selected_quote_id'],
            'additionalProperties': False,
        }
        extra = {'model': 'wrong', 'messages': [], 'max_tokens': 999, 'temperature': 1, 'stream': True,
                 'response_format': {'type': 'json_object'}}
        profile = {'base_url': 'http://localhost:11434/v1', 'model': 'chosen', 'extra_body': extra}
        before = copy.deepcopy(profile)
        response = type('Response', (), {'status_code': 200, 'json': lambda self: {'choices': [{'message': {'content': '{"selected_quote_id":null}'}}]}})()
        with patch.object(llm.httpx, 'post', return_value=response) as post:
            llm.OpenAICompatibleProvider(profile).chat([{'role': 'user', 'content': 'pick'}], max_tokens=80, temperature=0, response_schema=schema)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['model'], 'chosen')
        self.assertEqual(body['messages'], [{'role': 'user', 'content': 'pick'}])
        self.assertEqual(body['max_tokens'], 80)
        self.assertEqual(body['temperature'], 0)
        self.assertIs(body['stream'], False)
        self.assertEqual(body['response_format'], {'type': 'json_schema', 'json_schema': {'name': 'quote_selection', 'strict': True, 'schema': schema}})
        self.assertEqual(profile, before)

    def test_plain_chat_keeps_extra_body_behavior_without_schema_injection(self):
        extra = {'stream': True, 'response_format': {'type': 'json_object'}, 'custom': 'kept'}
        profile = {'base_url': 'http://localhost:11434/v1', 'model': 'chosen', 'extra_body': extra}
        response = type('Response', (), {'status_code': 200, 'json': lambda self: {'choices': [{'message': {'content': 'ok'}}]}})()
        with patch.object(llm.httpx, 'post', return_value=response) as post:
            llm.OpenAICompatibleProvider(profile).chat([{'role': 'user', 'content': 'plain'}])
        body = post.call_args.kwargs['json']
        self.assertIs(body['stream'], True)
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertEqual(body['custom'], 'kept')
        self.assertNotEqual(body['response_format'].get('type'), 'json_schema')

    def test_unsupported_schema_status_fails_as_single_safe_call(self):
        response = type('Response', (), {'status_code': 400, 'text': 'unsupported format'})()
        with patch.object(llm.httpx, 'post', return_value=response) as post:
            with self.assertRaises(llm.LLMError) as caught:
                llm.OpenAICompatibleProvider({'base_url': 'http://localhost:11434/v1', 'model': 'test'}).chat(
                    [{'role': 'user', 'content': 'pick'}], response_schema={'type': 'object'})
        self.assertEqual(caught.exception.kind, '모델 서버 HTTP 400 오류')
        post.assert_called_once()


if __name__ == '__main__':
    unittest.main()
