from __future__ import annotations

from aux_core.world_state import WorldState, _iou
from aux_core.engineering import wye_delta_reference


def detection(box, *, label='person', confidence=.95):
    return {'label': label, 'confidence': confidence, 'xyxy': list(box)}


def test_iou_and_ephemeral_identity_and_expiration():
    w = WorldState(current_ms=1000, retention_ms=3000)
    w.update([detection([0,0,100,100]), detection([300,10,380,140], label='cup')],
             camera_id='tracking', now=100.)
    first = w.snapshot(now=100.)
    assert first['current_count'] == 2 and first['person_count'] == 1
    person_id = next(x['id'] for x in first['tracks'] if x['label']=='person')
    w.update([detection([3,2,102,101]), detection([300,10,380,140], label='cup')],
             camera_id='tracking', now=100.5)
    assert next(x['id'] for x in w.snapshot(now=100.5)['tracks'] if x['label']=='person') == person_id
    assert w.snapshot(now=102.5)['current_count'] == 0
    assert all(x['freshness']=='last_seen' for x in w.snapshot(now=102.5)['tracks'])
    assert not w.snapshot(now=104.)['tracks']
    assert _iou([0,0,10,10],[20,20,30,30]) == 0


def test_invalid_detections_and_on_demand_context():
    w=WorldState()
    w.update([detection([0,0,50,60], label='bottle'),
              detection([2,4,10,20], label='noise', confidence=.1),
              {'label':'thing','xyxy':[1,2,float('nan'),9], 'confidence':.9}], camera_id='tracking')
    assert w.context('What is two plus two?') == ''
    assert w.context('Where is the university library?') == ''
    assert 'bottle' in w.context('Where is the bottle?')
    prompt=w.context('What did you see?')
    assert 'bottle' in prompt and 'last_seen' in prompt.casefold()
    assert len(w.snapshot()['tracks'])==1


def test_engineering_terminology_grounding():
    text=wye_delta_reference('How do I perform a Y–Δ transformation of resistors?')
    assert 'R_AB=R_AB' not in text
    assert 'R_A=R_AB*R_CA/S' in text
    assert 'R_AB=P/R_C' in text
    assert wye_delta_reference('How do I translate a spherical coordinate?') == ''


def test_world_endpoint_read_only(tmp_path):
    import json
    import urllib.request
    from aux_core.api_server import AuxApiServer
    from aux_core.state import AuxiliaryState
    from aux_core.tts import TtsManager
    from aux_core.voices import VoiceRegistry

    p=tmp_path
    (p/'voices.json').write_text(json.dumps({'voices':[{'id':'tone','display_name':'Tone',
                                        'backend':'mock','languages':['*'],'enabled':True}]}))
    registry=VoiceRegistry(p/'voices.json',p/'tts_state.json','tone')
    tts=TtsManager({'backends':{'mock':{'type':'mock_tone'}},'speed':1}, registry,p)
    class Conversation:
        world=WorldState()
        def clear_history(self, *_args): pass
    conversation=Conversation()
    api=AuxApiServer({'bind_host':'127.0.0.1','port':0,
                      'allow_unauthenticated_loopback':True},AuxiliaryState(),tts,registry,conversation)
    api.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{api.port}/v1/world',timeout=3) as response:
            payload=json.load(response)
        assert payload['schema']=='talus.world.v1'
        assert payload['status']=='unavailable'
    finally:
        api.stop()
