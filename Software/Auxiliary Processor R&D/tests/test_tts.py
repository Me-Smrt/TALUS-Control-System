import unittest,wave,io
from aux_core.tts import MockToneBackend
class T(unittest.TestCase):
 def test_wav(self):
  b=MockToneBackend().synthesize('hello',{});w=wave.open(io.BytesIO(b),'rb');self.assertEqual(w.getnchannels(),1);self.assertGreater(w.getnframes(),100)
if __name__=='__main__':unittest.main()
