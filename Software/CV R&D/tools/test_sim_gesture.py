"""Request a named simulation gesture, after checking Pi API reachability."""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

def request(base: str, path: str, token: str, data=None, timeout=5):
    headers={'Accept':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    payload=None if data is None else json.dumps(data).encode('utf-8')
    if payload is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(base+path,data=payload,headers=headers)
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

def main():
    p=argparse.ArgumentParser(description='Safely trigger a Blender-only named gesture')
    p.add_argument('gesture',choices=['wave','nod','shake_head'])
    p.add_argument('--pi-api',default='http://127.0.0.1:8766',help='Pi API URL; localhost means this computer, not a remote Pi')
    p.add_argument('--timeout',type=float,default=5)
    a=p.parse_args();base=a.pi_api.rstrip('/')
    token=os.getenv('AUTOMATON_API_TOKEN','')
    print('Checking Pi behavior API:',base+'/v1/behaviors')
    try:
        status=request(base,'/v1/behaviors',token,timeout=a.timeout)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f'Pi API returned HTTP {exc.code}. Check API token/config and behavior.enabled. ({base})') from None
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise SystemExit(f'Pi behavior API unreachable: {base} ({exc}).\n'
            'Start the CV R&D Pi controller in ANOTHER terminal: python main.py\n'
            'Leave that process running with control_api.enabled=true and without --no-api.\n'
            'Also run the Blender UDP bridge in Blender; it listens on port 8765.\n'
            'If the controller runs on a different machine, use --pi-api http://<PI-IP>:8766\n'
            '(and configure control_api.bind_host and authentication appropriately).') from None
    if status.get('motion_backend')!='blender_simulation_only':
        raise SystemExit('Refusing gesture: backend did not confirm Blender-only simulation. '
                         f'Reported backend: {status.get("motion_backend")!r}')
    result=request(base,'/v1/behaviors',token,{
        'schema':'automaton.aux_intent.v1','request_id':str(uuid.uuid4()),
        'intent':'gesture','parameters':{'name':a.gesture},'ttl_ms':5000,
    },timeout=a.timeout)
    print(json.dumps(result,indent=2))
    print('Request accepted by the broker does not prove Blender received frames. '
          'Check bridge output and simulation_gesture status.')

if __name__=='__main__':main()
