export type SponsorTask={id:string;sponsor_id:string;title:string;conditions:string;reward_points:number;deadline_at:number;active:boolean;verification:'MANUAL_OWNER';terms_hash:string;created_at:number;applications?:Record<string,number>;participants?:number};
export type Sponsor={id:string;name:string;description:string;logo_url:string;active:boolean;created_at:number;tasks:SponsorTask[];tasks_has_more:boolean};
export type TaskApplication={id:string;task_id:string;status:'PENDING'|'APPROVED'|'REJECTED';attempt:number;task_title:string;sponsor_name:string;conditions:string;reward_points:number;deadline_at:number;evidence:string;evidence_url:string;review_reason:string;created_at:number;reviewed_at:number|null;name?:string;user_id?:string;frozen?:boolean};
export type TaskStatus=Pick<TaskApplication,'id'|'task_id'|'status'|'review_reason'|'reward_points'>;
export const applicationLabels={PENDING:'На проверке',APPROVED:'Поинты начислены',REJECTED:'Отклонена'};
export const sponsorDate=(timestamp:number)=>new Date(timestamp*1000).toLocaleString('ru-RU',{dateStyle:'medium',timeStyle:'short'});
