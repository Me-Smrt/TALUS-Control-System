from aux_core.conversation import ConversationManager
from aux_core.reasoning import ReasoningPolicy


PROMPT = (
    "I have a circuit reduced to a delta and need to convert it to a wye. "
    "R one through three are twenty-two kilo-ohms, one hundred and eighty ohms, and twenty ohms. "
    "How do I continue with the conversion?"
)


class FakeLlm:
    def __init__(self):
        self.calls = []

    def chat(self, messages, image_jpeg=None, extra_prompt=None, reasoning_mode=None):
        self.calls.append((messages, reasoning_mode))
        if len(self.calls) == 1:
            return "Wait, that's not right. Let me restart the formula mapping."
        return "Use the verified delta-to-wye formulas and the sum of all three delta resistors."

    def stream_chat(self, *args, **kwargs):
        raise AssertionError("quantitative verified turns must not stream the unverified draft")


class Pi:
    def frame(self, *args, **kwargs):
        raise AssertionError("camera not expected")
    def choose_camera(self):
        return "aurora"


class Detector:
    def available(self):
        return False


class State:
    def update(self, *args, **kwargs):
        pass


def test_spoken_quantitative_engineering_problem_auto_selects_deep_and_verification():
    p = ReasoningPolicy({"default_mode": "auto", "auto_score_threshold": 2.75, "quantitative_verification": True})
    d = p.choose(PROMPT)
    assert d.mode == "deep"
    assert d.verification_required is True
    assert "engineering_quantitative" in d.reason


def test_unverified_scratchwork_is_never_streamed_to_user():
    llm = FakeLlm()
    c = ConversationManager(
        {
            "history_turns": 2,
            "visual_keywords": {"en": []},
            "visual_prompt": "",
            "reasoning": {
                "default_mode": "auto",
                "auto_score_threshold": 2.75,
                "quantitative_verification": True,
            },
        },
        llm,
        Pi(),
        Detector(),
        None,
        State(),
    )
    deltas = []
    out = c.handle_text(PROMPT, language="en", on_reply_delta=deltas.append)
    assert out["reasoning_mode"] == "deep"
    assert out["verification_used"] is True
    assert len(llm.calls) == 2
    assert all(mode == "deep" for _, mode in llm.calls)
    assert deltas == ["Use the verified delta-to-wye formulas and the sum of all three delta resistors."]
    assert "Wait" not in "".join(deltas)


def test_budget_instruction_forbids_visible_scratchwork():
    from aux_core.llm import OpenAICompatibleLlm
    text = OpenAICompatibleLlm._budget_instruction(1024)
    assert "scratch work" in text
    assert "self-corrections" in text
    assert "verify the governing formula" in text


def test_forced_deep_buffers_final_answer_instead_of_streaming_hidden_process():
    class DeepLlm:
        def __init__(self): self.chat_calls = 0
        def chat(self, messages, image_jpeg=None, extra_prompt=None, reasoning_mode=None):
            self.chat_calls += 1
            return "A clean final answer."
        def stream_chat(self, *args, **kwargs):
            raise AssertionError("deep mode should be buffered, not token-streamed")
    llm = DeepLlm()
    c = ConversationManager(
        {"history_turns": 2, "visual_keywords": {"en": []}, "visual_prompt": "", "reasoning": {"default_mode": "auto"}},
        llm, Pi(), Detector(), None, State(),
    )
    deltas=[]
    out=c.handle_text("Compare two architectures carefully.", reasoning_mode="deep", on_reply_delta=deltas.append)
    assert out["reasoning_mode"] == "deep"
    assert out["verification_used"] is False
    assert llm.chat_calls == 1
    assert deltas == ["A clean final answer."]
