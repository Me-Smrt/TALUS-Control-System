from aux_core.conversation import ConversationManager


class _Pi:
    def choose_camera(self):
        return "eye"


class _Detector:
    def available(self):
        return False


class _State:
    def update(self, *args, **kwargs):
        pass


class _KnowledgeNoHit:
    def query_diagnostics(self, query):
        return {"attempted": True, "intents": [], "query_terms": ["printing", "aieb"]}

    def retrieve(self, query):
        return []

    def format_context(self, hits):
        return ""


class _CaptureLlm:
    def __init__(self):
        self.extra_prompt = None

    def begin_turn_metrics(self):
        pass

    def end_turn_metrics(self):
        return {}

    def chat(self, messages, **kwargs):
        self.extra_prompt = kwargs.get("extra_prompt")
        return "I do not have enough local information."


def test_attempted_campus_lookup_with_no_hits_is_explicitly_grounded():
    llm = _CaptureLlm()
    c = ConversationManager(
        {"history_turns": 2, "visual_keywords": {}, "reasoning": {}, "action_router": {}},
        llm,
        _Pi(),
        _Detector(),
        None,
        _State(),
        knowledge=_KnowledgeNoHit(),
    )
    c.handle_text("Are there printers near the AIEB?", language="en")
    assert "no relevant curated excerpt was found" in llm.extra_prompt
    assert "Do not invent campus locations" in llm.extra_prompt
