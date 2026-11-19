import { useMemo, useState, type FormEvent } from "react";
import { ScanSearch, AlertCircle, CheckCircle2, HelpCircle } from "lucide-react";

type Shelf = { id: number; code: string; description: string | null };
type Capture = {
  id: number;
  shelf_id: number;
  original_filename: string;
  analysis_status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  sha256: string;
  created_at: string;
};
type CellComparison = {
  cell_code: string;
  status: "UNKNOWN" | "EMPTY" | "CONFLICT" | "MISPLACED" | "OCCUPIED_UNIDENTIFIED" | "UNDER_FACED" | "OVER_FACED" | "OCCUPIED";
  expected_product_id: number | null;
  expected_facings: number | null;
  observed_facings: number;
  observed_product_ids: Array<number | null>;
  detection_ids: number[];
  overlap_ratio: number;
};
type Comparison = {
  shelf_image_id: number;
  shelf_id: number;
  image_sha256: string;
  model_version: string | null;
  planogram_id: number;
  planogram_version: number;
  calibration_source: "MANUAL" | "IMAGE";
  calibration_image_id: number | null;
  calibration_image_sha256: string | null;
  cells: CellComparison[];
};
type Request = <T,>(path: string, init?: RequestInit) => Promise<T>;

type Props = {
  shelves: Shelf[];
  captures: Capture[];
  request: Request;
};

const statusLabels: Record<CellComparison["status"], string> = {
  UNKNOWN: "Visibilidade desconhecida",
  EMPTY: "Vazio confirmado",
  CONFLICT: "Conflito de deteções",
  MISPLACED: "Produto fora da posição",
  OCCUPIED_UNIDENTIFIED: "Ocupado sem SKU identificado",
  UNDER_FACED: "Menos frentes do que o esperado",
  OVER_FACED: "Mais frentes do que o esperado",
  OCCUPIED: "Ocupado",
};

function formatStatus(status: CellComparison["status"]): string {
  return statusLabels[status] ?? status;
}

export default function PlanogramComparison({ shelves, captures, request }: Props) {
  const [shelfId, setShelfId] = useState("");
  const [captureId, setCaptureId] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const eligibleCaptures = useMemo(
    () => captures.filter(item => item.analysis_status === "COMPLETED" && (!shelfId || String(item.shelf_id) === shelfId)),
    [captures, shelfId],
  );

  const selectedShelf = shelves.find(item => String(item.id) === shelfId);

  async function runComparison(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!shelfId || !captureId) {
      setError("Seleciona uma prateleira e uma captura analisada.");
      return;
    }
    setLoading(true);
    setError("");
    setComparison(null);
    try {
      const result = await request<Comparison>(
        `/api/v1/shelves/${encodeURIComponent(shelfId)}/planograms/comparison/${encodeURIComponent(captureId)}`,
      );
      setComparison(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível comparar a captura com o planograma.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section id="planogram-comparison" className="panel planogram-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">DISPOSIÇÃO ESPERADA</p>
          <h2>Comparação com planograma</h2>
          <p className="muted">Compara deteções persistidas com a versão ativa. A análise é consultiva e não altera inventário nem cria tarefas.</p>
        </div>
        <div className="capture-icon"><ScanSearch size={20} /></div>
      </div>

      <form className="planogram-controls" onSubmit={runComparison}>
        <label>
          Prateleira
          <select value={shelfId} onChange={event => { setShelfId(event.target.value); setCaptureId(""); setComparison(null); setError(""); }} required>
            <option value="">Selecionar prateleira…</option>
            {shelves.map(item => <option key={item.id} value={item.id}>{item.code} · {item.description || `Prateleira #${item.id}`}</option>)}
          </select>
        </label>
        <label>
          Captura concluída
          <select value={captureId} onChange={event => { setCaptureId(event.target.value); setComparison(null); setError(""); }} required disabled={!shelfId || eligibleCaptures.length === 0}>
            <option value="">Selecionar fotografia…</option>
            {eligibleCaptures.map(item => <option key={item.id} value={item.id}>#{item.id} · {item.original_filename} · {new Date(item.created_at).toLocaleString("pt-PT")}</option>)}
          </select>
        </label>
        <button className="row-action" type="submit" disabled={loading || !shelfId || !captureId}>
          <ScanSearch size={14} /> {loading ? "A comparar…" : "Comparar captura"}
        </button>
      </form>

      {!shelfId && <p className="planogram-hint">Seleciona uma prateleira para consultar as capturas concluídas.</p>}
      {shelfId && eligibleCaptures.length === 0 && <p className="planogram-hint">Não existem capturas concluídas para esta prateleira.</p>}
      {error && <div className="error-banner planogram-error" role="alert"><AlertCircle size={16} /> {error}</div>}

      {comparison && (
        <div className="planogram-results" aria-live="polite">
          <div className="planogram-summary">
            <div><span>Prateleira</span><strong>{selectedShelf?.code || `#${comparison.shelf_id}`}</strong></div>
            <div><span>Versão ativa</span><strong>v{comparison.planogram_version}</strong></div>
            <div><span>Células</span><strong>{comparison.cells.length}</strong></div>
            <div><span>Modelo</span><strong>{comparison.model_version || "Não indicado"}</strong></div>
          </div>
          <p className="planogram-provenance">Captura #{comparison.shelf_image_id} · SHA-256 {comparison.image_sha256.slice(0, 16)}… · Calibração {comparison.calibration_source === "IMAGE" ? `por imagem #${comparison.calibration_image_id}` : "manual"}</p>
          {comparison.cells.length === 0 ? (
            <div className="empty-state"><HelpCircle size={22} /><strong>O planograma não tem células</strong><span>Adiciona células à versão ativa para comparar a disposição.</span></div>
          ) : (
            <div className="planogram-cell-list">
              {comparison.cells.map(cell => (
                <article className="planogram-cell" key={cell.cell_code}>
                  <div className="planogram-cell-heading">
                    <strong>{cell.cell_code}</strong>
                    <span className={`planogram-status ${cell.status.toLowerCase()}`}>{cell.status === "OCCUPIED" ? <CheckCircle2 size={12} /> : <HelpCircle size={12} />} {formatStatus(cell.status)}</span>
                  </div>
                  <div className="planogram-cell-metrics">
                    <span>Frentes esperadas: <strong>{cell.expected_facings ?? "Não definido"}</strong></span>
                    <span>Frentes detetadas: <strong>{cell.observed_facings}</strong></span>
                    <span>SKU esperado: <strong>{cell.expected_product_id == null ? "Não definido" : `#${cell.expected_product_id}`}</strong></span>
                    <span>Deteções: <strong>{cell.detection_ids.length ? cell.detection_ids.map(id => `#${id}`).join(", ") : "Nenhuma"}</strong></span>
                  </div>
                  <div className="planogram-overlap"><span>Sobreposição geométrica</span><strong>{(cell.overlap_ratio * 100).toFixed(1)}%</strong></div>
                </article>
              ))}
            </div>
          )}
          <p className="planogram-caveat"><HelpCircle size={14} /> Sem calibração de visibilidade por célula, a ausência de deteções permanece UNKNOWN e não é interpretada como rutura ou vazio.</p>
        </div>
      )}
    </section>
  );
}
