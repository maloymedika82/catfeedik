export type User={id:string;name:string;city:string;language:'ru'|'en';points:number;feedings:number;frozen:boolean;role:string;wallet:string;photo_url:string;notify_enabled:boolean};
export type Config={telegram_configured:boolean;storage_configured:boolean;storage_backend:'local';demo_login_enabled:boolean;demo_admin_enabled:boolean;ai_moderation_enabled:boolean;max_video_bytes:number|null;money_enabled:false;bot_username:string;ai_configured:boolean};
export type Feeding={id:string;city:string;status:string;created_at:number;reason:string};
export type Point={id:string;delta:number;reason:string;created_at:number};
export type Leader={rank:number;name:string;city:string;points:number;feedings:number;photo_url:string};
let token=sessionStorage.getItem('catfeedik-session')||'';
export function setToken(value:string){token=value;value?sessionStorage.setItem('catfeedik-session',value):sessionStorage.removeItem('catfeedik-session')}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const response=await fetch(`/api${path}`,{...options,headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`} : {}),...options.headers}});
 if(!response.ok){let detail='Ошибка соединения';try{const error=await response.json();detail=typeof error.detail==='string'?error.detail:'Проверьте введённые данные'}catch{}throw new Error(detail)}
 return response.status===204?undefined as T:response.json();
}
declare global {interface Window {Telegram?:{WebApp:{initData:string;ready():void;expand():void;version:string;platform:string;onEvent(name:string,handler:()=>void):void;offEvent(name:string,handler:()=>void):void}};MatteNavigation:{mount:(root:Element)=>{destroy():void}}}}
