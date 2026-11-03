from aux_core.knowledge import LocalKnowledgeBase


def test_identity_small_talk_terms_do_not_trigger_contact_searches():
    terms = LocalKnowledgeBase._query_terms("You can call me Tyler. Sure, sounds good!")
    assert "call" not in terms
    assert "sure" not in terms
    assert "sounds" not in terms
    assert terms == ["tyler"]
