import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, RefreshCw, XCircle } from "lucide-react";

type Props = { token: string; storeId: number | null };
type Attempt = {
  id:number; source:"ERP"|"WMS"; provider:string; status:"STARTED"|"SUCCESS"|"PARTIAL"|"FAILED";
  started_at:string; finished_at:string|null; duration_ms:number|null;
  received_records:number|null; processed_records:number|null; error_code:string|null; error_message:string|null;
};
type HealthSource = {
  last_attempt:Attempt|null; last_success:Attempt|null; minutes_since_success:number|null;
  max_age_minutes:number; stale:boolean; alert_code:string|null; alert_message:string|null; latest_attempt_failed:boolean;
};
const API_BASE=(import.meta.env.VITE_API_BASE_URL||"").replace(/\/$/,"");
const dateTime=(value:string|null)=>value?new Intl.DateTimeFormat("pt-PT",{dateStyle:"medium",timeStyle:"short",timeZone:"Europe/Lisbon"}).format(new Date(value)):"Nunca";
const statusLabel=(status:string)=>({STARTED:"Em execução",SUCCESS:"Sucesso",PARTIAL:"Parcial",FAILED:"Falhou"}[status]||status);
export default function InventorySourceSyncPanel({token,storeId}:Props){
 const [health,setHealth]=useState<Record<string,HealthSource>|null>(null);
 const [items,setItems]=useState<Attempt[]>([]);const [loading,setLoading]=useState(false);const [error,setError]=useState("");
 const load=useCallback(async()=>{if(!storeId||!token){setHealth(null);setItems([]);return;}setLoading(true);setError("");try{
  const headers={Authorization:"Bearer "+token};
  const [healthResponse,historyResponse]=await Promise.all([
   fetch(API_BASE+"/api/v1/inventory/source-syncs/health?"+new URLSearchParams({store_id:String(storeId)}),{headers}),
   fetch(API_BASE+"/api/v1/inventory/source-syncs?"+new URLSearchParams({store_id:String(storeId),limit:"12"}),{headers})
  ]);
  const healthBody=await healthResponse.json().catch(()=>({}));const historyBody=await historyResponse.json().catch(()=>({}));
  if(!healthResponse.ok)throw new Error(typeof healthBody.detail==="string"?healthBody.detail:"Não foi possível consultar a saúde das fontes.");
  if(!historyResponse.ok)throw new Error(typeof historyBody.detail==="string"?historyBody.detail:"Não foi possível consultar o histórico.");
  setHealth(healthBody.sources||{});setItems(historyBody.items||[]);
 }catch(cause){setError(cause instanceof Error?cause.message:"Falha ao carregar sincronizações.");}finally{setLoading(false);}},[storeId,token]);
 useEffect(()=>{void load();},[load]);
 return <section className="panel source-sync-panel" aria-labelledby="source-sync-title">
  <div className="panel-heading"><div><p className="eyebrow">INTEGRAÇÕES · OBSERVABILIDADE</p><h2 id="source-sync-title">Sincronizações ERP / WMS</h2><p className="muted">Últimas tentativas registadas e atualidade da última execução bem-sucedida.</p></div>
   <button type="button" className="row-action secondary-action" onClick={()=>void load()} disabled={loading||!storeId}>{loading?"A atualizar…":"Atualizar"} <RefreshCw size={14} className={loading?"spin":""}/></button></div>
  {!storeId&&<p className="inventory-history-hint">Seleciona uma loja para consultar as sincronizações.</p>}
  {error&&<div className="error-banner" role="alert">{error}</div>}
  {health&&<div className="source-sync-health">{(["ERP","WMS"] as const).map(source=>{const item=health[source];return <article key={source} className={item.stale?"is-stale":""}>
   <div className="source-sync-title-row"><strong>{source}</strong>{item.stale?<span className="sync-status failed"><AlertTriangle size={12}/> Desatualizada</span>:<span className="sync-status success"><CheckCircle2 size={12}/> Atualizada</span>}</div>
   <strong className="source-sync-age">{item.minutes_since_success===null?"Sem sincronização":item.minutes_since_success+" min"}</strong>
   <small>Limite: {item.max_age_minutes} min · Último sucesso: {dateTime(item.last_success?.finished_at||null)}</small>
   {item.alert_message&&<p className="source-sync-alert">{item.alert_message}</p>}
   {item.latest_attempt_failed&&<p className="source-sync-error">{item.last_attempt?.error_code||"Falha"}: {item.last_attempt?.error_message||"A última tentativa falhou."}</p>}
  </article>;})}</div>}
  <div className="source-sync-history"><h3>Histórico recente</h3>{items.length===0?<p className="inventory-history-hint">Ainda não existem tentativas registadas. O histórico só é preenchido por um processo que reporte o início e o resultado da sincronização.</p>:
   <div className="source-sync-table-wrap"><table><thead><tr><th>Fonte</th><th>Fornecedor</th><th>Estado</th><th>Início</th><th>Registos</th><th>Duração</th></tr></thead><tbody>{items.map(item=><tr key={item.id}>
    <td><strong>{item.source}</strong></td><td>{item.provider}</td><td><span className={"sync-status "+(item.status==="SUCCESS"?"success":item.status==="FAILED"?"failed":item.status==="PARTIAL"?"partial":"running")}>{item.status==="SUCCESS"?<CheckCircle2 size={12}/>:item.status==="FAILED"?<XCircle size={12}/>:<Clock3 size={12}/>} {statusLabel(item.status)}</span>{item.error_code&&<small className="sync-error-code">{item.error_code}</small>}</td>
    <td>{dateTime(item.started_at)}</td><td>{item.processed_records===null?"—":item.processed_records+" / "+item.received_records}</td><td>{item.duration_ms===null?"—":(item.duration_ms/1000).toFixed(1)+" s"}</td>
   </tr>)}</tbody></table></div>}
  </div>
  <p className="source-sync-disclaimer">Este painel apresenta execuções reportadas à API. Não inicia ligações externas nem representa uma integração ERP/WMS operacional por si só.</p>
 </section>;
}
