import unittest
from aux_core.reasoning import ReasoningPolicy, ThinkingCueSequence

class ReasoningTests(unittest.TestCase):
    def setUp(self):
        self.cfg={'default_mode':'auto','auto_min_chars':40,'deep_keywords':['think deeply','root cause'],'waiting_lines':['a','b'],'initial_wait_s':1,'repeat_wait_s':2,'max_wait_cues':3}
    def test_default_is_fast(self):
        d=ReasoningPolicy(self.cfg).choose('hello there')
        self.assertEqual(d.mode,'fast')
    def test_keyword_selects_deep(self):
        d=ReasoningPolicy(self.cfg).choose('Please think deeply about this')
        self.assertEqual(d.mode,'deep')
    def test_force_overrides_auto(self):
        d=ReasoningPolicy(self.cfg).choose('think deeply please','fast')
        self.assertEqual(d.mode,'fast')
    def test_cue_schedule(self):
        s=list(ThinkingCueSequence(self.cfg).schedule())
        self.assertEqual([x[0] for x in s],[1.0,3.0,5.0]);self.assertEqual(len(s),3)

if __name__=='__main__':unittest.main()
