import {useEffect,useRef,useState,type FormEvent} from 'react';
import {api,type User} from './api';
import {applicationLabels,sponsorDate,type Sponsor,type SponsorTask,type TaskApplication,type TaskStatus} from './sponsorTypes';
import './sponsors.css';

export function SponsorLogo({name,url}:{name:string;url:string}){
 const [failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[url]);
 return <span className="partner-logo">{url&&!failed?<img src={url} alt={name} loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>:name.split(/\s+/).slice(0,2).map(word=>word[0]).join('').toUpperCase()}</span>;
}

export function Sponsors({user,onUpdated}:{user:User|null;onUpdated:()=>Promise<void>}){
 const [items,setItems]=useState<Sponsor[]>([]),[more,setMore]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const [selectedSponsorId,setSelectedSponsorId]=useState<string|null>(null);
 const [statuses,setStatuses]=useState<Record<string,TaskStatus>>({}),[history,setHistory]=useState<TaskApplication[]>([]),[historyMore,setHistoryMore]=useState(false);
 const [selected,setSelected]=useState<SponsorTask|null>(null),[evidence,setEvidence]=useState(''),[url,setUrl]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const request=useRef<{key:string;task:string;evidence:string;url:string;terms:string}|null>(null),seen=useRef<Record<string,TaskStatus>>({}),editor=useRef<HTMLElement>(null);
 useEffect(()=>{
  let live=true;setLoading(true);setError('');setHistory([]);setStatuses({});seen.current={};setSelected(null);request.current=null;
  async function load(){try{
   const catalog=await api<{items:Sponsor[];has_more:boolean}>('/sponsors');if(!live)return;setItems(catalog.items);setMore(catalog.has_more);
   if(user){const [states,applications]=await Promise.all([api<TaskStatus[]>('/me/task-statuses'),api<{items:TaskApplication[];has_more:boolean}>('/me/task-applications')]);if(!live)return;const map=Object.fromEntries(states.map(s=>[s.task_id,s]));seen.current=map;setStatuses(map);setHistory(applications.items);setHistoryMore(applications.has_more)}
  }catch(e){if(live)setError((e as Error).message)}finally{if(live)setLoading(false)}}load();return()=>{live=false};
 },[user?.id]);
 useEffect(()=>{if(selected){editor.current?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});editor.current?.querySelector('textarea')?.focus({preventScroll:true})}},[selected?.id]);
 const pending=Object.values(statuses).some(s=>s.status==='PENDING');
 useEffect(()=>{
  if(!user||!pending)return;let live=true;
  const timer=setInterval(async()=>{try{
   const [states,applications]=await Promise.all([api<TaskStatus[]>('/me/task-statuses'),api<{items:TaskApplication[];has_more:boolean}>('/me/task-applications')]);if(!live)return;
   const changed=states.some(s=>s.status==='APPROVED'&&seen.current[s.task_id]?.status==='PENDING');
   const map=Object.fromEntries(states.map(s=>[s.task_id,s]));seen.current=map;setStatuses(map);
   setHistory(old=>[...applications.items,...old.filter(a=>!applications.items.some(newer=>newer.id===a.id))]);setHistoryMore(applications.has_more);
   if(changed)await onUpdated();
  }catch(e){if(live)setError((e as Error).message)}},10000);
  return()=>{live=false;clearInterval(timer)};
 },[user?.id,pending,onUpdated]);
 async function loadMore(){try{const result=await api<{items:Sponsor[];has_more:boolean}>(`/sponsors?offset=${items.length}`);setItems(old=>[...old,...result.items]);setMore(result.has_more)}catch(e){setError((e as Error).message)}}
 async function moreTasks(sponsor:Sponsor){try{const result=await api<{items:SponsorTask[];has_more:boolean}>(`/sponsors/${sponsor.id}/tasks?offset=${sponsor.tasks.length}`);setItems(old=>old.map(s=>s.id===sponsor.id?{...s,tasks:[...s.tasks,...result.items],tasks_has_more:result.has_more}:s))}catch(e){setError((e as Error).message)}}
 async function moreHistory(){try{const result=await api<{items:TaskApplication[];has_more:boolean}>(`/me/task-applications?offset=${history.length}`);setHistory(old=>[...old,...result.items]);setHistoryMore(result.has_more)}catch(e){setError((e as Error).message)}}
 async function submit(event:FormEvent){
  event.preventDefault();if(!selected)return;setBusy(true);setMessage('');setError('');
  try{
   const old=request.current;if(!old||old.task!==selected.id||old.evidence!==evidence||old.url!==url||old.terms!==selected.terms_hash)request.current={key:crypto.randomUUID(),task:selected.id,evidence,url,terms:selected.terms_hash};
   const application=await api<TaskApplication>(`/tasks/${selected.id}/applications`,{method:'POST',body:JSON.stringify({request_key:request.current!.key,terms_hash:selected.terms_hash,evidence,evidence_url:url})});
   request.current=null;setHistory(old=>[application,...old.filter(a=>a.id!==application.id)]);
   const status:TaskStatus={id:application.id,task_id:application.task_id,status:application.status,review_reason:application.review_reason,reward_points:application.reward_points};
   seen.current={...seen.current,[selected.id]:status};setStatuses(old=>({...old,[selected.id]:status}));setSelected(null);setEvidence('');setUrl('');setMessage('Заявка отправлена. Поинты появятся после подтверждения Owner.');
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 return <section className="sponsors-page"><div className="section-intro"><div className="eyebrow">Спонсоры</div><h1>{selectedSponsorId?'О спонсоре':'Партнёры проекта'}</h1><p>{selectedSponsorId?'Предложения и задания этого партнёра.':'Познакомься со спонсорами и их заданиями.'}</p></div>
 {error&&<p role="alert" className="error">{error}</p>}{message&&<p role="status" className="notice">{message}</p>}{loading&&<p role="status">Загружаем партнёров…</p>}
 {!loading&&!items.length&&<section className="panel empty"><h2>Спонсоры появятся здесь</h2><p>Когда партнёры присоединятся к проекту, здесь будут их страницы и задания.</p></section>}
 {user?.frozen&&<p className="notice">Аккаунт заморожен. Новые заявки и начисления приостановлены; история остаётся доступна.</p>}
 {selectedSponsorId&&<button className="text-button" onClick={()=>{setSelectedSponsorId(null);setSelected(null)}}>← Все спонсоры</button>}
 <div className="partner-list">{items.filter(sponsor=>!selectedSponsorId||sponsor.id===selectedSponsorId).map(sponsor=><article className="panel partner-card" key={sponsor.id}><div className="partner-heading"><SponsorLogo name={sponsor.name} url={sponsor.logo_url}/><div><h2>{sponsor.name}</h2><p>{sponsor.description}</p></div></div>
 {!selectedSponsorId?<button className="secondary" onClick={()=>setSelectedSponsorId(sponsor.id)}>О спонсоре</button>:<><h3>Задания спонсора</h3>{sponsor.tasks.length?sponsor.tasks.map(task=>{const state=statuses[task.id];return <section className="partner-task" key={task.id}><div className="task-title"><h3>{task.title}</h3>{task.reward_points>0&&<span className="badge">+{task.reward_points} поинтов</span>}</div><p className="task-conditions">{task.conditions}</p><small>{task.deadline_at>0?`Отправить до ${sponsorDate(task.deadline_at)} · `:''}проверяет Owner вручную</small>
 {state&&<p className="task-state">{applicationLabels[state.status]}{state.status==='APPROVED'?` · +${state.reward_points}`:''}{state.review_reason&&<small>{state.review_reason}</small>}</p>}
 <button className="secondary" disabled={!user||user.frozen||busy||state?.status==='PENDING'||state?.status==='APPROVED'} onClick={()=>{setSelected(task);setEvidence('');setUrl('');setMessage('');setError('');request.current=null}}>{!user?'Для участия войди через Telegram':state?.status==='PENDING'?'Заявка на проверке':state?.status==='APPROVED'?'Награда получена':state?.status==='REJECTED'?'Отправить новую попытку':'Подробнее'}</button></section>}):<p className="notice">Пока нет заданий. Новые задания появятся на этой странице.</p>}</>}
 {selectedSponsorId&&sponsor.tasks_has_more&&<button className="secondary" onClick={()=>moreTasks(sponsor)}>Ещё задания</button>}</article>)}</div>
 {!selectedSponsorId&&more&&<button className="secondary" onClick={loadMore}>Ещё спонсоры</button>}
 {selected&&<section className="panel history task-application-form" ref={editor}><h2>{selected.title}</h2><p className="task-conditions">{selected.conditions}</p><p className="notice">Опиши выполнение и добавь HTTPS-ссылку, если она нужна по условиям. Проверка ручная. Отправка заявки сама по себе не начисляет поинты.</p><form onSubmit={submit}><label className="field">Как выполнено задание<textarea required minLength={10} maxLength={4000} disabled={busy} value={evidence} onChange={e=>setEvidence(e.target.value)}/></label><label className="field">Ссылка на подтверждение (необязательно)<input type="url" placeholder="https://…" maxLength={2048} disabled={busy} value={url} onChange={e=>setUrl(e.target.value)}/></label><button className="primary" disabled={busy||evidence.trim().length<10}>{busy?'Отправляем…':'Отправить заявку'}</button><button className="secondary" type="button" disabled={busy} onClick={()=>setSelected(null)}>Отмена</button></form></section>}
 {user&&<section className="panel history task-history"><h2>Мои заявки</h2>{!history.length&&<p>Ты ещё не отправлял заявки на задания.</p>}{history.map(a=><article className="history-row" key={a.id}><div><strong>{a.task_title}</strong><small>{a.sponsor_name} · попытка {a.attempt} · {sponsorDate(a.created_at)}</small>{a.review_reason&&<small>{a.review_reason}</small>}</div><span>{applicationLabels[a.status]}{a.status==='APPROVED'&&<small>+{a.reward_points} поинтов</small>}</span></article>)}{historyMore&&<button className="secondary" onClick={moreHistory}>Ещё заявки</button>}</section>}
 </section>;
}
