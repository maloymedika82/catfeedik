import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from .local_storage import storage_root,check_space

FORMATS='mov,mp4,m4a,3gp,3g2,mj2,matroska,webm'

class InvalidVideo(ValueError):
    pass


def run(args,timeout=90):
    return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=timeout)


def inspect_video(path):
    try:
        data=json.loads(run([os.getenv('FFPROBE_BIN') or 'ffprobe','-v','error','-protocol_whitelist','file,pipe',
             '-format_whitelist',FORMATS,'-show_entries','format=duration:stream=codec_type,width,height,codec_name',
             '-of','json',str(path)],timeout=20).stdout)
    except subprocess.CalledProcessError:
        raise InvalidVideo('Не удалось прочитать MP4/WebM') from None
    videos=[s for s in data.get('streams',[]) if s['codec_type']=='video']
    audios=[s for s in data.get('streams',[]) if s['codec_type']=='audio']
    try:
        duration=float(data['format']['duration'])
    except (KeyError,ValueError):
        # MediaRecorder's non-seekable WebM commonly omits a Duration header.
        # Scan bounded packet timestamps instead of rejecting valid recordings.
        try:
            packets=json.loads(run([os.getenv('FFPROBE_BIN') or 'ffprobe','-v','error',
                '-protocol_whitelist','file,pipe','-format_whitelist',FORMATS,'-read_intervals','%+#4001',
                '-show_entries','packet=pts_time,duration_time','-of','json',str(path)],timeout=20).stdout)['packets']
            if len(packets)>=4001:
                raise InvalidVideo('Слишком много пакетов в короткой записи')
            duration=max(float(p['pts_time'])+float(p.get('duration_time',0)) for p in packets if 'pts_time' in p)
        except (subprocess.CalledProcessError,KeyError,ValueError):
            raise InvalidVideo('Не удалось проверить длительность видео') from None
    if not math.isfinite(duration) or not 0<duration<=15.5:
        raise InvalidVideo('Длительность должна быть не более 15 секунд (технический допуск 0,5 с)')
    if len(videos)!=1 or not audios:
        raise InvalidVideo('Нужны один видеопоток и звук')
    if not 0<videos[0].get('width',0)<=4096 or not 0<videos[0].get('height',0)<=4096:
        raise InvalidVideo('Недопустимое разрешение исходного видео')
    return duration


def normalize(source,directory):
    duration=inspect_video(source)
    root=storage_root()
    check_space(root,max(source.stat().st_size*3,10*1024*1024))
    output=Path(directory)/'video.mp4'
    poster=Path(directory)/'poster.jpg'
    filters="scale=w='if(gte(iw,ih),1280,720)':h='if(gte(iw,ih),720,1280)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30"
    run([os.getenv('FFMPEG_BIN') or 'ffmpeg','-nostdin','-v','error','-threads','2',
         '-protocol_whitelist','file,pipe','-format_whitelist',FORMATS,'-i',str(source),
         '-map','0:v:0','-map','0:a:0','-map_metadata','-1','-map_metadata:s','-1','-map_chapters','-1',
         '-vf',filters,'-t','15','-c:v','libx264','-preset','veryfast','-crf','25','-pix_fmt','yuv420p',
         '-c:a','aac','-b:a','96k','-movflags','+faststart','-threads','2',str(output)])
    run([os.getenv('FFMPEG_BIN') or 'ffmpeg','-nostdin','-v','error','-i',str(output),
         '-frames:v','1','-vf','scale=480:-2','-map_metadata','-1','-map_metadata:s','-1',str(poster)],timeout=20)
    return output,poster,min(duration,15)


def sample_frames(video,directory):
    prefix=Path(directory)/'frame-%03d.jpg'
    run([os.getenv('FFMPEG_BIN') or 'ffmpeg','-nostdin','-v','error','-i',str(video),
         '-vf','fps=2,scale=480:-2','-frames:v','30','-map_metadata','-1','-map_metadata:s','-1',str(prefix)],timeout=30)
    frames=sorted(Path(directory).glob('frame-*.jpg'))
    if len(frames)>12:
        frames=[frames[round(i*(len(frames)-1)/11)] for i in range(12)]
    return frames
