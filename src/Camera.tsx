import {useEffect,useRef,useState} from 'react';
import {api,type Config} from './api';
type Stage='intro'|'permissions'|'ready'|'recording'|'preview'|'uploading'|'done';
export function Camera({config,onDone}:{config:Config;onDone:()=>void}){
 const [stage,setStage]=useState<Stage>('intro'),[error,setError]=useState(''),[seconds,setSeconds]=useState(0),[url,setUrl]=useState(''),[permissionStep,setPermissionStep]=useState(''),[status,setStatus]=useState(''),[city,setCity]=useState('');
 const stream=useRef<MediaStream|null>(null),recorder=useRef<MediaRecorder|null>(null),video=useRef<HTMLVideoElement>(null),blob=useRef<Blob|null>(null),location=useRef<GeolocationCoordinates|null>(null),alive=useRef(true),key=useRef(crypto.randomUUID()),feedingId=useRef('');
 function stop(){if(recorder.current?.state==='recording')recorder.current.stop();stream.current?.getTracks().forEach(t=>t.stop());stream.current=null}
 useEffect(()=>{alive.current=true;const hidden=()=>{if(document.hidden){stop();if(alive.current){setError('Запись остановлена при сворачивании приложения.');setStage('intro')}}};document.addEventListener('visibilitychange',hidden);window.Telegram?.WebApp.onEvent('deactivated',hidden);return()=>{alive.current=false;document.removeEventListener('visibilitychange',hidden);window.Telegram?.WebApp.offEvent('deactivated',hidden);stop()}},[]);
 useEffect(()=>()=>{if(url)URL.revokeObjectURL(url)},[url]);
 useEffect(()=>{if(stage!=='recording')return;const started=Date.now();const timer=setInterval(()=>{setSeconds(Math.min(15,Math.floor((Date.now()-started)/1000)))},200);const limit=setTimeout(()=>{if(recorder.current?.state==='recording')recorder.current.stop()},15000);return()=>{clearInterval(timer);clearTimeout(limit)}},[stage]);
 async function open(){setError('');setStage('permissions');let step='location';try{
 if(!navigator.geolocation)throw Error('Геолокация недоступна в этом приложении. Открой Mini App в обновлённом Telegram.');
 setPermissionStep('Определяем местоположение…');
 location.current=await new Promise<GeolocationCoordinates>((resolve,reject)=>navigator.geolocation.getCurrentPosition(p=>resolve(p.coords),e=>reject(Error(e.code===1?'Доступ к геолокации запрещён. Разреши местоположение для Telegram в настройках телефона и приложения, затем вернись и нажми «Открыть камеру». Согласие с условиями не заменяет это разрешение.':e.code===3?'Не удалось определить местоположение за 15 секунд. Проверь, что геолокация включена, и попробуй снова.':'Местоположение недоступно. Включи геолокацию и проверь сигнал GPS.')),{timeout:15000,enableHighAccuracy:true}));
 if(!alive.current||document.hidden)return;
 setPermissionStep('Определяем ближайший город…');
 const resolved=await api<{label:string}>(`/location/city?latitude=${location.current.latitude}&longitude=${location.current.longitude}`);
 if(!alive.current||document.hidden)return;setCity(resolved.label);step='media';
 if(!navigator.mediaDevices?.getUserMedia)throw Error('Для камеры нужен HTTPS и совместимый браузер.');
 setPermissionStep('Открываем камеру и микрофон. Подтверди системный запрос, если он появился.');
 const media=await navigator.mediaDevices.getUserMedia({video:{height:{ideal:720},frameRate:{ideal:30},facingMode:'environment'},audio:true});stream.current=media;
 if(!alive.current||document.hidden){stop();return}setStage('ready');
 }catch(e){stop();if(alive.current){const denied=step==='media'&&e instanceof DOMException&&e.name==='NotAllowedError';setError(denied?'Доступ к камере или микрофону запрещён. Разреши их для Telegram в настройках телефона и приложения, затем попробуй снова.':(e as Error).message);setStage('intro')}}}
 useEffect(()=>{if(stage==='ready'&&video.current)video.current.srcObject=stream.current},[stage]);
 function record(){try{if(!stream.current)throw Error('Камера выключена. Откройте её снова.');const media=stream.current;const mime=['video/mp4;codecs=avc1.42E01E,mp4a.40.2','video/mp4','video/webm;codecs=vp8,opus','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));if(!mime)throw Error('Этот браузер не поддерживает запись видео.');const r=new MediaRecorder(media,{mimeType:mime});const chunks:BlobPart[]=[];recorder.current=r;r.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};r.onstop=()=>{media.getTracks().forEach(t=>t.stop());stream.current=null;if(!alive.current||document.hidden)return;blob.current=new Blob(chunks,{type:r.mimeType});setUrl(URL.createObjectURL(blob.current));setStage('preview')};r.start();setSeconds(0);setStage('recording')}catch(e){setError((e as Error).message);stop();setStage('intro')}}
 async function upload(){if(!blob.current||!location.current)return;setError('');setStage('uploading');try{
 if(!city.trim())throw Error('Укажите город.');const c=location.current,file=blob.current;
 const result=await api<{id:string;status:string;upload_path:string|null}>('/feedings',{method:'POST',body:JSON.stringify({request_key:key.current,city:city.trim(),latitude:c.latitude,longitude:c.longitude,accuracy:c.accuracy,mime_type:file.type.startsWith('video/mp4')?'video/mp4':'video/webm',size:file.size})});feedingId.current=result.id;
 if(result.upload_path){await api(result.upload_path,{method:'PUT',body:file,headers:{'Content-Type':file.type.startsWith('video/mp4')?'video/mp4':'video/webm'}});}
 const completed=await api<{status:string}>(`/feedings/${result.id}/complete`,{method:'POST'});if(alive.current){setStatus(completed.status);setStage('done');onDone()}
 }catch(e){if(alive.current){setError((e as Error).message);setStage('preview')}}}
 return <><div className="eyebrow">Одно видео — одно доброе дело</div><h2>{stage==='done'?'Видео отправлено':'Поделись заботой'}</h2>{error&&<p role="alert" className="error">{error}</p>}
 {stage==='intro'&&<><p>Сними кормление кошки или собаки: корм, животное и процесс поедания должны быть видны. До 15 секунд, без пауз.</p><button className="primary" onClick={open}>Открыть камеру</button></>}
 {stage==='permissions'&&<p role="status">{permissionStep}</p>}
 {(stage==='ready'||stage==='recording')&&<><video ref={video} autoPlay muted playsInline/><p role="timer">{seconds} / 15 секунд</p><button className="primary" onClick={stage==='ready'?record:()=>recorder.current?.stop()}>{stage==='ready'?'Начать запись':'Завершить'}</button></>}
 {(stage==='preview'||stage==='uploading')&&<><video src={url} controls playsInline/><label className="field">Ближайший город<input value={city} readOnly/></label>{!config.max_video_bytes&&<p className="notice">Максимальный размер видео ещё не настроен. Отправка станет доступна после настройки сервера.</p>}{!config.storage_configured&&<p className="notice">Хранилище сервера недоступно. Видео останется на устройстве до закрытия окна.</p>}<button className="primary" onClick={upload} disabled={stage==='uploading'||!config.storage_configured||!config.max_video_bytes}>{stage==='uploading'?'Загружаем…':'Отправить на проверку'}</button><button className="secondary" disabled={stage==='uploading'||!!feedingId.current} onClick={()=>{blob.current=null;setUrl('');key.current=crypto.randomUUID();open()}}>Переснять</button><p style={{fontSize:10}}>Повторная отправка использует ту же сессию. После отправки содержание видео не меняется.</p></>}
 {stage==='done'&&<p>Статус: {status==='REVIEW'?'ожидает ручной проверки':status==='PROCESSING'?'видео обрабатывается':status}. Поинты появятся после подтверждения кормления.</p>}
 </>;
}
