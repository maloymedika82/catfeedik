import {useEffect,useState} from 'react';

type Theme='system'|'light'|'dark';
const labels:Record<Theme,string>={system:'Как на устройстве',light:'Светлая тема',dark:'Тёмная тема'};

export function ThemeToggle(){
 const [theme,setTheme]=useState<Theme>(()=>{const saved=localStorage.getItem('catfeedik-theme');return saved==='light'||saved==='dark'?saved:'system'});
 useEffect(()=>{document.documentElement.dataset.theme=theme;localStorage.setItem('catfeedik-theme',theme)},[theme]);
 return <button className="theme-toggle" type="button" aria-label={`Тема: ${labels[theme]}. Нажми, чтобы сменить.`} title={`Тема: ${labels[theme]}`} onClick={()=>setTheme(theme==='system'?'light':theme==='light'?'dark':'system')}>{theme==='dark'?'☾':theme==='light'?'☀':'◐'}</button>;
}
