import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Package, RefreshCw, ScanEye } from "lucide-react";

type ReconciliationItem = {
  shelf_id: number;
  shelf_code: string;
  zone_name: string;
  product_id: number;
  product_sku: string;
  product_name: string;
  display_target_quantity: number;
  observed_shelf_quantity: number | null;
  display_delta: number | null;
  display_status: "NO_OBSERVATION" | "NO_MEASURED_QUANTITY" | "BELOW_TARGET" | "ABOVE_TARGET" | "AT_TARGET";
  observation_status: string | null;
  observation_confidence: number | null;
  observed_at: string | null;
  backroom_on_hand_quantity: number | null;
  backroom_reserved_quantity: number | null;
  backroom_available_quantity: number | null;
  backroom_source: string | null;
  backroom_snapshot_age_minutes: number | null;
};

type Props = { token: string; storeId: number | null };
type ReconciliationResponse = { count: number; generated_at: string; note: string; items: ReconciliationItem[] };

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

function quantity(value: number | null): string {
  return value == null ? "—" : value.toLocaleString("pt-PT", { maximumFractionDigits: 3 });
}

function dateTime(value: string | null): string {
  if (!value) return "Sem observação";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Data indisponível" : new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" }).format(date);
}

const statusLabels: Record<ReconciliationItem["display_status"], string> = {
  NO_OBSERVATION: "Sem observação",
  NO_MEASURED_QUANTITY: "Sem quantidade medida",
  BELOW_TARGET: "Abaixo do alvo",
  ABOVE_TARGET: "Acima do alvo",
  AT_TARGET: "No alvo",
};

export default function InventoryReconciliation({ token, storeId }: Props) {
  const [data, setData] = useState<ReconciliationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!storeId || !token) {
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ store_id: String(storeId), limit: "200" });
      const response = await fetch(`${API_BASE}/api/v1/inventory/reconciliation?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message || detail?.code || `Erro HTTP ${response.status}`);
      }
      if (!Array.isArray(payload.items)) throw new Error("Resposta inválida da reconciliação de inventário.");
      setData(payload as ReconciliationResponse);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível consultar a reconciliação.");
    } finally {
      setLoading(false);
    }
  }, [storeId, token]);

  useEffect(() => { void load(); }, [load]);

  const metrics = useMemo(() => {
    const items = data?.items ?? [];
    return {
      below: items.filter(item => item.display_status === "BELOW_TARGET").length,
      noObservation: items.filter(item => item.display_status === "NO_OBSERVATION" || item.display_status === "NO_MEASURED_QUANTITY").length,
      noBackroom: items.filter(item => item.backroom_on_hand_quantity == null).length,
      unitsBelow: items.reduce((sum, item) => sum + Math.max(0, -(item.display_delta ?? 0)), 0),
    };
  }, [data]);

  return <section id="inventory-reconciliation" className="panel inventory-reconciliation-panel">
    <div className="panel-heading">
      <div><p className="eyebrow">RECONCILIAÇÃO OPERACIONAL</p><h2>Stock observado vs. alvo de exposição</h2>
        <p className="muted">Compara a quantidade medida na prateleira com o alvo configurado. O stock de retaguarda é apresentado separadamente.</p></div>
      <button type="button" className="row-action" onClick={() => void load()} disabled={loading || !storeId}>
        {loading ? "A atualizar…" : "Atualizar"} <RefreshCw size={14} className={loading ? "spin" : ""} />
      </button>
    </div>
    {!storeId && <p className="inventory-history-hint">Seleciona uma loja para consultar a reconciliação.</p>}
    {error && <div className="error-banner inventory-history-error" role="alert">{error}</div>}
    <div className="reconciliation-metrics">
      <div><span>Referências de prateleira</span><strong>{data?.count ?? 0}</strong></div>
      <div><span>Abaixo do alvo</span><strong>{metrics.below}</strong></div>
      <div><span>Sem medição válida</span><strong>{metrics.noObservation}</strong></div>
      <div><span>Sem snapshot de retaguarda</span><strong>{metrics.noBackroom}</strong></div>
    </div>
    {loading && !data && <div className="loading-state"><RefreshCw size={17} className="spin" /> A calcular reconciliação…</div>}
    {!loading && !error && data && data.items.length === 0 && <div className="empty-state"><ScanEye size={25} /><strong>Sem referências de exposição</strong><span>Associa produtos a prateleiras para iniciar a comparação.</span></div>}
    {data && data.items.length > 0 && <div className="reconciliation-list">
      {data.items.map(item => <article className="reconciliation-row" key={`${item.shelf_id}-${item.product_id}`}>
        <div className="reconciliation-heading">
          <div><strong>{item.product_name}</strong><span>{item.product_sku} · {item.zone_name} · Prateleira {item.shelf_code}</span></div>
          <span className={`reconciliation-status ${item.display_status.toLowerCase()}`}>{statusLabels[item.display_status]}</span>
        </div>
        <div className="reconciliation-values">
          <div><span>Alvo de exposição</span><strong>{quantity(item.display_target_quantity)}</strong></div>
          <div><span>Quantidade observada</span><strong>{quantity(item.observed_shelf_quantity)}</strong></div>
          <div><span>Diferença vs. alvo</span><strong>{item.display_delta == null ? "—" : `${item.display_delta > 0 ? "+" : ""}${quantity(item.display_delta)}`}</strong></div>
          <div><span>Confiança visual</span><strong>{item.observation_confidence == null ? "—" : `${(item.observation_confidence * 100).toFixed(0)}%`}</strong></div>
        </div>
        <div className="reconciliation-backroom">
          <div className="reconciliation-backroom-title"><Package size={14} /><strong>Retaguarda · {item.backroom_source || "Sem snapshot"}</strong></div>
          <span>Em mão: <strong>{quantity(item.backroom_on_hand_quantity)}</strong></span>
          <span>Reservado: <strong>{quantity(item.backroom_reserved_quantity)}</strong></span>
          <span>Disponível: <strong>{quantity(item.backroom_available_quantity)}</strong></span>
          <span>Idade: <strong>{item.backroom_snapshot_age_minutes == null ? "—" : `${Math.round(item.backroom_snapshot_age_minutes)} min`}</strong></span>
        </div>
        <p className="reconciliation-provenance"><ScanEye size={13} /> Última observação: {dateTime(item.observed_at)} · Estado visual: {item.observation_status || "Sem dados"}</p>
      </article>)}
    </div>}
    <p className="reconciliation-safety-note"><AlertTriangle size={15} /> {data?.note || "As diferenças são informativas. Nenhuma observação visual altera automaticamente o inventário contabilístico ou o stock da retaguarda."}</p>
    {data && <p className="inventory-history-updated">Cálculo atualizado em {dateTime(data.generated_at)}.</p>}
  </section>;
}
