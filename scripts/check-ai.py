"""Two tiny real vision requests; no feeding, publication or points are created."""
import base64
import json
import os
from pathlib import Path
import secrets
import struct
import sys
import tempfile
import zlib
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.settings import load_environment
load_environment()
from backend.ai import configured,base_url,resolve_model,moderate,ProviderUnavailable


def make_grid():
    palette={'red':(255,0,0),'green':(0,255,0),'blue':(0,0,255),
             'yellow':(255,255,0),'black':(0,0,0),'white':(255,255,255)}
    expected=[secrets.choice(list(palette)) for _ in range(9)]
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\x00'+b''.join(bytes(palette[expected[(y//32)*3+x//32]]) for x in range(96)) for y in range(96))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',96,96,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
    return png,expected


def main():
    if not configured():
        print('FAIL: AI_API_KEY is missing. Add it to your private .env; do not send it in chat.')
        return 1
    print('Checking vision using two small requests. No feeding or points are created; keys are not printed.')
    try:
        png,expected=make_grid()
        with httpx.Client(timeout=60,follow_redirects=False) as client:
            model=resolve_model(client)
            response=client.post(base_url()+'/chat/completions',headers={'Authorization':'Bearer '+os.environ['AI_API_KEY']},json={
                'model':model,'temperature':0,'max_tokens':200,'response_format':{'type':'json_object'},
                'messages':[{'role':'user','content':[
                    {'type':'text','text':'Read the attached 3-by-3 color grid. Return only JSON with cells: an array of exactly nine lowercase color names in row-major order (left to right, top to bottom). Choose from red, green, blue, yellow, black, white. Determine the colors only from the image.'},
                    {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode(),'detail':'low'}}]}]})
            response.raise_for_status()
            actual=json.loads(response.json()['choices'][0]['message']['content']).get('cells')
            print('Model: '+model)
            if actual!=expected:
                print('FAIL: provider answered, but the random visual challenge was not read correctly. Image support is not confirmed.')
                return 1
            print('PASS: model correctly read all nine randomly generated image cells.')
            with tempfile.TemporaryDirectory(prefix='catfeedik-ai-check-') as directory:
                image=Path(directory)/'grid.png';image.write_bytes(png)
                result=moderate([image],client)
        if result is None:
            print('FAIL: moderation is not configured.')
            return 1
        print(json.dumps({'model':result.provider_model,'decision':result.decision,'confidence':result.confidence,
                          'animal_visible':result.animal_visible,'food_visible':result.food_visible,
                          'eating_visible':result.eating_visible},ensure_ascii=True,indent=2))
        if result.decision=='APPROVE' or result.animal_visible or result.food_visible or result.eating_visible:
            print('FAIL: model reported feeding evidence in a color grid. Automatic moderation needs investigation.')
            return 1
        print('PASS: vision and structured moderation work. Test image was not approved. No points were awarded.')
        return 0
    except httpx.HTTPStatusError as error:
        print(f'FAIL: provider returned HTTP {error.response.status_code}. Check model, key permissions and balance. Response body was not printed.')
        return 1
    except ProviderUnavailable as error:
        print('FAIL: '+str(error))
        return 1
    except Exception:
        print('FAIL: could not validate the provider response. Credentials and response bodies were not printed.')
        return 1

if __name__=='__main__':
    raise SystemExit(main())
