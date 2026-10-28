import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from app import config, llm, model_status, upstage, public_demo, knowledge


class UpstageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.p=upstage.profile()
        self.p['api_key']='SYNTHETIC-TEST-KEY'
        self.cfg={'llm':{'active':'upstage','profiles':{'upstage':self.p,'offline':{'provider':'offline'}}}}
        self.patches=[patch.object(config,'CONFIG_PATH',Path(self.temp.name)/'config.json'),
                      patch.dict('os.environ',{'UPSTAGE_API_KEY':''}),
                      patch.object(model_status,'_inflight',None),patch.object(model_status,'_last_response',None)]
        for p in self.patches:p.start()
        config.save(self.cfg)

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def completion(self, content='{"ok":true}',model='solar-pro4-260806',status=200):
        return httpx.Response(status, json={'model':model,'choices':[{'message':{'content':content,'reasoning':'not-final-answer'}}]})

    def test_snapshot_never_calls_cloud_and_key_is_not_disclosed(self):
        with patch.object(llm.httpx,'get') as get,patch.object(llm.httpx,'post') as post:
            result=model_status.snapshot()
        get.assert_not_called();post.assert_not_called()
        self.assertEqual(result['connection']['state'],'upstage')
        self.assertTrue(result['checkable']);self.assertFalse(result['local'])
        self.assertNotIn(self.p['api_key'],json.dumps(result)+json.dumps(config.public_llm_view(self.cfg)))

    def test_missing_key_never_calls_api(self):
        self.cfg['llm']['profiles']['upstage']['api_key']='';config.save(self.cfg)
        with patch.object(llm.httpx,'post') as post:
            result=model_status.snapshot()
            self.assertEqual(result['connection']['state'],'key_missing')
            self.assertFalse(result['checkable'])
            with self.assertRaises(HTTPException):model_status.check(result['selection_id'])
            with self.assertRaises(llm.LLMError):llm.get_provider(config.active_profile()).chat([])
        post.assert_not_called()

    def test_explicit_check_uses_official_endpoint_and_snapshot_model(self):
        token=model_status.snapshot()['selection_id']
        with patch.object(llm.httpx,'post',return_value=self.completion()) as post:
            result=model_status.check(token)
        self.assertEqual(result['response']['state'],'verified')
        self.assertEqual(post.call_args.args[0],upstage.BASE_URL+'/chat/completions')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'],'Bearer SYNTHETIC-TEST-KEY')
        self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'],'none')
        self.assertEqual(post.call_args.kwargs['json']['max_tokens'],64)
        self.assertNotIn('not-final-answer',json.dumps(result))

    def test_model_switch_invalidates_check(self):
        token=model_status.snapshot()['selection_id']
        self.cfg['llm']['active']='offline';config.save(self.cfg)
        with patch.object(llm.httpx,'post') as post,self.assertRaises(HTTPException) as caught:
            model_status.check(token)
        self.assertEqual(caught.exception.status_code,409);post.assert_not_called()

    def test_unexpected_host_or_model_is_not_upstage(self):
        for change in ({'base_url':'https://api.upstage.ai.evil/v1'}, {'base_url':'http://api.upstage.ai/v1'},
                       {'base_url':'https://api.upstage.ai/v1?key=bad'}, {'model':'different-model'}):
            self.assertFalse(upstage.matches(self.p|change))
        self.assertFalse(upstage.same_model('solar-pro4','solar-mini4'))

    def test_anonymous_public_cannot_add_or_change_key(self):
        base={'llm':{'active':'local_gemma','profiles':{key:dict(provider='openai_compatible',base_url='http://127.0.0.1:11434/v1',model=value) for key,value in public_demo.MODELS.items()}}}
        inject=copy.deepcopy(base);inject['llm']['profiles']['upstage']=self.p;inject['llm']['active']='upstage'
        with self.assertRaises(ValueError):public_demo.validate_config(inject,base)
        base['llm']['profiles']['upstage']=self.p
        value=copy.deepcopy(base);value['llm']['active']='upstage';public_demo.validate_config(value,base)
        value['llm']['profiles']['upstage']['api_key']='replacement'
        with self.assertRaises(ValueError):public_demo.validate_config(value,base)

    def test_failed_api_never_logs_body_containing_credentials(self):
        with patch.object(llm.httpx,'post',return_value=self.completion(status=401)),patch.object(llm.log,'warning') as log:
            with self.assertRaises(llm.LLMError):llm.get_provider(self.p).chat([])
        log.assert_not_called()


if __name__=='__main__':unittest.main()
