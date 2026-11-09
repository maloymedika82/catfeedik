import type {ReactNode} from 'react';

const icons:ReactNode[]=[
 <svg key="home" viewBox="0 0 24 24" aria-hidden="true"><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>,
 <svg key="map" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>,
 <svg key="profile" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>,
];

export function Dock({page,onChange}:{page:number;onChange:(index:number)=>void}){
 return <nav className="app-dock" aria-label="Разделы приложения">{['Главная','Карта','Профиль'].map((label,index)=><button key={label} type="button" data-dock={index} aria-current={(index===0&&page===0||index===1&&page===3||index===2&&page===2)?'page':undefined} onClick={()=>onChange(index)}>{icons[index]}<span>{label}</span></button>)}</nav>;
}
