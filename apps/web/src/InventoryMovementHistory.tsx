import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Clock3, Filter, History, Package, RefreshCw } from "lucide-react";

type InventoryMovement = {
  id: number;
  task_id: number;
  store_id: number;
  product_id: number;
  movement_type: "BACKROOM_TO_SHELF";
  quantity: number;
  source_snapshot_id: number;
  result_snapshot_id: number;
  actor_user_id: number;
  reason: string;
  created_at: string;
};

type Props = { token: string; storeId: number | null };

function formatMovementDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Data indisponível";
  return new Intl.DateTimeFormat("pt-PT", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Lisbon",
  }).format(date);
}

export default function InventoryMovementHistory({ token, storeId }: Props) {
  const [movements, setMovements] = useState<InventoryMovement[]>([]);
  const [productFilter, setProductFilter] = useState("");
  const [taskFilter, setTaskFilter] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);

  const loadMovements = useCallback(async () => {
    if (!storeId || !token) {
      setMovements([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ store_id: String(storeId), limit: "100" });
      if (productFilter.trim()) params.set("product_id", productFilter.trim());
      if (taskFilter.trim()) params.set("task_id", taskFilter.trim());
      const response = await fetch(`/api/v1/inventory/movements?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message || detail?.code || `Erro HTTP ${response.status}`);
      }
      if (!Array.isArray(payload)) throw new Error("Resposta inválida do histórico de inventário.");
      setMovements(payload as InventoryMovement[]);
      setLoadedAt(new Date());
      setExpandedId(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível carregar o histórico.");
    } finally {
      setLoading(false);
    }
  }, [storeId, token, productFilter, taskFilter]);

  useEffect(() => { void loadMovements(); }, [loadMovements]);

  const totalUnits = useMemo(
    () => movements.reduce((sum, movement) => sum + Number(movement.quantity || 0), 0),
    [movements],
  );
  const latestMovement = movements[0];

  return <section id="inventory-movement-history" className="panel inventory-history-panel">
    <div className="panel-heading">
      <div>
        <p className="eyebrow">RASTREABILIDADE</p>
        <h2>Histórico de movimentos de stock</h2>
        <p className="muted">Movimentos aprovados da retaguarda para a prateleira. Consulta apenas de leitura.</p>
      </div>
      <button type="button" className="row-action" onClick={() => void loadMovements()} disabled={loading || !storeId}>
        {loading ? "A atualizar…" : "Atualizar"} <RefreshCw size={14} className={loading ? "spin" : ""} />
      </button>
    </div>

    {!storeId && <p className="inventory-history-hint">Seleciona uma loja para consultar os movimentos.</p>}
    <div className="inventory-history-filters">
      <label><span><Filter size={13} /> Produto</span>
        <input type="number" min="1" inputMode="numeric" placeholder="ID do produto" value={productFilter} onChange={event => setProductFilter(event.target.value)} />
      </label>
      <label><span><Filter size={13} /> Tarefa</span>
        <input type="number" min="1" inputMode="numeric" placeholder="ID da tarefa" value={taskFilter} onChange={event => setTaskFilter(event.target.value)} />
      </label>
      <button type="button" className="row-action secondary-action" onClick={() => { setProductFilter(""); setTaskFilter(""); }} disabled={!productFilter && !taskFilter}>Limpar filtros</button>
      <span className="inventory-history-limit">Últimos 100 registos</span>
    </div>

    {error && <div className="error-banner inventory-history-error" role="alert">{error}</div>}
    <div className="inventory-history-metrics">
      <div><span>Movimentos encontrados</span><strong>{movements.length}</strong></div>
      <div><span>Unidades movimentadas</span><strong>{totalUnits.toLocaleString("pt-PT", { maximumFractionDigits: 3 })}</strong></div>
      <div><span>Movimento mais recente</span><strong>{latestMovement ? formatMovementDate(latestMovement.created_at) : "—"}</strong></div>
    </div>

    <div className="inventory-movement-list" aria-live="polite">
      {loading && movements.length === 0 && <div className="loading-state"><RefreshCw className="spin" size={17} /> A carregar movimentos…</div>}
      {!loading && !error && movements.length === 0 && <div className="empty-state"><Package size={25} /><strong>Sem movimentos encontrados</strong><span>Os movimentos aprovados para esta loja aparecerão aqui. Ajusta os filtros ou aguarda uma reposição reconciliada.</span></div>}
      {movements.map(movement => {
        const expanded = expandedId === movement.id;
        return <article className="inventory-movement-row" key={movement.id}>
          <div className="inventory-movement-main">
            <div className="inventory-movement-icon"><Package size={17} /></div>
            <div className="inventory-movement-title">
              <strong>{movement.quantity.toLocaleString("pt-PT", { maximumFractionDigits: 3 })} unidades · Produto #{movement.product_id}</strong>
              <span><Clock3 size={12} /> {formatMovementDate(movement.created_at)} · Tarefa #{movement.task_id}</span>
            </div>
            <span className="inventory-movement-type">Retaguarda → Prateleira</span>
            <button type="button" className="inventory-movement-expand" aria-expanded={expanded} aria-label={expanded ? "Ocultar detalhe do movimento" : "Ver detalhe do movimento"} onClick={() => setExpandedId(expanded ? null : movement.id)}>
              {expanded ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
            </button>
          </div>
          {expanded && <div className="inventory-movement-detail">
            <div><span>Movimento</span><strong>#{movement.id}</strong></div>
            <div><span>Loja</span><strong>#{movement.store_id}</strong></div>
            <div><span>Responsável</span><strong>Utilizador #{movement.actor_user_id}</strong></div>
            <div><span>Snapshot de origem</span><strong>#{movement.source_snapshot_id}</strong></div>
            <div><span>Snapshot resultante</span><strong>#{movement.result_snapshot_id}</strong></div>
            <p><strong>Justificação:</strong> {movement.reason}</p>
            <small>Tipo: {movement.movement_type} · Registo imutável</small>
          </div>}
        </article>;
      })}
    </div>
    {loadedAt && <p className="inventory-history-updated">Atualizado em {formatMovementDate(loadedAt.toISOString())}. A consulta não altera snapshots nem movimentos.</p>}
  </section>;
}
