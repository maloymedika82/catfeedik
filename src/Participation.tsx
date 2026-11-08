import {useEffect,useState} from 'react';
import {api,type Config} from './api';
import {Camera} from './Camera';
type Terms={version:string;document_hash:string;title:string;paragraphs:string[];accepted?:boolean};
function TermsText({terms}:{terms:Terms}){return <><h2>{terms.title}</h2><small>Версия {terms.version}</small><div className="participation-text">{terms.paragraphs.map((text,i)=><p key={i}>{text}</p>)}</div></>}
export function ParticipationTerms(){
 const [terms,setTerms]=useState<Terms|null>(null),[error,setError]=useState('');
 useEffect(()=>{let live=true;api<Terms>('/participation-terms').then(value=>{if(live)setTerms(value)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[]);
 return <>{error?<p role="alert" className="error">{error}</p>:terms?<TermsText terms={terms}/>:<p role="status">Загружаем условия…</p>}</>;
}
export function ParticipationCamera({config,onDone,onCancel}:{config:Config;onDone:()=>void;onCancel:()=>void}){
 const [terms,setTerms]=useState<Terms|null>(null),[error,setError]=useState(''),[checked,setChecked]=useState(false),[busy,setBusy]=useState(false),[retry,setRetry]=useState(0);
 useEffect(()=>{let live=true;setError('');api<Terms>('/me/participation-consent').then(value=>{if(live)setTerms(value)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[retry]);
 async function accept(){if(!terms||!checked)return;setBusy(true);setError('');try{setTerms(await api<Terms>('/me/participation-consent',{method:'POST',body:JSON.stringify({version:terms.version,document_hash:terms.document_hash,accepted:true})}))}catch(e){setError((e as Error).message);setChecked(false)}finally{setBusy(false)}}
 if(terms?.accepted)return <Camera config={config} onDone={onDone}/>;
 return <section className="participation"><div className="eyebrow">Перед первым кормлением</div>{terms?<TermsText terms={terms}/>:!error&&<p role="status">Загружаем условия…</p>}{error&&<p role="alert" className="error">{error}</p>}{terms&&<><label className="consent-check"><input type="checkbox" checked={checked} disabled={busy} onChange={e=>setChecked(e.target.checked)}/><span>Я прочитал(а) условия участия и согласен(на) с описанным использованием видео, звука, выбранного города и данных профиля.</span></label><p className="notice">Сохраним согласие для твоего профиля. Доступ к точному местоположению не требуется.</p><button className="primary" disabled={!checked||busy} onClick={accept}>{busy?'Сохраняем…':'Принять и продолжить'}</button></>}{error&&<button className="secondary" disabled={busy} onClick={()=>{setTerms(null);setChecked(false);setRetry(n=>n+1)}}>Обновить условия</button>}<button className="text-button" disabled={busy} onClick={onCancel}>Пока только посмотреть карту</button></section>;
}
