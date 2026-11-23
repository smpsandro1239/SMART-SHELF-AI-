import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Package, RefreshCw, Search } from "lucide-react";

type ReconciliationItem = {
  store_id: number; zone_id: number; zone_name: string; shelf_id: number; shelf_code: string;
  product_id: number; product_sku: string; product_name: string;
  display_target_quantity: number; observed_shelf_quantity: number | null; display_delta: number | null;
  display_status: "NO_OBSERVATION" | "NO_MEASURED_QUANTITY" | "BELOW_TARGET" | "ABOVE_TARGET" | "AT_TARGET";
  observation_id: number | null; observation_status: string | null; observation_source: string | null;
  observation_confidence: number | null; observed_at: string | null; backroom_snapshot_id: number | null;
  backroom_on_hand_quantity: number | null; backroom_reserved_quantity: number | null;
  backroom_available_quantity: number | null; backroom_source: string | null;
  backroom_captured_at: string | null; backroom_snapshot_age_minutes: number | null;
};
type Props = { token: string; storeId: number | null };
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const STATUS: Record<ReconciliationItem["display_status"], { label: string; tone: string }> = {
  NO_OBSERVATION: { label: "Sem observação", tone: "neutral" },
  NO_MEASURED_QUANTITY: { label: "Sem quantidade medida", tone: "neutral" },
  BELOW_TARGET: { label: "Abaixo do objetivo", tone: "warning" },
  ABOVE_TARGET: { label: "Acima do objetivo", tone: "info" },
  AT_TARGET: { label: "No objetivo", tone: "success" },
};
function quantity(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("pt-PT", { maximumFractionDigits: 3 }) + " un";
}
function dateTime(value: string | null): string {
  if (!value) return "Sem registo";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Data indisponível" : new Intl.DateTimeFormat("pt-PT", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Lisbon",
  }).format(date);
}

export default function InventoryReconciliationPanel({ token, storeId }: Props) {
  const [items, setItems] = useState<ReconciliationItem[]>([]);
  const [productFilter, setProductFilter] = useState("");
  const [shelfFilter, setShelfFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    if (!storeId || !token) { setItems([]); setGeneratedAt(null); return; }
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ store_id: String(storeId), limit: "300" });
      if (productFilter.trim()) params.set("product_id", productFilter.trim());
      if (shelfFilter.trim()) params.set("shelf_id", shelfFilter.trim());
      const response = await fetch(API_BASE + "/api/v1/inventory/reconciliation?" + params.toString(), {
        headers: { Authorization: "Bearer " + token },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message || detail?.code || ("Erro HTTP " + response.status));
      }
      if (!Array.isArray(payload.items)) throw new Error("Resposta inválida da reconciliação de inventário.");
      setItems(payload.items as ReconciliationItem[]);
      setGeneratedAt(payload.generated_at || null);
      setNote(payload.note || "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível carregar a reconciliação.");
    } finally { setLoading(false); }
  }, [storeId, token, productFilter, shelfFilter]);

  useEffect(() => { void load(); }, [load]);
  const counts = useMemo(() => ({
    below: items.filter(item => item.display_status === "BELOW_TARGET").length,
    atTarget: items.filter(item => item.display_status === "AT_TARGET").length,
    noMeasurement: items.filter(item => item.display_status === "NO_OBSERVATION" || item.display_status === "NO_MEASURED_QUANTITY").length,
    backroomUnknown: items.filter(item => item.backroom_snapshot_id === null).length,
  }), [items]);

  return <section id="inventory-reconciliation" className="panel inventory-reconciliation-panel">
    <div className="panel-heading">
      <div>
        <p className="eyebrow">VISÃO OPERACIONAL · STOCK</p>
        <h2>Reconciliação da exposição e retaguarda</h2>
        <p className="muted">Compara a quantidade observada na prateleira com o objetivo de exposição e apresenta o stock da retaguarda separadamente.</p>
      </div>
      <button type="button" className="row-action" onClick={() => void load()} disabled={loading || !storeId}>
        {loading ? "A atualizar…" : "Atualizar"} <RefreshCw size={14} className={loading ? "spin" : ""} />
      </button>
    </div>
    {!storeId && <p className="inventory-history-hint">Seleciona uma loja para consultar a reconciliação.</p>}
    <div className="inventory-reconciliation-filters">
      <label><span><Search size={13} /> Produto</span>
        <input type="number" min="1" inputMode="numeric" placeholder="ID do produto" value={productFilter} onChange={event => setProductFilter(event.target.value)} />
      </label>
      <label><span><Search size={13} /> Prateleira</span>
        <input type="number" min="1" inputMode="numeric" placeholder="ID da prateleira" value={shelfFilter} onChange={event => setShelfFilter(event.target.value)} />
      </label>
      <button type="button" className="row-action secondary-action" onClick={() => { setProductFilter(""); setShelfFilter(""); }} disabled={!productFilter && !shelfFilter}>Limpar filtros</button>
      <span className="inventory-history-limit">Até 300 referências</span>
    </div>
    {error && <div className="error-banner inventory-history-error" role="alert">{error}</div>}
    <div className="inventory-reconciliation-metrics">
      <div><span>Referências de prateleira</span><strong>{items.length}</strong></div>
      <div className="warning"><span>Abaixo do objetivo</span><strong>{counts.below}</strong></div>
      <div className="success"><span>No objetivo</span><strong>{counts.atTarget}</strong></div>
      <div><span>Sem medição</span><strong>{counts.noMeasurement}</strong></div>
      <div><span>Sem snapshot de retaguarda</span><strong>{counts.backroomUnknown}</strong></div>
    </div>
    <div className="inventory-reconciliation-list" aria-live="polite">
      {loading && items.length === 0 && <div className="loading-state"><RefreshCw className="spin" size={17} /> A carregar reconciliação…</div>}
      {!loading && !error && items.length === 0 && <div className="empty-state"><Package size={25} /><strong>Sem referências para reconciliar</strong><span>Não existem associações produto/prateleira para os filtros e loja selecionados.</span></div>}
      {items.map(item => {
        const status = STATUS[item.display_status];
        return <article className="inventory-reconciliation-row" key={item.shelf_id + ":" + item.product_id}>
          <div className="inventory-reconciliation-heading">
            <div>
              <strong>{item.product_name} <small>{item.product_sku}</small></strong>
              <span>{item.zone_name} · Prateleira {item.shelf_code} · Produto #{item.product_id}</span>
            </div>
            <span className={"inventory-reconciliation-status " + status.tone}>
              {item.display_status === "BELOW_TARGET" ? <AlertCircle size={13} /> : item.display_status === "AT_TARGET" ? <CheckCircle2 size={13} /> : null}
              {status.label}
            </span>
          </div>
          <div className="inventory-reconciliation-domains">
            <div className="inventory-domain shelf-domain">
              <span className="inventory-domain-title">Exposição · prateleira</span>
              <div><span>Objetivo</span><strong>{quantity(item.display_target_quantity)}</strong></div>
              <div><span>Observado</span><strong>{quantity(item.observed_shelf_quantity)}</strong></div>
              <div><span>Diferença face ao objetivo</span><strong className={item.display_delta !== null && item.display_delta < 0 ? "negative" : ""}>{quantity(item.display_delta)}</strong></div>
              <small>Observação: {dateTime(item.observed_at)}{item.observation_confidence !== null ? " · Confiança " + Math.round(item.observation_confidence * 100) + "%" : ""}</small>
            </div>
            <div className="inventory-domain backroom-domain">
              <span className="inventory-domain-title">Retaguarda · snapshot autoritativo</span>
              <div><span>Stock físico registado</span><strong>{quantity(item.backroom_on_hand_quantity)}</strong></div>
              <div><span>Reservado</span><strong>{quantity(item.backroom_reserved_quantity)}</strong></div>
              <div><span>Disponível</span><strong>{quantity(item.backroom_available_quantity)}</strong></div>
              <small>{item.backroom_source || "Sem fonte"} · {dateTime(item.backroom_captured_at)}{item.backroom_snapshot_age_minutes !== null ? " · " + Math.floor(item.backroom_snapshot_age_minutes) + " min" : ""}</small>
            </div>
          </div>
          <div className="inventory-reconciliation-footnote">
            <span>Observação #{item.observation_id ?? "—"} · Snapshot #{item.backroom_snapshot_id ?? "—"}</span>
            <span>Sem ajustes automáticos ao inventário contabilístico.</span>
          </div>
        </article>;
      })}
    </div>
    {note && <p className="inventory-reconciliation-note">{note}</p>}
    {generatedAt && <p className="inventory-history-updated">Calculado em {dateTime(generatedAt)}.</p>}
  </section>;
}
