import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import type {City} from './WorldMap';
type Item={id:string;name:string;city:string;created_at:number;video_url:string;poster_url:string;likes:number;liked?:boolean};
function VideoCard({item,canLike}:{item:Item;canLike:boolean}){
 const video=useRef<HTMLVideoElement>(null),card=useRef<HTMLElement>(null);
 const [likes,setLikes]=useState(item.likes),[liked,setLiked]=useState(item.liked??false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(!entries[0].isIntersecting)video.current?.pause()},{threshold:.6});if(card.current)observer.observe(card.current);return()=>{observer.disconnect();video.current?.pause()}},[]);
 async function toggle(){setBusy(true);setError('');try{const result=await api<{liked:boolean;likes:number}>(`/feedings/${item.id}/like`,{method:liked?'DELETE':'PUT'});setLikes(result.likes);setLiked(result.liked)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <article className="feed-video-card" ref={card}><video ref={video} src={item.video_url} poster={item.poster_url} controls playsInline preload="none"/><div className="feed-video-meta"><div><strong>{item.name}</strong><small>{new Date(item.created_at*1000).toLocaleDateString('ru-RU')} · {item.city}</small></div><button disabled={!canLike||busy} aria-pressed={liked} aria-label={liked?'Убрать лайк':'Поставить лайк'} onClick={toggle}><svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" fill={liked?'currentColor':'none'} aria-hidden="true"><path d="M12 20S3 14.5 3 8.5C3 3 9 2 12 6c3-4 9-3 9 2.5C21 14.5 12 20 12 20Z"/></svg>{likes}</button></div>{!canLike&&<small className="feed-signin-note">Лайки доступны после входа через Telegram</small>}{error&&<p role="alert">{error}</p>}</article>;
}
export function CityFeed({city,canLike}:{city:City;canLike:boolean}){
 const [items,setItems]=useState<Item[]>([]),[more,setMore]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),offset=useRef(0);
 async function load(reset=false){setBusy(true);setError('');try{const result=await api<{items:Item[];has_more:boolean}>(`/feed?city_id=${encodeURIComponent(city.id)}&offset=${reset?0:offset.current}`);const liked=canLike?new Set(await api<string[]>('/me/likes')):new Set<string>();const incoming=result.items.map(item=>({...item,liked:liked.has(item.id)}));setItems(old=>reset?incoming:[...old,...incoming]);offset.current=(reset?0:offset.current)+result.items.length;setMore(result.has_more)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 useEffect(()=>{load(true)},[city.id]);
 return <div className="city-feed"><div className="eyebrow">Публичная лента · только одобренные видео</div><h2>{city.label}</h2>{error&&<p role="alert" className="error">{error}</p>}{!busy&&!items.length&&!error&&<p>В этом городе пока нет опубликованных видео.</p>}<div className="feed-scroll">{items.map(item=><VideoCard key={item.id} item={item} canLike={canLike}/>)}</div>{busy&&<p role="status">Загружаем видео…</p>}{(more||error)&&<button className="secondary" onClick={()=>load()} disabled={busy}>{error?'Повторить':'Ещё видео'}</button>}</div>;
}
