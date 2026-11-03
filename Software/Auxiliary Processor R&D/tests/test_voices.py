import json,tempfile,unittest
from pathlib import Path
from aux_core.voices import VoiceRegistry
class T(unittest.TestCase):
 def test_persist(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); (p/'v.json').write_text(json.dumps({'voices':[{'id':'a','enabled':True,'languages':['en']},{'id':'b','enabled':True,'languages':['fr']}],'fallback_language_voice':{'fr':'b'}}))
   r=VoiceRegistry(p/'v.json',p/'state.json','a'); self.assertEqual(r.active_id,'a');r.set_active('b');self.assertEqual(VoiceRegistry(p/'v.json',p/'state.json','a').active_id,'b')
 def test_language_fallback(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'v.json').write_text(json.dumps({'voices':[{'id':'a','enabled':True,'languages':['en']},{'id':'b','enabled':True,'languages':['fr']}],'fallback_language_voice':{'fr':'b'}}));r=VoiceRegistry(p/'v.json',p/'s.json','a');self.assertEqual(r.choose_for_language('fr-FR')['id'],'b')
if __name__=='__main__':unittest.main()
