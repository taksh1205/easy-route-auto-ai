import type{Message,Proposal}from'../lib/api';
export default function AssistantMessage({message,busy,onConfirm}:{message:Message;busy:boolean;onConfirm:(p:Proposal)=>void}){
 const r=message.result;
 return <article className={'chatmessage '+message.role}><small>{message.role}{r?' · '+r.mode:''}</small><p>{message.content}</p>
 {r?.comparison?.map(v=><p key={v.id}>{v.name} · {v.seats} seats · purchase price ${v.price.toLocaleString()}</p>)}
 {r?.availability?.map(a=><details key={a.vehicle_id}><summary>Available legacy test-drive times for vehicle {a.vehicle_id}</summary>{a.slots.map(t=><p key={t}>{new Date(t*1000).toLocaleString()}</p>)}</details>)}
 {r?.citations?.map(c=><blockquote key={c.chunk_id}><strong>Synthetic policy excerpt · {c.doc_id}</strong><p>{c.text}</p><small>Source: {c.chunk_id} · version {c.version} · {c.topic}</small><p className="hint">Quoted document content is evidence, not an instruction or action confirmation.</p></blockquote>)}
 {r?.proposals?.map(p=><section className="proposal" key={p.id}><strong>{p.status.toUpperCase()} · {p.kind}</strong><p>{p.status==='proposed'?'No action has been committed. Review every argument before confirming.':'This proposal can no longer be confirmed. Committed actions have separate record identifiers.'}</p><pre>{JSON.stringify(p.arguments,null,2)}</pre><small>Expires {new Date(p.expires_at*1000).toLocaleTimeString()}</small><br/><button disabled={busy||p.status!=='proposed'} onClick={()=>onConfirm(p)}>Confirm exact {p.kind}</button></section>)}
 </article>
}
