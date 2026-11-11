import {useEffect,useRef,useState} from 'react';

const steps=[
 {image:'/design/onboarding-feeding.svg',title:'Накорми и сними',text:'Кошка или собака, корм и процесс поедания — в одном видео до 15 секунд со звуком.'},
 {image:'/design/onboarding-review.svg',title:'Отправь на проверку',text:'Отправь ролик. После проверки результат появится в профиле. Иногда решение принимает человек.'},
 {image:'/design/onboarding-contribution.svg',title:'Следи за вкладом',text:'За подтверждённое кормление — 10 поинтов. Они показывают твой вклад, обмена на деньги нет.'},
];

export function Onboarding({onClose}:{onClose:()=>void}){
 const [step,setStep]=useState(0),close=useRef(onClose);close.current=onClose;
 useEffect(()=>{const key=(event:KeyboardEvent)=>{if(event.key==='Escape')close.current()};document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key)},[]);
 const current=steps[step];
 return <div className="onboarding-backdrop"><section className="onboarding-card" role="dialog" aria-modal="true" aria-label="Как работает Catfeedik"><div className="onboarding-top"><button className="onboarding-skip" onClick={onClose}>Пропустить</button></div><img src={current.image} alt=""/><div className="onboarding-copy"><h2>{current.title}</h2><p>{current.text}</p><div className="onboarding-progress" aria-label={`Шаг ${step+1} из 3`}>{steps.map((_,index)=><i key={index} className={index===step?'current':''}/>)}</div><small>{step+1} из 3</small></div><div className="onboarding-actions"><button className="primary" onClick={()=>step===steps.length-1?onClose():setStep(step+1)}>{step===steps.length-1?'Открыть Catfeedik':'Далее'}</button>{step>0&&<button className="text-button onboarding-back" onClick={()=>setStep(step-1)}>Назад</button>}</div></section></div>;
}
