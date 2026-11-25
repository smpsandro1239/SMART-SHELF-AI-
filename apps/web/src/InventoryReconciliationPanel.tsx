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
  erp_snapshot_id: number | null; erp_on_hand_quantity: number | null; erp_reserved_quantity: number | null;
  erp_available_quantity: number | null; erp_source: string | null; erp_captured_at: string | null;
  erp_snapshot_age_minutes: number | null; erp_freshness_status: "MISSING" | "CURRENT" | "STALE" | "FUTURE";
  wms_snapshot_id: number | null; wms_on_hand_quantity: number | null; wms_reserved_quantity: number | null;
  wms_available_quantity: number | null; wms_source: string | null; wms_captured_at: string | null;
  wms_snapshot_age_minutes: number | null; wms_freshness_status: "MISSING" | "CURRENT" | "STALE" | "FUTURE";
  wms_erp_available_delta: number | null;
  erp_wms_capture_skew_seconds: number | null;
  erp_wms_capture_skew_tolerance_minutes: number | null;
  wms_erp_comparison_status: "MISSING_ERP" | "MISSING_WMS" | "INVALID_TIMESTAMP" | "STALE_SOURCE" | "IN_SYNC" | "DIVERGENCE" | "WMS_BACKROOM_UNAVAILABLE" | "WMS_BACKROOM_LOCATION_NOT_CONFIGURED" | "MISSING_WMS_BACKROOM_STOCK" | "TEMPORAL_SKEW_UNCONFIGURED" | "TEMPORAL_SKEW";
};
type LedgerRecord = {
  id: number; shelf_id: number; product_id: number; review_status: "PENDING" | "APPROVED" | "REJECTED" | "NEEDS_INVESTIGATION";
  comparison_status: string; display_quantity: number | null; wms_available_quantity: number | null;
  erp_available_quantity: number | null; wms_erp_delta: number | null; created_at: string;
  created_by_name: string | null; reviewed_by_name: string | null; review_reason: string | null;
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
  const [ledger, setLedger] = useState<LedgerRecord[]>([]);
  const [ledgerBusy, setLedgerBusy] = useState<number | null>(null);
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
      const historyResponse = await fetch(API_BASE + "/api/v1/inventory/reconciliations?" + new URLSearchParams({
        store_id: String(storeId), limit: "100",
      }).toString(), { headers: { Authorization: "Bearer " + token } });
      const historyPayload = await historyResponse.json().catch(() => ({}));
      if (!historyResponse.ok) throw new Error(typeof historyPayload.detail === "string" ? historyPayload.detail : "Não foi possível carregar o histórico.");
      setLedger(Array.isArray(historyPayload.items) ? historyPayload.items as LedgerRecord[] : []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível carregar a reconciliação.");
    } finally { setLoading(false); }
  }, [storeId, token, productFilter, shelfFilter]);

  const createLedgerRecord = useCallback(async (item: ReconciliationItem) => {
    const reason = window.prompt("Motivo para registar esta reconciliação:", "Divergência identificada no painel operacional");
    if (!reason || reason.trim().length < 3) return;
    setLedgerBusy(item.product_id);
    try {
      const response = await fetch(API_BASE + "/api/v1/inventory/reconciliations", {
        method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
        body: JSON.stringify({ store_id: item.store_id, shelf_id: item.shelf_id, product_id: item.product_id, reason }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Não foi possível registar a reconciliação.");
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao registar reconciliação."); }
    finally { setLedgerBusy(null); }
  }, [token, load]);

  const reviewLedgerRecord = useCallback(async (recordId: number, decision: "APPROVED" | "REJECTED" | "NEEDS_INVESTIGATION") => {
    const reason = window.prompt(decision === "APPROVED" ? "Justificação da aprovação:" : decision === "REJECTED" ? "Motivo da rejeição:" : "O que deve ser investigado?");
    if (!reason || reason.trim().length < 3) return;
    setLedgerBusy(recordId);
    try {
      const response = await fetch(API_BASE + "/api/v1/inventory/reconciliations/" + recordId + "/review", {
        method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
        body: JSON.stringify({ decision, reason }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Não foi possível rever a reconciliação.");
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao rever reconciliação."); }
    finally { setLedgerBusy(null); }
  }, [token, load]);

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
        <p className="muted">Compara a contagem física da prateleira, os snapshots WMS e o registo ERP. Só calcula diferenças ERP/WMS quando ambas as fontes estão presentes e dentro da política de frescura.</p>
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
              <span className="inventory-domain-title">Retaguarda · último snapshot</span>
              <div><span>Stock físico registado</span><strong>{quantity(item.backroom_on_hand_quantity)}</strong></div>
              <div><span>Reservado</span><strong>{quantity(item.backroom_reserved_quantity)}</strong></div>
              <div><span>Disponível</span><strong>{quantity(item.backroom_available_quantity)}</strong></div>
              <small>{item.backroom_source || "Sem fonte"} · {dateTime(item.backroom_captured_at)}{item.backroom_snapshot_age_minutes !== null ? " · " + Math.floor(item.backroom_snapshot_age_minutes) + " min" : ""}</small>
            </div>
            <div className="inventory-domain source-domain">
              <span className="inventory-domain-title">ERP · sistema central</span>
              <div><span>Stock registado</span><strong>{quantity(item.erp_on_hand_quantity)}</strong></div>
              <div><span>Reservado</span><strong>{quantity(item.erp_reserved_quantity)}</strong></div>
              <div><span>Disponível</span><strong>{quantity(item.erp_available_quantity)}</strong></div>
              <small>{item.erp_source || "Sem snapshot ERP"} · {dateTime(item.erp_captured_at)} · {item.erp_freshness_status}</small>
            </div>
            <div className="inventory-domain source-domain">
              <span className="inventory-domain-title">WMS · retaguarda</span>
              <div><span>Stock registado</span><strong>{quantity(item.wms_on_hand_quantity)}</strong></div>
              <div><span>Reservado</span><strong>{quantity(item.wms_reserved_quantity)}</strong></div>
              <div><span>Disponível</span><strong>{quantity(item.wms_available_quantity)}</strong></div>
              <small>{item.wms_source || "Sem snapshot WMS"} · {dateTime(item.wms_captured_at)} · {item.wms_freshness_status}</small>
            </div>
          </div>
          <div className="inventory-reconciliation-footnote">
            <span>Observação #{item.observation_id ?? "—"} · Snapshot #{item.backroom_snapshot_id ?? "—"}</span>
            <span>
              {item.wms_erp_comparison_status === "IN_SYNC" ? "ERP e WMS coincidem."
                : item.wms_erp_comparison_status === "DIVERGENCE" ? "Divergência WMS − ERP: " + quantity(item.wms_erp_available_delta)
                  : item.wms_erp_comparison_status === "TEMPORAL_SKEW_UNCONFIGURED" ? "Comparação suspensa: falta configurar a tolerância temporal ERP/WMS."
                    : item.wms_erp_comparison_status === "TEMPORAL_SKEW" ? "Comparação suspensa: diferença temporal superior à tolerância configurada."
                      : "Comparação ERP/WMS indisponível: " + item.wms_erp_comparison_status}
              {item.erp_wms_capture_skew_seconds !== null && " · Diferença entre capturas: " + item.erp_wms_capture_skew_seconds.toLocaleString("pt-PT") + " s"}
              {item.erp_wms_capture_skew_tolerance_minutes !== null && " · Tolerância: " + item.erp_wms_capture_skew_tolerance_minutes + " min"}
              {" · Sem ajustes automáticos ao inventário contabilístico."}
            </span>
          </div>
          <div className="inventory-reconciliation-ledger-action">
            <span>Guardar evidência imutável e enviar para revisão humana.</span>
            <button type="button" className="row-action secondary-action"
              onClick={() => void createLedgerRecord(item)} disabled={ledgerBusy === item.product_id}>
              {ledgerBusy === item.product_id ? "A registar…" : "Registar reconciliação"}
            </button>
          </div>
        </article>;
      })}
    </div>
    <section className="inventory-reconciliation-ledger" aria-labelledby="inventory-reconciliation-ledger-title">
      <div className="panel-heading"><div><p className="eyebrow">AUDITORIA · DECISÕES HUMANAS</p><h3 id="inventory-reconciliation-ledger-title">Histórico de reconciliações</h3>
        <p className="muted">Cada registo conserva os valores e timestamps usados no momento da análise. A revisão não altera os saldos contabilísticos.</p></div></div>
      {ledger.length === 0 ? <p className="inventory-history-hint">Ainda não existem reconciliações persistidas para esta loja.</p> :
        <div className="inventory-reconciliation-ledger-list">
          {ledger.map(record => <article className="inventory-reconciliation-ledger-row" key={record.id}>
            <div><strong>Reconciliação #{record.id} · Produto #{record.product_id} · Prateleira #{record.shelf_id}</strong>
              <span>{dateTime(record.created_at)} · Criada por {record.created_by_name || "utilizador indisponível"}</span></div>
            <div className="inventory-ledger-values">
              <span>Prateleira: {quantity(record.display_quantity)}</span><span>WMS: {quantity(record.wms_available_quantity)}</span>
              <span>ERP: {quantity(record.erp_available_quantity)}</span><span>WMS − ERP: {quantity(record.wms_erp_delta)}</span>
              <strong>{record.review_status}</strong>
            </div>
            {record.reviewed_by_name && <small>Revista por {record.reviewed_by_name} · {record.review_reason}</small>}
            {record.review_status === "PENDING" && <div className="inventory-ledger-review-actions">
              <button type="button" className="row-action" disabled={ledgerBusy === record.id} onClick={() => void reviewLedgerRecord(record.id, "APPROVED")}>Aprovar</button>
              <button type="button" className="row-action secondary-action" disabled={ledgerBusy === record.id} onClick={() => void reviewLedgerRecord(record.id, "REJECTED")}>Rejeitar</button>
              <button type="button" className="row-action secondary-action" disabled={ledgerBusy === record.id} onClick={() => void reviewLedgerRecord(record.id, "NEEDS_INVESTIGATION")}>Investigar</button>
            </div>}
          </article>)}
        </div>}
    </section>
    {note && <p className="inventory-reconciliation-note">{note}</p>}
    {generatedAt && <p className="inventory-history-updated">Calculado em {dateTime(generatedAt)}.</p>}
  </section>;
}
