import {useEffect,useRef} from 'react';
import markup from '../public/dock.html?raw';
import '../public/components/dock/app.css';
export function Dock({onChange}:{onChange:(index:number)=>void}){
 const host=useRef<HTMLDivElement>(null),latest=useRef(onChange);latest.current=onChange;
 useEffect(()=>{const root=host.current!.querySelector('.nav-demo')!;const controller=window.MatteNavigation.mount(root);const life=new AbortController();root.querySelectorAll<HTMLButtonElement>('[data-dock]').forEach((b,i)=>b.addEventListener('click',()=>latest.current(i),{signal:life.signal}));return()=>{life.abort();controller.destroy()}},[]);
 return <div ref={host} dangerouslySetInnerHTML={{__html:markup}}/>;
}
