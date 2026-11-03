import unittest
from aux_core.conversation import ConversationManager
from aux_core.llm import MockLlm
class PI:
 def frame(self,*a,**k):return b'jpeg',{'X-Automaton-Camera':'eye'}
 def choose_camera(self):return 'eye'
class D:
 def available(self):return False
class S:
 def update(self,*a,**k):pass
class T(unittest.TestCase):
 def test_visual_keyword(self):
  c=ConversationManager({'visual_keywords':{'en':['what do you see']},'history_turns':2,'visual_prompt':'look'},MockLlm(),PI(),D(),None,S());o=c.handle_text('what do you see',language='en');self.assertTrue(o['visual_used']);self.assertEqual(o['camera_id'],'eye')
 def test_reply_stream_callback_receives_final_text(self):
  c=ConversationManager({'visual_keywords':{'en':['what do you see']},'history_turns':2,'visual_prompt':'look'},MockLlm(),PI(),D(),None,S())
  chunks=[]
  o=c.handle_text('hello',language='en',on_reply_delta=chunks.append)
  self.assertTrue(chunks)
  self.assertEqual(''.join(chunks).strip(),o['reply'])

if __name__=='__main__':unittest.main()
