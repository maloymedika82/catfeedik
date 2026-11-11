import type {ReactNode} from 'react';

const icons:ReactNode[]=[
 <svg key="home" viewBox="0 0 24 24" aria-hidden="true"><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>,
 <svg key="sponsors" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-8-5.6-8-11.4A4.6 4.6 0 0 1 12 6.5a4.6 4.6 0 0 1 8 3.1C20 15.4 12 21 12 21Z"/></svg>,
 <svg key="profile" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>,
];

export function Dock({page,onChange}:{page:number;onChange:(index:number)=>void}){
 return <nav className="app-dock" aria-label="Разделы приложения">{['Главная','Спонсоры','Профиль'].map((label,index)=><button key={label} type="button" data-dock={index} aria-current={page===index?'page':undefined} onClick={()=>onChange(index)}>{icons[index]}<span>{label}</span></button>)}</nav>;
}
