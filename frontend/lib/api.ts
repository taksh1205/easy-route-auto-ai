export type Vehicle={id:number;name:string;body:string;price:number;seats:number;features:string[];mileage:number|null;mpg:number|null;explanations?:string[];available:boolean};
export type Session={id:string;token:string;ai_mode:string;version:number};
export type Proposal={id:string;kind:'booking'|'lead'|'cancellation'|'reschedule'|'preferences';arguments:Record<string,unknown>;expires_at:number;status:string};
export type Citation={chunk_id:string;doc_id:string;version:string;topic:string;text:string};
export type Result={comparison?:Vehicle[];availability?:{vehicle_id:number;slots:number[]}[];reply:string;mode:string;intent:string;vehicles:Vehicle[];citations:Citation[];proposals:Proposal[];actions:{committed:boolean;record_id:string;kind:string}[];version:number};
export type Message={role:string;content:string;result?:Result|null};
export type Appointment={id:string;vehicle_id:number;slot:number;cancelled:boolean};
const API=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000';
export class ApiError extends Error{constructor(public status:number,message:string){super(message)}}
export async function request(path:string,method='GET',body?:unknown,s?:Session|null,idempotency?:string){
 const r=await fetch(API+path,{method,headers:{'Content-Type':'application/json',...(s?{'X-Session-Token':s.token}:{}),...(idempotency?{'Idempotency-Key':idempotency}:{})},body:body===undefined?undefined:JSON.stringify(body)});
 if(!r.ok){let message='Request failed';try{const d=await r.json();message=typeof d.detail==='string'?d.detail:d.detail?.message||'Please check your input'}catch{}throw new ApiError(r.status,message)}
 return r.status===204?null:r.json();
}
export function readSession():Session|null{
 const raw=sessionStorage.getItem('easy-session');if(!raw)return null;
 try{const s=JSON.parse(raw);if(typeof s.id==='string'&&typeof s.token==='string'&&s.token.length>=32&&Number.isInteger(s.version))return s}catch{}
 sessionStorage.removeItem('easy-session');return null;
}
export function saveSession(s:Session){sessionStorage.setItem('easy-session',JSON.stringify(s))}
