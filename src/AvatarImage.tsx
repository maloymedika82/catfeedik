import {useEffect,useState} from 'react';

export function AvatarImage({name,url}:{name:string;url?:string}){
 const [failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[url]);
 if(url&&!failed)return <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>;
 return <>{name.split(' ').slice(0,2).map(part=>part[0]).join('')}</>;
}
