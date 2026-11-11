import {useEffect,useState} from 'react';
import {api} from './api';
import {SponsorLogo} from './Sponsors';
import type {Sponsor} from './sponsorTypes';

export function SponsorPreview({onOpen}:{onOpen:()=>void}){
 const [items,setItems]=useState<Sponsor[]>([]);
 useEffect(()=>{let live=true;api<{items:Sponsor[]}>('/sponsors?limit=2').then(result=>{if(live)setItems(result.items)}).catch(()=>{});return()=>{live=false}},[]);
 return <section className="home-sponsors" aria-label="Спонсоры"><div className="panel-head"><h2>Спонсоры</h2><button className="text-button" onClick={onOpen}>Все →</button></div>{items.length?<div className="home-sponsor-cards">{items.map(item=><article className="panel partner-card" key={item.id}><div className="partner-heading"><SponsorLogo name={item.name} url={item.logo_url}/><div><h3>{item.name}</h3><small>Партнёр Catfeedik</small></div></div><p>{item.description}</p><button className="secondary" onClick={onOpen}>О спонсоре</button></article>)}</div>:<p className="notice">Спонсоры появятся здесь, когда первые партнёры присоединятся к проекту.</p>}</section>;
}
