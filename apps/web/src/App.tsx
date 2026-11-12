import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowUpRight, Boxes, CheckCircle2,
  CircleUserRound, Clock3, LogOut, PackageSearch, RefreshCw, ShieldCheck,
  Store, Truck, UserRound, Warehouse, Check, X, History, Image as ImageIcon,
} from "lucide-react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

type Role = "ADMIN" | "SUPERVISOR" | "EMPLOYEE";
type TaskStatus = "PENDING" | "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
type User = { id: number; email: string; full_name: string; role: Role; store_id: number | null; is_active: boolean };
type Task = {
  id: number; store_id: number; shelf_id: number; product_id: number;
  priority: "LOW" | "NORMAL" | "HIGH" | "URGENT"; status: TaskStatus;
  assigned_to: string | null; assigned_user_id: number | null;
  requested_quantity: number | null; notes: string | null; created_at: string;
};
type ShelfImage = { id: number; shelf_id: number; original_filename: string; mime_type: string; file_size_bytes: number; sha256: string; analysis_status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED"; analysis_error: string | null; analysis_started_at: string | null; analysis_completed_at: string | null; captured_at: string; created_at: string };
type ShelfImageDetection = { id: number; shelf_image_id: number; product_id: number | null; label: string; confidence: number; x_min: number; y_min: number; x_max: number; y_max: number; model_version: string; sku_match_status?: "MATCHED" | "AMBIGUOUS" | "UNKNOWN" | null; sku_similarity?: number | null; sku_match_margin?: number | null; created_at: string };
type Product = { id: number; sku: string; name: string; is_active: boolean };
type ShelfProduct = { id: number; shelf_id: number; product_id: number; target_quantity: number; position: number | null };
type DetectionSkuReview = { id: number; detection_id: number; previous_product_id: number | null; selected_product_id: number | null; decision: "CONFIRMED" | "CORRECTED" | "REJECTED"; reviewer_user_id: number | null; notes: string | null; created_at: string };
type ReviewQueueItem = {
  fused_evidence_id: number; detection_id: number; shelf_image_id: number;
  shelf_id: number; shelf_code: string; image_filename: string;
  status: "CONSENSUS" | "VISUAL_ONLY" | "TEXT_ONLY" | "CONFLICT" | "AMBIGUOUS" | "UNKNOWN";
  suggested_product_id: number | null; visual_product_id: number | null; text_product_id: number | null;
  detection_label: string; detection_confidence: number;
  x_min: number; y_min: number; x_max: number; y_max: number;
  visual_similarity: number | null; text_score: number | null; ocr_confidence: number | null;
  visual_model_version: string | null; ocr_provider: string; ocr_model_version: string;
  reason: string; created_at: string;
};
type ReviewQueueSummary = Record<ReviewQueueItem["status"], number>;
type ReviewEvaluationReport = {
  sample_count: number; known_ground_truth_count: number; unknown_ground_truth_count: number;
  predicted_sku_count: number; correct_matches: number; incorrect_known_matches: number;
  missed_known_products: number; false_accepts_on_rejected_detections: number;
  correct_abstentions: number; accuracy_including_abstentions: number | null;
  precision_when_sku_predicted: number | null; known_product_coverage: number | null;
  known_product_correct_coverage: number | null; unknown_rejection_rate: number | null;
  unknown_false_accept_rate: number | null; fusion_status_breakdown: Record<string, number>;
  human_decision_breakdown: Record<string, number>;
  reviewed_detections_without_matching_fusion: number; model_version_filter: string | null;
};
type PlannedTask = {
  shelf_id: number; product_id: number; shelf_code?: string; product_name?: string;
  recommendation_status: string; proposed_priority: string; stockout_risk_level?: string;
  stockout_explanation?: string; estimated_elapsed_minutes?: number | null;
  effort_estimate_status?: string; effort_estimate_basis?: string;
  suggested_quantity?: number | null; explanation?: string; task_creation_allowed: boolean;
};
type ReplenishmentPlan = {
  store_id: number; total_candidates: number; returned_candidates: number;
  groups: { zone_id: number | null; zone_name: string; tasks: PlannedTask[] }[];
  excluded: Record<string, number>;
  risk_assessment: { enabled: boolean; history_days: number | null };
  effort_estimation: { enabled: boolean; estimated_candidates?: number; unestimated_candidates?: number; estimated_total_elapsed_minutes?: number; metric?: string | null };
  warehouse_pick_plan?: {
    enabled: boolean; status: string; read_only: boolean;
    stock_reserved: boolean; stock_movement_allowed: boolean;
    products?: { product_id: number; required_quantity: number; allocated_quantity: number; shortfall_quantity: number; status: string; temperature_requirement: string | null }[];
    stops?: { sequence: number; location_code: string; aisle?: string | null; rack?: string | null; bin_code?: string | null; distance_to_picking_m: number; items: { product_id: number; proposed_pick_quantity: number }[] }[];
    summary?: { products_with_demand: number; ready_for_review: number; partial_stock: number; blocked: number; proposed_pick_lines: number; warehouse_stops: number; total_proposed_units: number; total_shortfall_units: number };
    route_basis?: string; physical_route_optimized?: boolean; distance_metric?: string;
  };
  automatic_stock_movement_allowed: boolean;
};
type OperationalDecision = {
  status: "INSUFFICIENT_EVIDENCE" | "MONITOR" | "ACTION_RECOMMENDED" | "ALREADY_IN_PROGRESS" | string;
  priority: "NONE" | "NORMAL" | "HIGH" | string;
  reason: string;
  suggested_replenishment_quantity: number | null;
  inventory_coverage_hours?: number | null;
  requires_human_approval: boolean;
  automatic_stock_movement_allowed: boolean;
  warnings: string[];
  evidence: { type: string; status?: string; confidence?: number | null; available_quantity?: number; predicted_units?: number; fresh?: boolean; source?: string }[];
};
type OperationalDecisionRow = {
  store_id: number; zone_name: string; shelf_id: number; shelf_code: string;
  product_id: number; product_sku: string; product_name: string;
  decision: OperationalDecision;
};
type OperationalDecisionResponse = {
  generated_at: string; count: number; status_counts: Record<string, number>;
  forecast_policy: string; decisions: OperationalDecisionRow[];
};
type Summary = {
  store_id: number | null; role: Role; active_tasks: number;
  shelves_requiring_attention: number;
  tasks: Record<string, number>; observations: Record<string, number>; note: string;
};

function apiError(message: string) { throw new Error(message); }

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem("smart-shelf-token") || "");
  const [user, setUser] = useState<User | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [storeFilter, setStoreFilter] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [operationalDecisions, setOperationalDecisions] = useState<OperationalDecisionResponse | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [captures, setCaptures] = useState<ShelfImage[]>([]);
  const [imageDetections, setImageDetections] = useState<Record<number, ShelfImageDetection[]>>({});
  const [imageUrls, setImageUrls] = useState<Record<number, string>>({});
  const [detectionReviews, setDetectionReviews] = useState<Record<number, DetectionSkuReview[]>>({});
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [reviewQueueSummary, setReviewQueueSummary] = useState<ReviewQueueSummary | null>(null);
  const [reviewEvaluation, setReviewEvaluation] = useState<ReviewEvaluationReport | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [shelfProducts, setShelfProducts] = useState<Record<number, number[]>>({});
  const [reviewProductSelection, setReviewProductSelection] = useState<Record<number, string>>({});
  const [reviewLoading, setReviewLoading] = useState<number | null>(null);
  const [expandedDetectionImage, setExpandedDetectionImage] = useState<number | null>(null);
  const [detectionLoading, setDetectionLoading] = useState<number | null>(null);
  const [retryLoading, setRetryLoading] = useState<number | null>(null);
  const [captureShelfId, setCaptureShelfId] = useState("");
  const [captureFile, setCaptureFile] = useState<File | null>(null);
  const [captureReset, setCaptureReset] = useState(0);
  const [captureLoading, setCaptureLoading] = useState(false);
  const [captureMessage, setCaptureMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [replenishmentPlan, setReplenishmentPlan] = useState<ReplenishmentPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState("");


  const request = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) apiError(payload.detail || `Erro HTTP ${response.status}`);
    return payload as T;
  }, [token]);

  const logout = useCallback(() => {
    sessionStorage.removeItem("smart-shelf-token");
    Object.values(imageUrls).forEach(url => URL.revokeObjectURL(url));
    setImageUrls({});
    setToken(""); setUser(null); setSummary(null); setOperationalDecisions(null); setTasks([]); setCaptures([]); setImageDetections({}); setDetectionReviews({}); setExpandedDetectionImage(null);
  }, [imageUrls]);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true); setError("");
    try {
      const query = storeFilter.trim() ? `?store_id=${encodeURIComponent(storeFilter.trim())}` : "";
      const [me, kpis, taskList, captureList] = await Promise.all([
        request<User>("/api/v1/auth/me"),
        request<Summary>(`/api/v1/dashboard/summary${query}`),
        request<Task[]>("/api/v1/tasks?limit=100"),
        request<ShelfImage[]>("/api/v1/shelf-images?limit=30"),
      ]);
      setUser(me); setSummary(kpis); setTasks(taskList); setCaptures(captureList); setLastUpdated(new Date());
      if (me.role === "ADMIN" || me.role === "SUPERVISOR") {
        setDecisionLoading(true);
        try {
          const decisionQuery = me.role === "ADMIN" && storeFilter.trim()
            ? `?store_id=${encodeURIComponent(storeFilter.trim())}`
            : "";
          const decisions = await request<OperationalDecisionResponse>(`/api/v1/operational-decisions${decisionQuery}`);
          setOperationalDecisions(decisions);
        } catch (decisionError) {
          setOperationalDecisions(null);
          setError(decisionError instanceof Error ? decisionError.message : "Não foi possível carregar as decisões operacionais.");
        } finally {
          setDecisionLoading(false);
        }
      } else {
        setOperationalDecisions(null);
      }
      if (me.role === "ADMIN" || me.role === "SUPERVISOR") {
        try {
          const [queue, queueSummary, evaluation] = await Promise.all([
            request<ReviewQueueItem[]>("/api/v1/shelf-image-review-queue?limit=50"),
            request<ReviewQueueSummary>("/api/v1/shelf-image-review-queue/summary"),
            request<ReviewEvaluationReport>("/api/v1/sku-evaluation/reviewed"),
          ]);
          setReviewQueue(queue);
          setReviewQueueSummary(queueSummary);
          setReviewEvaluation(evaluation);
        } catch (queueError) {
          setReviewQueue([]);
          setReviewQueueSummary(null);
          setReviewEvaluation(null);
          setError(queueError instanceof Error ? queueError.message : "Não foi possível carregar a fila de revisão.");
        }
      } else {
        setReviewQueue([]);
        setReviewQueueSummary(null);
        setReviewEvaluation(null);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível carregar os dados.";
      setError(message);
      if (/token|autentic|401/i.test(message)) logout();
    } finally { setLoading(false); }
  }, [token, storeFilter, request, logout]);

  useEffect(() => { if (token) void refresh(); }, [token, refresh]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError("");
    try {
      const result = await request<{ access_token: string; token_type: string }>("/api/v1/auth/login", {
        method: "POST", body: JSON.stringify({ email, password }),
      });
      sessionStorage.setItem("smart-shelf-token", result.access_token);
      setToken(result.access_token); setPassword("");
    } catch (err) { setError(err instanceof Error ? err.message : "Falha no início de sessão."); }
    finally { setLoading(false); }
  }

  async function updateTask(task: Task, status: "ASSIGNED" | "IN_PROGRESS" | "COMPLETED", assignedUserId?: number) {
    setError("");
    try {
      await request<Task>(`/api/v1/tasks/${task.id}/status`, {
        method: "PATCH", body: JSON.stringify({ status, ...(assignedUserId ? { assigned_user_id: assignedUserId } : {}) }),
      });
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Não foi possível atualizar a tarefa."); }
  }

 
  async function loadReplenishmentPlan() {
    const selectedStoreId = user?.role === "ADMIN" ? Number(storeFilter) : Number(user?.store_id);
    if (!Number.isInteger(selectedStoreId) || selectedStoreId < 1) {
      setPlanError("Indica um ID de loja válido para gerar o plano.");
      return;
    }
    setPlanLoading(true);
    setPlanError("");
    try {
      const plan = await request<ReplenishmentPlan>(
        `/api/v1/replenishment/plan?store_id=${selectedStoreId}&include_stockout_risk=true&risk_days=28&include_effort_estimates=true&effort_history_days=90&effort_minimum_sample_size=5&include_warehouse_pick_plan=true`
      );
      setReplenishmentPlan(plan);
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : "Não foi possível gerar o plano de reposição.");
    } finally {
      setPlanLoading(false);
    }
  }

  async function uploadCapture(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!captureShelfId.trim() || !captureFile) {
      setCaptureMessage("Indica o ID da prateleira e seleciona uma fotografia.");
      return;
    }
    setCaptureLoading(true); setCaptureMessage("");
    try {
      const form = new FormData();
      form.append("shelf_id", captureShelfId.trim());
      form.append("image", captureFile);
      const response = await fetch(`${API_BASE}/api/v1/shelf-images`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
      setCaptureMessage(`Fotografia #${payload.id} recebida. Estado: ${payload.analysis_status}.`);
      setCaptureFile(null); setCaptureReset(value => value + 1);
      await refresh();
    } catch (err) {
      setCaptureMessage(err instanceof Error ? err.message : "Não foi possível enviar a fotografia.");
    } finally { setCaptureLoading(false); }
  }



  async function retryImageAnalysis(item: ShelfImage) {
    setRetryLoading(item.id);
    try {
      const updated = await request<ShelfImage>(`/api/v1/shelf-images/${item.id}/retry`, { method: "POST" });
      setCaptures(current => current.map(capture => capture.id === item.id ? updated : capture));
      setImageDetections(current => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      setCaptureMessage(`A análise da fotografia #${item.id} foi colocada novamente na fila.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível repetir a análise.");
    } finally {
      setRetryLoading(null);
    }
  }


  async function toggleImageDetections(item: ShelfImage) {
    if (expandedDetectionImage === item.id) {
      setExpandedDetectionImage(null);
      return;
    }
    setExpandedDetectionImage(item.id);
    if (imageDetections[item.id]) return;
    setDetectionLoading(item.id);
    try {
      const [result, imageResponse] = await Promise.all([
        request<ShelfImageDetection[]>(`/api/v1/shelf-images/${item.id}/detections`),
        fetch(`${API_BASE}/api/v1/shelf-images/${item.id}/content`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      const canReview = user?.role === "ADMIN" || user?.role === "SUPERVISOR";
      if (canReview) {
        const [activeProducts, assignedProducts] = await Promise.all([
          request<Product[]>("/api/v1/products?active_only=true&limit=500"),
          request<ShelfProduct[]>(`/api/v1/shelf-products?shelf_id=${item.shelf_id}`),
        ]);
        setProducts(activeProducts);
        setShelfProducts(current => ({ ...current, [item.shelf_id]: assignedProducts.map(link => link.product_id) }));
      }
      if (!imageResponse.ok) {
        const body = await imageResponse.json().catch(() => ({}));
        throw new Error(body.detail || `Não foi possível abrir a fotografia (HTTP ${imageResponse.status}).`);
      }
      const blobUrl = URL.createObjectURL(await imageResponse.blob());
      setImageUrls(current => {
        if (current[item.id]) URL.revokeObjectURL(current[item.id]);
        return { ...current, [item.id]: blobUrl };
      });
      setImageDetections(current => ({ ...current, [item.id]: result }));
      const reviewPairs = await Promise.all(result.map(async detection => {
        const history = await request<DetectionSkuReview[]>(`/api/v1/shelf-image-detections/${detection.id}/reviews`);
        return [detection.id, history] as const;
      }));
      setDetectionReviews(current => ({ ...current, ...Object.fromEntries(reviewPairs) }));
      setReviewProductSelection(current => {
        const next = { ...current };
        result.forEach(detection => {
          if (next[detection.id] === undefined) next[detection.id] = detection.product_id ? String(detection.product_id) : "";
        });
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível consultar as deteções.");
      setExpandedDetectionImage(null);
    } finally {
      setDetectionLoading(null);
    }
  }

  function openQueueImage(item: ReviewQueueItem) {
    const capture = captures.find(image => image.id === item.shelf_image_id);
    if (!capture) {
      setError("Esta fotografia já não está na lista das 30 capturas recentes. Consulta o registo da imagem pela API.");
      return;
    }
    if (expandedDetectionImage !== capture.id) void toggleImageDetections(capture);
  }

  async function reviewDetection(detection: ShelfImageDetection, decision: "CONFIRMED" | "CORRECTED" | "REJECTED") {
    const selected = reviewProductSelection[detection.id] || "";
    if (decision !== "REJECTED" && !selected) {
      setError("Seleciona um produto atribuído a esta prateleira.");
      return;
    }
    if (decision === "CONFIRMED" && Number(selected) !== detection.product_id) {
      setError("Para confirmar, seleciona o SKU proposto. Usa corrigir para escolher outro produto.");
      return;
    }
    setReviewLoading(detection.id);
    setError("");
    try {
      const created = await request<DetectionSkuReview>(`/api/v1/shelf-image-detections/${detection.id}/reviews`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          ...(decision === "REJECTED" ? {} : { selected_product_id: Number(selected) }),
        }),
      });
      setDetectionReviews(current => ({
        ...current,
        [detection.id]: [...(current[detection.id] || []), created],
      }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível guardar a revisão.");
    } finally {
      setReviewLoading(null);
    }
  }

  const taskRows = useMemo(() => tasks.filter(t => !["CANCELLED"].includes(t.status)), [tasks]);
  const taskTotal = summary ? Object.values(summary.tasks).reduce((a, b) => a + b, 0) : 0;

  if (!token) return (
    <main className="login-shell">
      <section className="login-card">
        <div className="brand-mark"><Warehouse size={25} /></div>
        <p className="eyebrow">SMART SHELF AI · OPERATIONS</p>
        <h1>Bem-vindo de volta.</h1>
        <p className="muted">Entre para consultar o estado das prateleiras e as tarefas da sua loja.</p>
        <form onSubmit={login} className="login-form">
          <label>Email profissional<input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" required placeholder="nome@empresa.pt" /></label>
          <label>Palavra-passe<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required placeholder="A sua palavra-passe" /></label>
          {error && <p className="error-banner" role="alert">{error}</p>}
          <button className="primary-button" disabled={loading}>{loading ? "A autenticar…" : "Iniciar sessão"} <ArrowUpRight size={17} /></button>
        </form>
        <p className="login-foot"><ShieldCheck size={15} /> Acesso protegido por token de sessão.</p>
      </section>
      <aside className="login-art"><div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" /><div className="art-content"><Boxes size={54} /><span>Da prateleira à decisão.</span><p>Visibilidade operacional, reposição assistida e controlo de inventário.</p></div></aside>
    </main>
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><div className="brand-mark small"><Warehouse size={20} /></div><div><strong>SMART SHELF</strong><span>INTELLIGENCE PLATFORM</span></div></div>
        <div className="nav-label">ESPAÇO DE TRABALHO</div>
        <div className="nav-item active"><Activity size={18} /> Visão geral</div>
        <div className="nav-item"><PackageSearch size={18} /> Tarefas de reposição <span className="nav-count">{summary?.active_tasks ?? "—"}</span></div>
        <div className="nav-item"><Store size={18} /> Operação da loja</div>
        <div className="sidebar-bottom"><div className="status-dot" /> API ligada por sessão</div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div><p className="eyebrow">OPERAÇÕES / DASHBOARD</p><h1>Visão geral</h1></div>
          <div className="top-actions">
            <button className="icon-button" onClick={() => void refresh()} title="Atualizar dados" disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} /></button>
            <div className="user-chip"><div className="avatar"><UserRound size={17} /></div><div><strong>{user?.full_name || "A carregar…"}</strong><span>{user?.role || "Sessão"}</span></div></div>
            <button className="icon-button" onClick={logout} title="Terminar sessão"><LogOut size={17} /></button>
          </div>
        </header>
        <section className="toolbar">
          <div><span className="live-dot" /> <strong>Dados operacionais</strong><span className="muted"> · {lastUpdated ? `Atualizado às ${lastUpdated.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}` : "A sincronizar"}</span></div>
          {user?.role === "ADMIN" && <label className="store-filter"><Store size={15} /><input aria-label="Filtrar por ID da loja" placeholder="Todas as lojas · ID opcional" value={storeFilter} onChange={e => setStoreFilter(e.target.value)} onKeyDown={e => { if (e.key === "Enter") void refresh(); }} /><button onClick={() => void refresh()}>Aplicar</button></label>}
        </section>
        {error && <div className="error-banner page-error" role="alert"><AlertTriangle size={17} /> {error}</div>}
        {summary && <>
          <section className="metric-grid">
            <Metric icon={<AlertTriangle />} label="Prateleiras a necessitar de atenção" value={summary.shelves_requiring_attention} tone="orange" detail="Rutura ou stock baixo" />
            <Metric icon={<Clock3 />} label="Tarefas ativas" value={summary.active_tasks} tone="blue" detail="Pendentes, atribuídas ou em curso" />
            <Metric icon={<CheckCircle2 />} label="Tarefas concluídas" value={summary.tasks.completed || 0} tone="green" detail="No conjunto de registos consultado" />
            <Metric icon={<Truck />} label="Tarefas urgentes" value={tasks.filter(t => t.priority === "URGENT" && !["COMPLETED", "CANCELLED"].includes(t.status)).length} tone="purple" detail="A aguardar intervenção" />
          </section>
          <section className="content-grid">
            <article className="panel task-panel">
              <div className="panel-heading"><div><p className="eyebrow">EXECUÇÃO</p><h2>Tarefas de reposição</h2><p className="muted">Acompanhamento das intervenções registadas na API.</p></div><span className="subtle-pill">{taskRows.length} registos</span></div>
              <div className="task-list">
                {taskRows.length === 0 && <div className="empty-state"><PackageSearch size={28} /><strong>Sem tarefas registadas</strong><span>Quando forem criadas tarefas, aparecerão aqui.</span></div>}
                {taskRows.map(task => <TaskRow key={task.id} task={task} canAssign={user?.role === "ADMIN" || user?.role === "SUPERVISOR"} canProgress={user?.role === "EMPLOYEE" ? task.assigned_user_id === user.id : user?.role === "ADMIN" || user?.role === "SUPERVISOR"} onUpdate={updateTask} />)}
              </div>
            </article>
            <article className="panel status-panel">
              <div className="panel-heading"><div><p className="eyebrow">RESUMO</p><h2>Estado das tarefas</h2><p className="muted">Distribuição por estado.</p></div></div>
              <div className="status-total"><strong>{taskTotal}</strong><span>tarefas no total</span></div>
              <StatusBar label="Pendentes" value={summary.tasks.pending || 0} total={taskTotal} color="amber" />
              <StatusBar label="Atribuídas" value={summary.tasks.assigned || 0} total={taskTotal} color="violet" />
              <StatusBar label="Em execução" value={summary.tasks.in_progress || 0} total={taskTotal} color="blue" />
              <StatusBar label="Concluídas" value={summary.tasks.completed || 0} total={taskTotal} color="green" />
              <div className="panel-note"><AlertTriangle size={16} /><span>{summary.observations.empty || 0} prateleiras sem stock e {summary.observations.low_stock || 0} com stock baixo, segundo as observações registadas.</span></div>
            </article>
          </section>
          {(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && <section className="panel decision-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">INTELIGÊNCIA OPERACIONAL</p><h2>Decisões e alertas por prateleira</h2><p className="muted">Cruza observações, inventário, vendas recentes e tarefas ativas. Apenas recomenda; não cria tarefas nem altera stock.</p></div>
              <button className="row-action" onClick={() => void refresh()} disabled={loading || decisionLoading}>{decisionLoading ? "A atualizar…" : "Atualizar decisões"} <RefreshCw size={14} /></button>
            </div>
            {decisionLoading && !operationalDecisions && <div className="loading-state">A avaliar evidência operacional…</div>}
            {operationalDecisions && <>
              <div className="decision-counts">
                <div><span>Itens avaliados</span><strong>{operationalDecisions.count}</strong></div>
                <div><span>Ação recomendada</span><strong>{operationalDecisions.status_counts.ACTION_RECOMMENDED || 0}</strong></div>
                <div><span>Em acompanhamento</span><strong>{operationalDecisions.status_counts.MONITOR || 0}</strong></div>
                <div><span>Já em execução</span><strong>{operationalDecisions.status_counts.ALREADY_IN_PROGRESS || 0}</strong></div>
              </div>
              <p className="decision-method">{operationalDecisions.forecast_policy}</p>
              <div className="decision-list">
                {operationalDecisions.decisions.length === 0 && <div className="empty-state"><ShieldCheck size={24} /><strong>Sem produtos associados a prateleiras</strong><span>Quando existirem associações e evidência registada, o motor apresentará as decisões aqui.</span></div>}
                {operationalDecisions.decisions.map(item => <article className="decision-row" key={`${item.shelf_id}-${item.product_id}`}>
                  <div className="decision-product"><strong>{item.product_name}</strong><span>{item.product_sku} · {item.zone_name} · Prateleira {item.shelf_code}</span></div>
                  <span className={`decision-status ${item.decision.status.toLowerCase()}`}>{item.decision.status === "ACTION_RECOMMENDED" ? "Requer avaliação" : item.decision.status === "ALREADY_IN_PROGRESS" ? "Tarefa ativa" : item.decision.status === "INSUFFICIENT_EVIDENCE" ? "Dados insuficientes" : "Monitorizar"}</span>
                  <p>{item.decision.reason}</p>
                  <div className="decision-meta">
                    <span>Prioridade: <strong>{item.decision.priority}</strong></span>
                    <span>Quantidade sugerida: <strong>{item.decision.suggested_replenishment_quantity == null ? "Não calculada" : item.decision.suggested_replenishment_quantity}</strong></span>
                    <span>Cobertura estimada: <strong>{item.decision.inventory_coverage_hours == null ? "—" : `${item.decision.inventory_coverage_hours.toFixed(1)} h`}</strong></span><span>Fontes: <strong>{item.decision.evidence.length}</strong></span>
                  </div>
                  {item.decision.warnings.length > 0 && <ul className="decision-warnings">{item.decision.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
                </article>)}
              </div>
              <p className="decision-method">Gerado em {new Date(operationalDecisions.generated_at).toLocaleString("pt-PT")}. Todas as recomendações requerem validação humana.</p>
            </>}
          </section>}
          {(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && <section className="panel replenishment-plan-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">PLANEAMENTO ASSISTIDO</p><h2>Plano inteligente de reposição</h2><p className="muted">Prioriza por risco de rutura e estima esforço quando existe histórico suficiente.</p></div>
              <button className="row-action" onClick={() => void loadReplenishmentPlan()} disabled={planLoading || (user?.role === "ADMIN" && !storeFilter.trim())}>
                {planLoading ? "A calcular…" : replenishmentPlan ? "Atualizar plano" : "Gerar plano"} <ArrowUpRight size={14} />
              </button>
            </div>
            {user?.role === "ADMIN" && !storeFilter.trim() && <p className="plan-hint">Para administradores, indica primeiro o ID da loja no filtro superior.</p>}
            {planError && <p className="plan-error" role="alert">{planError}</p>}
            {replenishmentPlan && <>
              <div className="plan-metrics">
                <div><span>Candidatos</span><strong>{replenishmentPlan.total_candidates}</strong></div>
                <div><span>Incluídos no plano</span><strong>{replenishmentPlan.returned_candidates}</strong></div>
                <div><span>Com estimativa de esforço</span><strong>{replenishmentPlan.effort_estimation.estimated_candidates ?? 0}</strong></div>
                <div><span>Minutos estimados</span><strong>{replenishmentPlan.effort_estimation.estimated_total_elapsed_minutes == null ? "—" : replenishmentPlan.effort_estimation.estimated_total_elapsed_minutes.toFixed(0)}</strong></div>
              </div>
              <p className="plan-hint">Risco de rutura baseado em 28 dias de vendas; estimativas de tempo baseadas em tarefas concluídas. Tempo decorrido não equivale a trabalho ativo. Movimentação automática de stock: desativada.</p>
              {replenishmentPlan.warehouse_pick_plan?.enabled && <div className="warehouse-pick-summary">
                <div className="plan-zone-heading"><strong>Picking da retaguarda</strong><span>{replenishmentPlan.warehouse_pick_plan.summary?.warehouse_stops ?? 0} localizações</span></div>
                <div className="plan-metrics">
                  <div><span>Produtos cobertos</span><strong>{replenishmentPlan.warehouse_pick_plan.summary?.ready_for_review ?? 0}</strong></div>
                  <div><span>Parcial / bloqueado</span><strong>{(replenishmentPlan.warehouse_pick_plan.summary?.partial_stock ?? 0) + (replenishmentPlan.warehouse_pick_plan.summary?.blocked ?? 0)}</strong></div>
                  <div><span>Unidades propostas</span><strong>{replenishmentPlan.warehouse_pick_plan.summary?.total_proposed_units ?? 0}</strong></div>
                  <div><span>Unidades em falta</span><strong>{replenishmentPlan.warehouse_pick_plan.summary?.total_shortfall_units ?? 0}</strong></div>
                </div>
                <p className="plan-hint">Proposta não vinculativa. Stock não reservado; confirmar disponibilidade e compatibilidade antes da recolha. Distâncias referem-se ao ponto de picking, não a percursos entre localizações.</p>
                {(replenishmentPlan.warehouse_pick_plan.stops ?? []).map(stop => <div className="pick-stop" key={stop.location_code}>
                  <div><strong>{stop.sequence}. {stop.location_code}</strong><span>{[stop.aisle, stop.rack, stop.bin_code].filter(Boolean).join(" · ") || "Localização"}</span></div>
                  <span>{stop.distance_to_picking_m} m</span>
                  <span>{stop.items.map(item => `SKU #${item.product_id}: ${item.proposed_pick_quantity}`).join(" · ")}</span>
                </div>)}
              </div>}
              <div className="plan-groups">
                {replenishmentPlan.groups.length === 0 && <div className="empty-state"><CheckCircle2 size={24} /><strong>Sem candidatos para reposição</strong><span>Não existem recomendações elegíveis nesta consulta.</span></div>}
                {replenishmentPlan.groups.map(group => <div className="plan-zone" key={group.zone_id ?? group.zone_name}>
                  <div className="plan-zone-heading"><strong>{group.zone_name}</strong><span>{group.tasks.length} itens</span></div>
                  {group.tasks.map(item => <div className="plan-task" key={`${item.shelf_id}-${item.product_id}`}>
                    <div><strong>{item.product_name || `Produto #${item.product_id}`}</strong><span>Prateleira {item.shelf_code || `#${item.shelf_id}`} · {item.recommendation_status}</span></div>
                    <span className={`plan-risk ${(item.stockout_risk_level || "UNKNOWN").toLowerCase()}`}>{item.stockout_risk_level || "UNKNOWN"}</span>
                    <span className="plan-duration">{item.estimated_elapsed_minutes == null ? "Tempo —" : `${item.estimated_elapsed_minutes.toFixed(0)} min`}</span>
                    {!item.task_creation_allowed && <span className="plan-review">Requer validação</span>}
                  </div>)}
                </div>)}
              </div>
            </>}
          </section>}
          <section className="capture-grid">
            <article className="panel capture-panel">
              <div className="panel-heading"><div><p className="eyebrow">VISÃO COMPUTACIONAL</p><h2>Nova captura de prateleira</h2><p className="muted">Envia uma fotografia para registo e futura análise automática.</p></div><div className="capture-icon"><PackageSearch size={20} /></div></div>
              <form className="capture-form" onSubmit={uploadCapture}>
                <label>ID da prateleira<input type="number" min="1" value={captureShelfId} onChange={e => setCaptureShelfId(e.target.value)} placeholder="Ex.: 12" required /></label>
                <label>Fotografia (JPEG, PNG ou WebP)<input key={captureReset} type="file" accept="image/jpeg,image/png,image/webp" onChange={e => setCaptureFile(e.target.files?.[0] || null)} required /></label>
                <div className="capture-submit"><span>{captureFile ? captureFile.name : "Nenhum ficheiro selecionado"}</span><button className="row-action" disabled={captureLoading || !captureFile}>{captureLoading ? "A enviar…" : "Enviar fotografia"} <ArrowUpRight size={14} /></button></div>
                {captureMessage && <p className="capture-feedback" role="status">{captureMessage}</p>}
              </form>
            </article>
            <article className="panel capture-history">
              <div className="panel-heading"><div><p className="eyebrow">REGISTO DE CAPTURAS</p><h2>Fotografias recentes</h2><p className="muted">As imagens ficam pendentes até existir um modelo de análise.</p></div><span className="subtle-pill">{captures.length} capturas</span></div>
              <div className="capture-list">
                {captures.length === 0 && <div className="empty-state"><PackageSearch size={25} /><strong>Sem fotografias registadas</strong><span>As próximas capturas serão apresentadas aqui.</span></div>}
                {captures.map(item => <div className="capture-item" key={item.id}>
                  <div className="capture-row"><div className="capture-thumb"><Boxes size={17} /></div><div className="capture-meta"><strong>Prateleira #{item.shelf_id} · {item.original_filename}</strong><span>{(item.file_size_bytes / 1024).toFixed(0)} KB · {new Date(item.created_at).toLocaleString("pt-PT")}</span></div><span className={`task-status ${item.analysis_status.toLowerCase()}`}>{item.analysis_status}</span>{(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && item.analysis_status === "FAILED" && <button className="row-action detection-toggle" disabled={retryLoading === item.id} onClick={() => void retryImageAnalysis(item)}>{retryLoading === item.id ? "A repetir…" : "Repetir análise"}</button>}<button className="row-action detection-toggle" onClick={() => void toggleImageDetections(item)}>{detectionLoading === item.id ? "A consultar…" : expandedDetectionImage === item.id ? "Fechar" : "Deteções"}</button></div>
                  {expandedDetectionImage === item.id && <div className="detection-workspace">
                    {imageUrls[item.id] && <div className="detection-image-stage">
                      <img src={imageUrls[item.id]} alt={`Fotografia da prateleira ${item.shelf_id}`} />
                      {imageDetections[item.id]?.map(detection => <div key={detection.id} className={`detection-box ${(detectionReviews[detection.id] || []).length ? "reviewed" : ""}`} style={{ left: `${detection.x_min * 100}%`, top: `${detection.y_min * 100}%`, width: `${(detection.x_max - detection.x_min) * 100}%`, height: `${(detection.y_max - detection.y_min) * 100}%` }}><span>#{detection.id}</span></div>)}
                    </div>}
                    {!imageDetections[item.id]?.length && <p className="detection-empty">{item.analysis_status === "COMPLETED" ? "A análise terminou sem registar objetos nesta fotografia." : item.analysis_status === "FAILED" ? `A análise falhou. ${item.analysis_error || "Pode ser repetida por um supervisor."}` : item.analysis_status === "PROCESSING" ? "A fotografia está a ser analisada pelo worker." : "Ainda não existem deteções guardadas. A fotografia aguarda processamento."}</p>}
                    {imageDetections[item.id]?.map(detection => {
                      const assignedIds = shelfProducts[item.shelf_id] || [];
                      const selectableProducts = products.filter(product => assignedIds.includes(product.id));
                      const history = detectionReviews[detection.id] || [];
                      const selectedId = reviewProductSelection[detection.id] || "";
                      const canReview = user?.role === "ADMIN" || user?.role === "SUPERVISOR";
                      return <article className="detection-review-card" key={detection.id}>
                        <div className="detection-review-heading"><div><strong>Deteção #{detection.id} · {detection.label}</strong><span>{(detection.confidence * 100).toFixed(1)}% confiança · {detection.sku_match_status || "Estado SKU não disponível"}</span></div><span className={`review-state ${history.length ? "reviewed" : "pending"}`}>{history.length ? "Com revisão" : "Por rever"}</span></div>
                        <div className="detection-review-meta"><span>SKU proposto: <strong>{detection.product_id ? `#${detection.product_id}` : "Sem correspondência"}</strong></span><span>Modelo: {detection.model_version}</span>{detection.sku_similarity !== null && detection.sku_similarity !== undefined && <span>Similaridade: {(detection.sku_similarity * 100).toFixed(1)}%</span>}</div>
                        {canReview && <div className="review-controls">
                          <label>Produto atribuído à prateleira
                            <select value={selectedId} onChange={event => setReviewProductSelection(current => ({ ...current, [detection.id]: event.target.value }))}>
                              <option value="">Selecionar produto…</option>
                              {selectableProducts.map(product => <option key={product.id} value={product.id}>{product.sku} — {product.name}</option>)}
                            </select>
                          </label>
                          <div className="review-actions">
                            <button className="review-button confirm" disabled={reviewLoading === detection.id || !detection.product_id || Number(selectedId) !== detection.product_id} onClick={() => void reviewDetection(detection, "CONFIRMED")}><Check size={14} /> Confirmar</button>
                            <button className="review-button correct" disabled={reviewLoading === detection.id || !selectedId || Number(selectedId) === detection.product_id} onClick={() => void reviewDetection(detection, "CORRECTED")}><ImageIcon size={14} /> Corrigir</button>
                            <button className="review-button reject" disabled={reviewLoading === detection.id} onClick={() => void reviewDetection(detection, "REJECTED")}><X size={14} /> Rejeitar</button>
                          </div>
                        </div>}
                        <div className="review-history">
                          <strong><History size={14} /> Histórico ({history.length})</strong>
                          {history.length === 0 && <span>Sem decisões humanas registadas.</span>}
                          {history.map(review => <div className="review-history-row" key={review.id}><span>{review.decision === "CONFIRMED" ? "Confirmado" : review.decision === "CORRECTED" ? "Corrigido" : "Rejeitado"}</span><span>{review.selected_product_id ? `Produto #${review.selected_product_id}` : "Sem SKU"}</span><time>{new Date(review.created_at).toLocaleString("pt-PT")}</time>{review.notes && <small>{review.notes}</small>}</div>)}
                        </div>
                      </article>;
                    })}
                  </div>}
                </div>)}
              </div>
            </article>
          </section>
          {(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && <section className="panel review-queue-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">CONTROLO DE QUALIDADE</p><h2>Fila de revisão de SKU</h2><p className="muted">Sugestões da fusão visual + OCR que aguardam decisão humana.</p></div>
              <span className="subtle-pill">{reviewQueue.length} itens prioritários</span>
            </div>
            {reviewQueueSummary && <div className="review-queue-counts">
              {(["CONFLICT", "AMBIGUOUS", "TEXT_ONLY", "UNKNOWN", "VISUAL_ONLY", "CONSENSUS"] as const).map(status => <div key={status} className={`review-queue-count ${status.toLowerCase()}`}><span>{status === "CONFLICT" ? "Conflito" : status === "AMBIGUOUS" ? "Ambíguo" : status === "TEXT_ONLY" ? "Só OCR" : status === "UNKNOWN" ? "Desconhecido" : status === "VISUAL_ONLY" ? "Só visual" : "Consenso"}</span><strong>{reviewQueueSummary[status] || 0}</strong></div>)}
            </div>}
            <div className="review-queue-list">
              {reviewQueue.length === 0 && <div className="empty-state"><ShieldCheck size={25} /><strong>Sem revisões pendentes</strong><span>Quando existirem resultados de OCR e fusão, os casos a validar aparecerão aqui.</span></div>}
              {reviewQueue.map(item => <article className="review-queue-row" key={item.fused_evidence_id}>
                <div className="review-queue-main">
                  <div><strong>Prateleira {item.shelf_code} · Deteção #{item.detection_id}</strong><span>{item.image_filename} · {new Date(item.created_at).toLocaleString("pt-PT")}</span></div>
                  <span className={`review-queue-status ${item.status.toLowerCase()}`}>{item.status}</span>
                </div>
                <p>{item.reason}</p>
                <div className="review-queue-meta"><span>Visual: {item.visual_product_id ? `SKU #${item.visual_product_id}` : "sem candidato"}</span><span>OCR: {item.text_product_id ? `SKU #${item.text_product_id}` : "sem candidato"}</span><span>Proposta: {item.suggested_product_id ? `SKU #${item.suggested_product_id}` : "abstenção"}</span></div>
                <div className="review-queue-actions"><button className="row-action" onClick={() => openQueueImage(item)}>Abrir fotografia e rever <ArrowUpRight size={14} /></button></div>
              </article>)}
            </div>
          </section>}
          {(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && reviewEvaluation && <section className="panel evaluation-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">QUALIDADE DO MODELO</p><h2>Resultados das revisões humanas</h2><p className="muted">Compara as últimas sugestões com as decisões dos operadores.</p></div>
              <span className="subtle-pill">{reviewEvaluation.sample_count} casos avaliados</span>
            </div>
            {reviewEvaluation.sample_count === 0 ? <div className="empty-state"><ShieldCheck size={25} /><strong>Ainda não existem casos avaliáveis</strong><span>As métricas surgem depois de existirem deteções com fusão e decisão humana.</span></div> : <>
              <div className="evaluation-metrics">
                <div><span>Precisão nas propostas</span><strong>{reviewEvaluation.precision_when_sku_predicted == null ? "—" : `${(reviewEvaluation.precision_when_sku_predicted * 100).toFixed(1)}%`}</strong></div>
                <div><span>Cobertura SKU conhecido</span><strong>{reviewEvaluation.known_product_coverage == null ? "—" : `${(reviewEvaluation.known_product_coverage * 100).toFixed(1)}%`}</strong></div>
                <div><span>Falsos positivos rejeitados</span><strong>{reviewEvaluation.false_accepts_on_rejected_detections}</strong></div>
                <div><span>Abstenções corretas</span><strong>{reviewEvaluation.correct_abstentions}</strong></div>
              </div>
              <div className="evaluation-detail">
                <span>Acertos: <strong>{reviewEvaluation.correct_matches}</strong></span>
                <span>SKU incorretos: <strong>{reviewEvaluation.incorrect_known_matches}</strong></span>
                <span>SKU não identificados: <strong>{reviewEvaluation.missed_known_products}</strong></span>
                <span>Sem fusão: <strong>{reviewEvaluation.reviewed_detections_without_matching_fusion}</strong></span>
              </div>
            </>}
            <p className="evaluation-caveat">Amostra limitada às deteções revistas; não representa um teste independente nem uma estimativa estatística de precisão em produção.</p>
          </section>}
          <footer className="data-note"><ShieldCheck size={15} /> {summary.note} <span>·</span> {summary.role} {summary.store_id ? `· Loja #${summary.store_id}` : "· Visão global"}</footer>
        </>}
        {!summary && loading && <div className="loading-state"><RefreshCw className="spin" /> A carregar os indicadores…</div>}
      </main>
    </div>
  );
}

function Metric({ icon, label, value, tone, detail }: { icon: ReactNode; label: string; value: number; tone: string; detail: string }) {
  return <article className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><p>{label}</p><strong>{value.toLocaleString("pt-PT")}</strong><span>{detail}</span></article>;
}
function TaskRow({ task, canAssign, canProgress, onUpdate }: { task: Task; canAssign: boolean; canProgress: boolean; onUpdate: (task: Task, status: "ASSIGNED" | "IN_PROGRESS" | "COMPLETED", assignedUserId?: number) => void }) {
  const [assigneeId, setAssigneeId] = useState("");
  const next = task.status === "ASSIGNED" ? "IN_PROGRESS" : task.status === "IN_PROGRESS" ? "COMPLETED" : null;
  return <div className="task-row">
    <div className="task-symbol"><ArrowDownToLine size={18} /></div>
    <div className="task-info"><strong>Reposição · Prateleira #{task.shelf_id}</strong><span>Produto #{task.product_id} · {task.assigned_to || "Por atribuir"} · #{task.id}</span></div>
    <span className={`priority ${task.priority.toLowerCase()}`}>{task.priority}</span>
    <span className={`task-status ${task.status.toLowerCase()}`}>{task.status.replace("_", " ")}</span>
    {canAssign && task.status === "PENDING" && <div className="assign-control"><input aria-label={`ID do funcionário para a tarefa ${task.id}`} inputMode="numeric" placeholder="ID funcionário" value={assigneeId} onChange={e => setAssigneeId(e.target.value)} /><button className="row-action" disabled={!/^\d+$/.test(assigneeId) || Number(assigneeId) < 1} onClick={() => onUpdate(task, "ASSIGNED", Number(assigneeId))}>Atribuir</button></div>}
    {canProgress && next && <button className="row-action" onClick={() => onUpdate(task, next)}>{next === "IN_PROGRESS" ? "Iniciar" : "Concluir"} <ArrowUpRight size={14} /></button>}
  </div>;
}
function StatusBar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const percent = total ? Math.round(value / total * 100) : 0;
  return <div className="status-bar-row"><div><span>{label}</span><strong>{value}</strong></div><div className="bar-track"><div className={`bar-fill ${color}`} style={{ width: `${percent}%` }} /></div></div>;
}
