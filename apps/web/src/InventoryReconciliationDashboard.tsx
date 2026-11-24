import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Clock3, Package, RefreshCw } from "lucide-react";
type Props = { token: string; storeId: number | null };
type Dashboard = {
  store_name: string; generated_at: string; window_days: number; truncated: boolean;
  total_reconciliations: number; unique_products: number; divergences: number; recurring_products_30d: number;
  review_status_counts: Record<string, number>;
  product_ranking: Array<{product_id:number;product_sku:string;product_name:string;reconciliation_count:number;recurring_count_30d:number;divergence_count:number;absolute_delta_total:number;is_recurring:boolean}>;
  source_freshness: Record<string,{current:number;stale:number;missing:number;future:number;coverage_percent:number|null;freshness_percent:number|null;max_age_minutes:number}>;
  note: string;
};
const API_BASE=(import.meta.env.VITE_API_BASE_URL||"").replace(/\/$/,"");
const percent=(value:number|null)=>value===null?"Sem dados":value.toLocaleString("pt-PT",{maximumFractionDigits:1})+"%";
export default function InventoryReconciliationDashboard({token,storeId}:Props){
 const [data,setData]=useState<Dashboard|null>(null);const [loading,setLoading]=useState(false);const [error,setError]=useState("");
 const load=useCallback(async()=>{if(!storeId||!token){setData(null);return;}setLoading(true);setError("");try{
  const response=await fetch(API_BASE+"/api/v1/inventory/reconciliations/dashboard?"+new URLSearchParams({store_id:String(storeId)}),{headers:{Authorization:"Bearer "+token}});
  const payload=await response.json().catch(()=>({}));if(!response.ok)throw new Error(typeof payload.detail==="string"?payload.detail:"Não foi possível carregar o dashboard.");setData(payload as Dashboard);
 }catch(cause){setError(cause instanceof Error?cause.message:"Falha ao carregar o dashboard.");}finally{setLoading(false);}},[storeId,token]);
 useEffect(()=>{void load();},[load]);
 return <section className="panel reconciliation-dashboard" aria-labelledby="reconciliation-dashboard-title">
  <div className="panel-heading"><div><p className="eyebrow">INTELIGÊNCIA OPERACIONAL · LEDGER</p><h2 id="reconciliation-dashboard-title">Dashboard de divergências</h2><p className="muted">{data?data.store_name+" · últimos "+data.window_days+" dias":"Indicadores calculados a partir das reconciliações persistidas."}</p></div>
   <button type="button" className="row-action secondary-action" onClick={()=>void load()} disabled={loading||!storeId}>{loading?"A atualizar…":"Atualizar"} <RefreshCw size={14} className={loading?"spin":""}/></button></div>
  {!storeId&&<p className="inventory-history-hint">Seleciona uma loja para consultar os indicadores.</p>}
  {error&&<div className="error-banner" role="alert">{error}</div>}
  {loading&&!data&&<div className="loading-state"><RefreshCw className="spin" size={17}/> A calcular indicadores…</div>}
  {data&&<>
   <div className="reconciliation-dashboard-metrics">
    <article><span><Activity size={15}/> Reconciliações</span><strong>{data.total_reconciliations}</strong><small>{data.unique_products} produtos distintos</small></article>
    <article className="warning"><span><AlertTriangle size={15}/> Divergências ERP/WMS</span><strong>{data.divergences}</strong><small>Nos últimos {data.window_days} dias</small></article>
    <article className="pending"><span><Clock3 size={15}/> Pendentes</span><strong>{data.review_status_counts.PENDING||0}</strong><small>Aguardam decisão humana</small></article>
    <article className="success"><span><CheckCircle2 size={15}/> Aprovadas</span><strong>{data.review_status_counts.APPROVED||0}</strong><small>Validadas por revisor independente</small></article>
    <article><span><Package size={15}/> Divergências recorrentes</span><strong>{data.recurring_products_30d}</strong><small>≥2 registos por produto em 30 dias</small></article>
   </div>
   <div className="reconciliation-dashboard-grid">
    <section className="reconciliation-dashboard-block"><div className="panel-heading"><div><h3>Produtos com maior discrepância</h3><p className="muted">Ordenação por recorrência, divergências e magnitude acumulada absoluta WMS − ERP.</p></div></div>
     {data.product_ranking.length===0?<p className="inventory-history-hint">Ainda não existem reconciliações no período.</p>:<div className="reconciliation-ranking">{data.product_ranking.map((item,index)=><article key={item.product_id}>
      <span className="ranking-position">{index+1}</span><div className="ranking-product"><strong>{item.product_name}</strong><small>{item.product_sku} · {item.reconciliation_count} registos · {item.divergence_count} divergências</small></div>
      <div className="ranking-value"><strong>{item.absolute_delta_total.toLocaleString("pt-PT",{maximumFractionDigits:3})}</strong><small>un. |Δ| acumulado</small></div>{item.is_recurring&&<span className="recurring-badge">Recorrente</span>}
     </article>)}</div>}
    </section>
    <section className="reconciliation-dashboard-block"><div className="panel-heading"><div><h3>Atualidade das fontes</h3><p className="muted">Atualidade entre evidências existentes; cobertura calculada separadamente.</p></div></div>
     <div className="source-health-list">{Object.entries(data.source_freshness).map(([source,health])=><article key={source}>
      <div><strong>{source==="SHELF"?"Prateleira":source}</strong><b>{percent(health.freshness_percent)}</b></div>
      <div className="source-health-track"><span style={{width:(health.freshness_percent??0)+"%"}}/></div>
      <small>Cobertura {percent(health.coverage_percent)} · {health.current} atuais · {health.stale} desatualizadas · {health.missing} em falta · {health.future} futuras</small><small>Limite: {health.max_age_minutes} min</small>
     </article>)}</div>
    </section>
   </div>
   {data.truncated&&<p className="inventory-history-hint">Limite de 5 000 registos atingido; os indicadores reflectem os mais recentes.</p>}
   <p className="reconciliation-dashboard-note">{data.note}</p>
   <p className="inventory-history-updated">Atualizado em {new Intl.DateTimeFormat("pt-PT",{dateStyle:"medium",timeStyle:"short",timeZone:"Europe/Lisbon"}).format(new Date(data.generated_at))}.</p>
  </>}
 </section>;
}
