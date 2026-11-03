import json,tempfile,unittest
from pathlib import Path
from unittest import mock
from aux_core.llm import LlmError,OpenAICompatibleLlm

class _Response:
    def __init__(self,obj):self._data=json.dumps(obj).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return self._data

class LlmResponseTests(unittest.TestCase):
    def llm(self,root=None):
        return OpenAICompatibleLlm({'base_url':'http://127.0.0.1:8000/v1','model':'test','profiles':{'fast':{'max_tokens':111,'reasoning_effort':'none'},'deep':{'max_tokens':999,'reasoning_effort':'high'}}},root)
    def test_returns_final_content(self):
        body={'choices':[{'message':{'content':'Hello!','reasoning_content':'hidden'},'finish_reason':'stop'}]}
        with mock.patch('aux_core.llm.urllib.request.urlopen',return_value=_Response(body)):
            self.assertEqual(self.llm().chat([{'role':'user','content':'hi'}]),'Hello!')
    def test_reasoning_only_is_not_surfaced(self):
        body={'choices':[{'message':{'content':'','reasoning_content':'private reasoning'},'finish_reason':'length'}]}
        with mock.patch('aux_core.llm.urllib.request.urlopen',return_value=_Response(body)):
            with self.assertRaises(LlmError) as ctx:self.llm().chat([{'role':'user','content':'hi'}],reasoning_mode='deep')
        self.assertIn('reasoning but no final answer',str(ctx.exception));self.assertNotIn('private reasoning',str(ctx.exception))
    def test_fast_and_deep_request_profiles(self):
        llm=self.llm();fast,_=llm._payload([{'role':'user','content':'hi'}],reasoning_mode='fast');deep,_=llm._payload([{'role':'user','content':'hard'}],reasoning_mode='deep')
        self.assertEqual(fast['max_tokens'],111);self.assertEqual(fast['reasoning_effort'],'none');self.assertFalse(fast['chat_template_kwargs']['enable_thinking'])
        self.assertEqual(deep['max_tokens'],999);self.assertEqual(deep['reasoning_effort'],'high');self.assertTrue(deep['chat_template_kwargs']['enable_thinking'])
    def test_system_prompt_file(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'prompt.txt').write_text('Robot identity prompt',encoding='utf-8')
            llm=OpenAICompatibleLlm({'base_url':'x','model':'x','system_prompt_file':'prompt.txt'},root)
            self.assertEqual(llm.system_prompt,'Robot identity prompt')

if __name__=='__main__':unittest.main()
