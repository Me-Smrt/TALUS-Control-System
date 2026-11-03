import tempfile
import unittest
from pathlib import Path
from unittest import mock
from aux_core.llm_server import ManagedLlamaServer, LlmServerError


class ManagedServerTests(unittest.TestCase):
    def cfg(self, root: Path):
        q = root/'models/qwen'; q.mkdir(parents=True)
        (q/'Qwen3.5-4B-Q4_K_M.gguf').write_bytes(b'x')
        (q/'mmproj-Qwen3.5-4B-BF16.gguf').write_bytes(b'x')
        return {
            'base_url':'http://127.0.0.1:8000/v1',
            'model':'Qwen/Qwen3.5-4B',
            'managed_server':{
                'auto_start':True,'executable':'llama-server',
                'model_path':'models/qwen/Qwen3.5-4B-Q4_K_M.gguf',
                'mmproj_path':'models/qwen/mmproj-Qwen3.5-4B-BF16.gguf',
                'host':'127.0.0.1','port':8000,'context_size':4096,
                'parallel':1,'gpu_layers':'auto','flash_attention':True,'reasoning':'off',
            }
        }

    def test_command_has_model_mmproj_and_api_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cfg=self.cfg(root); s=ManagedLlamaServer(root,cfg)
            with mock.patch('aux_core.llm_server.shutil.which', return_value='/bin/llama-server'):
                cmd=s._build_command()
            self.assertIn('--model',cmd); self.assertIn('--mmproj',cmd)
            self.assertIn('--alias',cmd); self.assertIn('Qwen/Qwen3.5-4B',cmd)
            self.assertIn('--port',cmd); self.assertIn('8000',cmd)
            self.assertIn('--reasoning',cmd); self.assertEqual(cmd[cmd.index('--reasoning')+1],'off')
            fa_i=cmd.index('--flash-attn')
            self.assertEqual(cmd[fa_i+1], 'on')

    def test_flash_attention_string_auto_is_emitted_with_value(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cfg=self.cfg(root)
            cfg['managed_server']['flash_attention']='auto'
            s=ManagedLlamaServer(root,cfg)
            with mock.patch('aux_core.llm_server.shutil.which', return_value='/bin/llama-server'):
                cmd=s._build_command()
            fa_i=cmd.index('--flash-attn')
            self.assertEqual(cmd[fa_i+1], 'auto')


    def test_reasoning_defaults_to_auto_for_per_request_profiles(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cfg=self.cfg(root)
            cfg['managed_server'].pop('reasoning',None)
            s=ManagedLlamaServer(root,cfg)
            with mock.patch('aux_core.llm_server.shutil.which', return_value='/bin/llama-server'):
                cmd=s._build_command()
            self.assertEqual(cmd[cmd.index('--reasoning')+1],'auto')

    def test_existing_server_is_reused_not_owned(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); s=ManagedLlamaServer(root,self.cfg(root))
            with mock.patch.object(s,'healthy',return_value=True):
                self.assertEqual(s.ensure_ready(),'external')
                self.assertFalse(s.owns_process)

    def test_missing_model_fails_before_spawn(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cfg=self.cfg(root)
            (root/'models/qwen/Qwen3.5-4B-Q4_K_M.gguf').unlink()
            s=ManagedLlamaServer(root,cfg)
            with mock.patch('aux_core.llm_server.shutil.which', return_value='/bin/llama-server'):
                with self.assertRaises(LlmServerError): s._build_command()

if __name__=='__main__': unittest.main()
