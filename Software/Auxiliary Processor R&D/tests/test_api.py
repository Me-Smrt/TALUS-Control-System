import json,tempfile,unittest,urllib.request
from pathlib import Path
from aux_core.api_server import AuxApiServer
from aux_core.state import AuxiliaryState
from aux_core.voices import VoiceRegistry
from aux_core.tts import TtsManager
class C:
 def handle_text(self,*a,**k):return {'reply':'ok'}
class T(unittest.TestCase):
 def test_voice_api(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'voices.json').write_text(json.dumps({'voices':[{'id':'tone','display_name':'Tone','backend':'mock','languages':['*'],'enabled':True}]}));r=VoiceRegistry(p/'voices.json',p/'state.json','tone');m=TtsManager({'backends':{'mock':{'type':'mock_tone'}},'speed':1},r,p);s=AuxApiServer({'bind_host':'127.0.0.1','port':0,'allow_unauthenticated_loopback':True},AuxiliaryState(),m,r,C());s.start()
   try:
    with urllib.request.urlopen(f'http://127.0.0.1:{s.port}/v1/voices') as x:o=json.load(x);self.assertEqual(o['active_voice_id'],'tone')
    req=urllib.request.Request(f'http://127.0.0.1:{s.port}/v1/tts/synthesize',data=json.dumps({'text':'hello'}).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req) as x:self.assertEqual(x.headers.get_content_type(),'audio/wav');self.assertGreater(len(x.read()),100)
   finally:s.stop()
if __name__=='__main__':unittest.main()
