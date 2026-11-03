from __future__ import annotations
import json,os,secrets,threading,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from .system_health import SystemHealthSampler

class AuxApiServer:
    def __init__(self,cfg,state,tts,voices,conversation,knowledge=None,person_session=None,telemetry=None):
        self.cfg=cfg;self.state=state;self.tts=tts;self.voices=voices;self.conversation=conversation;self.knowledge=knowledge;self.person_session=person_session;self.telemetry=telemetry
        self.health=SystemHealthSampler()
        self.host=str(cfg.get('bind_host','127.0.0.1'));self.port=int(cfg.get('port',8770));self.token=os.getenv(str(cfg.get('token_env','AUTOMATON_AUX_API_TOKEN')),'').strip();self.allow_loopback=bool(cfg.get('allow_unauthenticated_loopback',True));self._server=None;self._thread=None
        if self.host not in {'127.0.0.1','localhost','::1'} and not self.token:raise RuntimeError('Refusing LAN bind without AUTOMATON_AUX_API_TOKEN')
    def start(self):
        outer=self
        class H(BaseHTTPRequestHandler):
            server_version='AutomatonAuxAPI/0.5.0'
            def log_message(self,fmt,*args):
                if outer.cfg.get('access_log',False):super().log_message(fmt,*args)
            def auth(self):
                if outer.token:
                    h=self.headers.get('Authorization','');s=h[7:] if h.startswith('Bearer ') else '';return bool(s and secrets.compare_digest(s,outer.token))
                return outer.allow_loopback and self.client_address[0] in {'127.0.0.1','::1'}
            def js(self,status,obj):
                b=json.dumps(obj,separators=(',',':'),ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
            def body(self,maxn=16384):
                n=int(self.headers.get('Content-Length','0') or 0)
                if n<0 or n>maxn:raise ValueError('request_too_large')
                return json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
            def do_GET(self):
                if not self.auth():return self.js(401,{'error':'unauthorized'})
                p=urllib.parse.urlsplit(self.path).path.rstrip('/') or '/'
                if p=='/v1/health':
                    snap=outer.state.snapshot()
                    return self.js(200,{
                        'schema':'automaton.aux_health.v1',
                        'status':snap.get('status'),
                        'version':snap.get('service_version'),
                        'uptime_s':snap.get('uptime_s'),
                        'system':outer.health.sample(),
                    })
                if p=='/v1/status':return self.js(200,outer.state.snapshot())
                if p=='/v1/world':
                    world=getattr(outer.conversation,'world',None)
                    return self.js(200,world.snapshot() if world is not None else {'status':'unavailable','tracks':[]})
                if p=='/v1/voices':return self.js(200,{'active_voice_id':outer.voices.active_id,'active_voice_set_id':outer.voices.active_set_id,'voice_sets':outer.tts.list_voice_sets(),'voices':outer.tts.list_voices()})
                if p=='/v1/knowledge/status':
                    return self.js(200,outer.knowledge.status() if outer.knowledge is not None else {'enabled':False,'available':False})
                if p=='/v1/telemetry':
                    return self.js(200,outer.telemetry.snapshot() if outer.telemetry is not None else {'schema':'automaton.aux_telemetry.v1','enabled':False})
                if p=='/v1/people/status':
                    return self.js(200,outer.person_session.status() if outer.person_session is not None else {'enabled':False})
                if p=='/v1/contract':return self.js(200,{
                    'schema':'automaton.aux_api.v1',
                    'endpoints':['GET /v1/health','GET /v1/status','GET /v1/voices','GET /v1/knowledge/status','GET /v1/telemetry','GET /v1/world','GET /v1/people/status','POST /v1/voices/select','POST /v1/voice-sets/select','POST /v1/tts/synthesize','POST /v1/conversation/text','POST /v1/conversation/reset','POST /v1/vision/ask','POST /v1/people/enroll','POST /v1/people/remember','POST /v1/people/forget_current'],
                    'conversation_reasoning_modes':['auto','fast','deep'],
                    'safety_authority':False,'direct_servo_control':False
                })
                return self.js(404,{'error':'not_found'})
            def do_POST(self):
                if not self.auth():return self.js(401,{'error':'unauthorized'})
                p=urllib.parse.urlsplit(self.path).path.rstrip('/') or '/'
                try:data=self.body(32768)
                except Exception as e:return self.js(400,{'error':'invalid_json','detail':str(e)})
                try:
                    if p=='/v1/voices/select':
                        vid=str(data.get('voice_id',''));outer.voices.set_active(vid);v=outer.voices.get();outer.state.update('voice',active_id=vid,active_set_id=None,backend=v.get('backend'),available=outer.tts.voice_status(v));return self.js(200,{'ok':True,'active_voice_id':vid,'active_voice_set_id':None})
                    if p=='/v1/voice-sets/select':
                        sid=str(data.get('voice_set_id',''));outer.voices.set_active_set(sid)
                        preview,backend=outer.tts._select_voice('en',voice_set_id=sid)
                        outer.state.update('voice',active_id=preview.get('id'),active_set_id=sid,backend=preview.get('backend'),available=True)
                        return self.js(200,{'ok':True,'active_voice_id':outer.voices.active_id,'active_voice_set_id':sid})
                    if p=='/v1/tts/synthesize':
                        text=str(data.get('text','')).strip();
                        if not text or len(text)>1000:return self.js(400,{'error':'invalid_text'})
                        wav,voice=outer.tts.synthesize(text,voice_id=data.get('voice_id'),voice_set_id=data.get('voice_set_id'),language=data.get('language'),speed=data.get('speed'))
                        self.send_response(200);self.send_header('Content-Type','audio/wav');self.send_header('Content-Length',str(len(wav)));self.send_header('Cache-Control','no-store');self.send_header('X-Automaton-Voice-Id',voice['id']);self.send_header('X-Automaton-Voice-Set-Id',str(data.get('voice_set_id') or outer.voices.active_set_id or ''));self.end_headers();self.wfile.write(wav);return
                    if p=='/v1/conversation/reset':
                        reason=str(data.get('reason','api_reset')).strip() or 'api_reset'
                        outer.conversation.clear_history(reason);return self.js(200,{'ok':True,'history_messages':0,'reason':reason})
                    if p=='/v1/people/enroll':
                        if outer.person_session is None:return self.js(503,{'error':'identity_unavailable'})
                        name=str(data.get('name','')).strip()
                        if not name:return self.js(400,{'error':'invalid_name'})
                        return self.js(200,{'ok':True,'person':outer.person_session.enroll_current(name)})
                    if p=='/v1/people/remember':
                        if outer.person_session is None:return self.js(503,{'error':'identity_unavailable'})
                        memory=str(data.get('text','')).strip()
                        if not memory:return self.js(400,{'error':'invalid_text'})
                        return self.js(200,{'ok':True,'memory':outer.person_session.remember_current(memory)})
                    if p=='/v1/people/forget_current':
                        if outer.person_session is None:return self.js(503,{'error':'identity_unavailable'})
                        return self.js(200,{'ok':True,'removed':outer.person_session.forget_current()})
                    if p in {'/v1/conversation/text','/v1/vision/ask'}:
                        gate=getattr(outer.conversation,'startup_gate',None)
                        if gate is not None and not gate.ready:
                            return self.js(503,{'error':'startup_not_ready','phase':gate.phase})
                        text=str(data.get('text','')).strip();
                        if not text or len(text)>4000:return self.js(400,{'error':'invalid_text'})
                        reasoning_mode=str(data.get('reasoning_mode','auto')).lower()
                        if reasoning_mode not in {'auto','fast','deep'}:return self.js(400,{'error':'invalid_reasoning_mode'})
                        out=outer.conversation.handle_text(text,language=data.get('language'),force_vision=(p=='/v1/vision/ask'),camera_id=data.get('camera_id'),reasoning_mode=reasoning_mode);return self.js(200,out)
                except KeyError:return self.js(404,{'error':'unknown_voice'})
                except ValueError as e:return self.js(400,{'error':str(e)})
                except Exception as e:return self.js(503,{'error':'backend_unavailable','detail':str(e)})
                return self.js(404,{'error':'not_found'})
        self._server=ThreadingHTTPServer((self.host,self.port),H);self.port=self._server.server_address[1];self._thread=threading.Thread(target=self._server.serve_forever,daemon=True,name='aux-api');self._thread.start()
    def stop(self):
        try:self.conversation.clear_history('api_server_stop')
        except Exception:pass
        if self._server:self._server.shutdown();self._server.server_close();self._server=None
        if self._thread:self._thread.join(timeout=2);self._thread=None
