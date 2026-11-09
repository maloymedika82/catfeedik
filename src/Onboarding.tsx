import {useEffect,useRef,useState} from 'react';

const steps=[
 {image:'/design/onboarding-feeding.png',title:'Покорми кошку или собаку',text:'Найди животное, которому нужна еда. Сними, как оно ест корм.'},
 {image:'/design/onboarding-review.png',title:'Отправь видео на проверку',text:'Запиши один ролик до 15 секунд со звуком. Результат появится в профиле.'},
 {image:'/design/onboarding-contribution.png',title:'Следи за своим вкладом',text:'За подтверждённое кормление начисляются поинты. Денежных выплат нет.'},
];

export function Onboarding({onClose}:{onClose:()=>void}){
 const [step,setStep]=useState(0),close=useRef(onClose);close.current=onClose;
 useEffect(()=>{const key=(event:KeyboardEvent)=>{if(event.key==='Escape')close.current()};document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key)},[]);
 const current=steps[step];
 return <div className="onboarding-backdrop"><section className="onboarding-card" role="dialog" aria-modal="true" aria-label="Как работает Catfeedik"><button className="onboarding-skip" onClick={onClose}>Пропустить</button><img src={current.image} alt=""/><div className="onboarding-progress" aria-label={`Шаг ${step+1} из 3`}>{steps.map((_,index)=><i key={index} className={index===step?'current':''}/>)}</div><h2>{current.title}</h2><p>{current.text}</p><button className="primary" onClick={()=>step===steps.length-1?onClose():setStep(step+1)}>{step===steps.length-1?'Начать':'Далее'}</button></section></div>;
}
