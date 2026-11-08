"""Small perceptual video signature used only to route possible repeats to review."""
import json
import os
import subprocess


FRAME_BYTES=9*8


def frame_hash(frame):
    if len(frame)!=FRAME_BYTES:
        raise ValueError('Invalid fingerprint frame')
    result=0
    for row in range(8):
        pixels=frame[row*9:(row+1)*9]
        for column in range(8):
            result=(result<<1)|int(pixels[column]>pixels[column+1])
    return result


def video_fingerprint(video):
    result=subprocess.run([os.getenv('FFMPEG_BIN') or 'ffmpeg','-nostdin','-v','error','-threads','1',
        '-i',str(video),'-an','-vf','fps=1,scale=9:8,format=gray','-frames:v','15',
        '-f','rawvideo','-pix_fmt','gray','pipe:1'],capture_output=True,check=True,timeout=30)
    data=result.stdout
    if not data or len(data)%FRAME_BYTES:
        raise ValueError('Unable to fingerprint video')
    return [f'{frame_hash(data[index:index+FRAME_BYTES]):016x}' for index in range(0,len(data),FRAME_BYTES)]


def similar(left,right):
    try:
        a=[int(value,16) for value in left]
        b=[int(value,16) for value in right]
    except (TypeError,ValueError):
        return False
    if len(a)<3 or len(b)<3:
        return False
    used=set();matches=0
    for value in a:
        candidate=next((index for index,other in enumerate(b)
                        if index not in used and (value^other).bit_count()<=6),None)
        if candidate is not None:
            used.add(candidate);matches+=1
    return matches>=max(3,min(len(a),len(b))//2)


def has_similar(db,asset_class,fingerprint,exclude_id):
    from sqlalchemy import select
    rows=db.scalars(select(asset_class).where(asset_class.status=='READY',
        asset_class.feeding_id!=exclude_id,asset_class.fingerprint!='[]'))
    for row in rows:
        try:
            if similar(fingerprint,json.loads(row.fingerprint)):
                return True
        except (TypeError,ValueError):
            continue
    return False
