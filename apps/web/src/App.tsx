import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowUpRight, Boxes, CheckCircle2,
  CircleUserRound, Clock3, LogOut, PackageSearch, RefreshCw, ShieldCheck,
  Store, Truck, UserRound, Warehouse, Check, X, History, Image as ImageIcon,
} from "lucide-react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

type Role = "ADMIN" | "SUPERVISOR" | "EMPLOYEE";
type TaskStatus = "PENDING" | "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
type User = { id: number; email: string; full_name: string; role: Role; store_id: number | null; is_active: boolean };
type EmployeeRecord = { id: number; full_name: string; role: Role; store_id: number | null; is_active: boolean };
type StoreRecord = { id: number; code: string; name: string };
type ZoneRecord = { id: number; store_id: number; name: string };
type ShelfRecord = { id: number; zone_id: number; code: string; description: string | null };
type CaptureSession = { id: number; shelf_id: number; store_id: number; started_at: string };
type Task = {
  id: number; store_id: number; shelf_id: number; product_id: number;
  priority: "LOW" | "NORMAL" | "HIGH" | "URGENT"; status: TaskStatus;
  assigned_to: string | null; assigned_user_id: number | null;
  requested_quantity: number | null; actual_quantity?: number | null; exception_reason?: string | null; notes: string | null; created_at: string;
};
type TaskEvent = {
  id: number; task_id: number;
  event_type: "CREATED" | "APPROVED" | "STATUS_CHANGED" | "INVENTORY_RECONCILED";
  from_status: TaskStatus | null; to_status: TaskStatus | null;
  actor_user_id: number | null; actual_quantity: number | null;
  reason: string | null; created_at: string;
};
type InventoryMovement = {
  id: number; task_id: number; store_id: number; product_id: number;
  movement_type: "BACKROOM_TO_SHELF"; quantity: number;
  source_snapshot_id: number; result_snapshot_id: number;
  actor_user_id: number; reason: string; created_at: string;
};
type ShelfImage = { id: number; shelf_id: number; capture_session_id?: number | null; original_filename: string; mime_type: string; file_size_bytes: number; sha256: string; analysis_status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED"; analysis_error: string | null; analysis_started_at: string | null; analysis_completed_at: string | null; captured_at: string; created_at: string };
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
type ReplenishmentAssessment = {
  status: string; suggested_quantity: number | null;
  shelf_gap_quantity: number | null; remaining_gap_quantity: number | null;
  requires_human_review: boolean; explanation: string;
  observation_age_minutes?: number; inventory_freshness_required?: boolean;
};
type OperationalDecisionRow = {
  store_id: number; zone_name: string; shelf_id: number; shelf_code: string;
  product_id: number; product_sku: string; product_name: string;
  backroom_inventory?: { on_hand_quantity: number; reserved_quantity: number;
    available_quantity: number; source: string; captured_at: string;
    age_minutes: number; is_fresh: boolean } | null;
  replenishment_assessment?: ReplenishmentAssessment | null;
  evidence?: { observation_id: number; image_id: number; detection_id: number; review_id: number; sha256: string } | null;
  decision: OperationalDecision;
};
type OperationalZoneSummary = {
  store_id: number; zone_name: string; items_evaluated: number;
  action_recommended: number; high_priority: number;
  already_in_progress: number; insufficient_evidence: number; monitor: number;
  lowest_coverage_hours: number | null;
  urgent_items: { product_id: number; product_name: string; product_sku: string;
    shelf_id: number; shelf_code: string; priority: string; reason: string;
    inventory_coverage_hours: number | null }[];
};
type OperationalDecisionResponse = {
  generated_at: string; count: number; status_counts: Record<string, number>;
  priority_counts?: Record<string, number>;
  zone_summaries?: OperationalZoneSummary[];
  forecast_policy: string; decisions: OperationalDecisionRow[];
};
type Summary = {
  store_id: number | null; role: Role; active_tasks: number;
  shelves_requiring_attention: number;
  tasks: Record<string, number>; observations: Record<string, number>; note: string;
};

function formatDurationMinutes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const totalMinutes = Math.max(0, Math.floor(value));
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  return [days ? `${days} d` : "", hours ? `${hours} h` : "", minutes || (!days && !hours) ? `${minutes} min` : ""].filter(Boolean).join(" ");
}

function formatDateTime(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "Data indisponível";
  return new Intl.DateTimeFormat("pt-PT", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: "Europe/Lisbon", timeZoneName: "short",
  }).format(date);
}

function formatTime(value: Date): string {
  return new Intl.DateTimeFormat("pt-PT", {
    hour: "2-digit", minute: "2-digit", timeZone: "Europe/Lisbon", timeZoneName: "short",
  }).format(value);
}

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
  const [approvalLoadingKey, setApprovalLoadingKey] = useState<string | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskUpdatingId, setTaskUpdatingId] = useState<number | null>(null);
  const [taskEvents, setTaskEvents] = useState<Record<number, TaskEvent[]>>({});
  const [taskEventsLoading, setTaskEventsLoading] = useState<number | null>(null);
  const [taskReconcileLoading, setTaskReconcileLoading] = useState<number | null>(null);
  const [taskReconcileMessages, setTaskReconcileMessages] = useState<Record<number, string>>({});
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
  const [stores, setStores] = useState<StoreRecord[]>([]);
  const [zones, setZones] = useState<ZoneRecord[]>([]);
  const [shelves, setShelves] = useState<ShelfRecord[]>([]);
  const [employees, setEmployees] = useState<EmployeeRecord[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState("");
  const [selectedZoneId, setSelectedZoneId] = useState("");
  const [employeeSelection, setEmployeeSelection] = useState<Record<string, string>>({});
  const [observationByDetection, setObservationByDetection] = useState<Record<number, number>>({});
  const [observationLoading, setObservationLoading] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [replenishmentPlan, setReplenishmentPlan] = useState<ReplenishmentPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState("");
  const [taskFocusFilter, setTaskFocusFilter] = useState<"ALL" | "ACTIVE" | "PENDING" | "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "URGENT">("ALL");
  const navigateToSection = useCallback((sectionId: string) => {
    const target = document.getElementById(sectionId);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  }, []);


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
    if (!response.ok) {
      const detail = payload.detail;
      const message = typeof detail === "string"
        ? detail
        : detail && typeof detail === "object"
          ? (detail.message || detail.code || JSON.stringify(detail))
          : `Erro HTTP ${response.status}`;
      apiError(message);
    }
    return payload as T;
  }, [token]);

  const logout = useCallback(() => {
    sessionStorage.removeItem("smart-shelf-token");
    Object.values(imageUrls).forEach(url => URL.revokeObjectURL(url));
    setImageUrls({});
    setToken(""); setUser(null); setSummary(null); setOperationalDecisions(null); setTasks([]); setTaskEvents({}); setTaskReconcileMessages({}); setCaptures([]); setImageDetections({}); setDetectionReviews({}); setExpandedDetectionImage(null);
  }, [imageUrls]);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true); setError("");
    try {
      const me = await request<User>("/api/v1/auth/me");
      const query = storeFilter.trim() ? `?store_id=${encodeURIComponent(storeFilter.trim())}` : "";
      const [kpis, taskList, captureList] = await Promise.all([
        request<Summary>(`/api/v1/dashboard/summary${query}`),
        request<Task[]>("/api/v1/tasks?limit=100"),
        request<ShelfImage[]>("/api/v1/shelf-images?limit=30"),
      ]);
      let storeList: StoreRecord[] = [];
      let zoneList: ZoneRecord[] = [];
      let shelfList: ShelfRecord[] = [];
      let employeeList: EmployeeRecord[] = [];
      if (me.role === "ADMIN" || me.role === "SUPERVISOR") {
        [storeList, zoneList, shelfList, employeeList] = await Promise.all([
          request<StoreRecord[]>("/api/v1/stores"),
          request<ZoneRecord[]>("/api/v1/zones"),
          request<ShelfRecord[]>("/api/v1/shelves"),
          request<EmployeeRecord[]>("/api/v1/store-employees?limit=500"),
        ]);
      }
      setUser(me); setSummary(kpis); setTasks(taskList); setCaptures(captureList); setLastUpdated(new Date());
      setStores(storeList); setZones(zoneList); setShelves(shelfList);
      setEmployees(employeeList.filter(person => person.role === "EMPLOYEE" && person.is_active));
      setSelectedStoreId(current => current || String(me.store_id ?? storeList[0]?.id ?? ""));
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
  const demoZones = useMemo(() => zones.filter(zone => String(zone.store_id) === selectedStoreId), [zones, selectedStoreId]);
  const demoShelves = useMemo(() => shelves.filter(shelf => String(shelf.zone_id) === selectedZoneId), [shelves, selectedZoneId]);
  useEffect(() => {
    if (!demoZones.some(zone => String(zone.id) === selectedZoneId)) setSelectedZoneId(String(demoZones[0]?.id ?? ""));
  }, [demoZones, selectedZoneId]);
  useEffect(() => {
    if (!demoShelves.some(shelf => String(shelf.id) === captureShelfId)) setCaptureShelfId(String(demoShelves[0]?.id ?? ""));
  }, [demoShelves, captureShelfId]);

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

  async function updateTask(
    task: Task,
    status: "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED",
    assignedUserId?: number,
    completion?: { actual_quantity: number; exception_reason?: string },
    cancellationReason?: string,
  ) {
    setTaskUpdatingId(task.id);
    setError("");
    try {
      await request<Task>(`/api/v1/tasks/${task.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({
          status,
          ...(assignedUserId !== undefined ? { assigned_user_id: assignedUserId } : {}),
          ...(completion || {}),
          ...(status === "CANCELLED" && cancellationReason
            ? { exception_reason: cancellationReason.trim() }
            : {}),
        }),
      });
      await refresh();
      if (taskEvents[task.id] !== undefined) await loadTaskEvents(task.id);
    } catch (err) { setError(err instanceof Error ? err.message : "Não foi possível atualizar a tarefa."); }
    finally { setTaskUpdatingId(current => current === task.id ? null : current); }
  }

  async function loadTaskEvents(taskId: number) {
    setTaskEventsLoading(taskId);
    setError("");
    try {
      const events = await request<TaskEvent[]>(`/api/v1/tasks/${taskId}/events`);
      setTaskEvents(current => ({ ...current, [taskId]: events }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível consultar a cronologia da tarefa.");
    } finally {
      setTaskEventsLoading(current => current === taskId ? null : current);
    }
  }

  async function reconcileTask(task: Task, reason: string) {
    setTaskReconcileLoading(task.id);
    setTaskReconcileMessages(current => ({ ...current, [task.id]: "" }));
    setError("");
    try {
      const movement = await request<InventoryMovement>(`/api/v1/tasks/${task.id}/reconcile-inventory`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      setTaskReconcileMessages(current => ({
        ...current,
        [task.id]: `Reconciliação #${movement.id} registada: ${movement.quantity} unidades. Snapshot resultante #${movement.result_snapshot_id}.`,
      }));
      await loadTaskEvents(task.id);
      await refresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível reconciliar o inventário.";
      setTaskReconcileMessages(current => ({ ...current, [task.id]: message }));
      if (message.includes("INVENTORY_ALREADY_RECONCILED")) await loadTaskEvents(task.id);
    } finally {
      setTaskReconcileLoading(current => current === task.id ? null : current);
    }
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
    if (!captureShelfId.trim() || !captureFile || !user || !["ADMIN", "SUPERVISOR"].includes(user.role)) {
      setCaptureMessage("Seleciona uma prateleira, uma fotografia e confirma que tens perfil SUPERVISOR/ADMIN.");
      return;
    }
    setCaptureLoading(true); setCaptureMessage("");
    let sessionId: number | null = null;
    try {
      const captureSession = await request<CaptureSession>("/api/v1/capture-sessions", {
        method: "POST",
        body: JSON.stringify({ shelf_id: Number(captureShelfId), source_type: "mobile", capture_mode: "single" }),
      });
      sessionId = captureSession.id;
      const form = new FormData();
      form.append("shelf_id", captureShelfId.trim());
      form.append("capture_session_id", String(captureSession.id));
      form.append("image", captureFile);
      const response = await fetch(`${API_BASE}/api/v1/shelf-images`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
      let sessionCloseWarning = "";
      try {
        await request<CaptureSession>(`/api/v1/capture-sessions/${captureSession.id}/close`, { method: "POST" });
      } catch {
        sessionCloseWarning = " A imagem foi guardada, mas a sessão não ficou encerrada; consulta a auditoria.";
      }
      setCaptureMessage(`Sessão #${sessionId} · fotografia #${payload.id} · SHA-256 ${String(payload.sha256).slice(0, 12)}… · ${payload.analysis_status}.${sessionCloseWarning}`);
      setCaptureFile(null); setCaptureReset(value => value + 1);
      await refresh();
    } catch (err) {
      if (sessionId !== null) {
        try { await request<CaptureSession>(`/api/v1/capture-sessions/${sessionId}/close`, { method: "POST" }); } catch { /* Preserve the original upload error. */ }
      }
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
    if (imageDetections[item.id]?.length) return;
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


  async function createObservationFromDetection(image: ShelfImage, detection: ShelfImageDetection) {
    const history = detectionReviews[detection.id] || [];
    const latest = history[history.length - 1];
    const productId = latest?.selected_product_id;
    if (!latest || latest.decision === "REJECTED" || !productId) {
      setError("É necessária uma revisão humana válida do SKU antes de criar a observação.");
      return;
    }
    if (!window.confirm(`Registar observação ${detection.label} para o SKU selecionado? A evidência ficará ligada à imagem #${image.id}.`)) return;
    setObservationLoading(detection.id);
    setError("");
    try {
      const observation = await request<{ id: number }>(`/api/v1/shelf-image-detections/${detection.id}/observation`, {
        method: "POST",
        body: JSON.stringify({ product_id: productId }),
      });
      setObservationByDetection(current => ({ ...current, [detection.id]: observation.id }));
      setCaptureMessage(`Observação #${observation.id} registada a partir da deteção #${detection.id}.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível criar a observação.");
    } finally {
      setObservationLoading(null);
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

  async function approveOperationalRefill(item: OperationalDecisionRow) {
    const assessment = item.replenishment_assessment;
    if (!assessment || assessment.status !== "NEEDS_REPLENISHMENT" || assessment.suggested_quantity == null) return;
    if (!item.evidence) {
      setError("A aprovação do demo exige evidência visual ativa, deteção e revisão humana ligadas à observação.");
      return;
    }
    const quantity = assessment.suggested_quantity;
    const available = item.backroom_inventory?.available_quantity;
    const key = `${item.store_id}:${item.shelf_id}:${item.product_id}`;
    const assignedUserId = Number(employeeSelection[key]);
    if (!Number.isInteger(assignedUserId) || !employees.some(employee => employee.id === assignedUserId && employee.store_id === item.store_id)) {
      setError("Seleciona um EMPLOYEE ativo da mesma loja antes de aprovar.");
      return;
    }
    if (!item.backroom_inventory?.is_fresh || available == null || quantity > available) {
      setError("A proposta deixou de ter stock de retaguarda atualizado e suficiente. Atualiza as decisões antes de aprovar.");
      return;
    }
    const accepted = window.confirm(
      `Aprovar tarefa de reposição?\\n\\n${item.product_name} (${item.product_sku})\\nPrateleira: ${item.shelf_code}\\nQuantidade: ${quantity}\\nStock disponível na retaguarda: ${available}\\n\\nA tarefa será criada, sem movimentar stock automaticamente.`
    );
    if (!accepted) return;
    setApprovalLoadingKey(key);
    setError("");
    try {
      await request<Task>("/api/v1/tasks/from-operational-decision?approved=true&demo_evidence_required=true", {
        method: "POST",
        body: JSON.stringify({
          store_id: item.store_id,
          shelf_id: item.shelf_id,
          product_id: item.product_id,
          priority: item.decision.priority === "HIGH" ? "HIGH" : "NORMAL",
          requested_quantity: quantity,
          assigned_user_id: assignedUserId,
          notes: [
            "Aprovado pelo responsável no dashboard de decisões operacionais.",
            item.evidence
              ? `evidence_image_id=${item.evidence.image_id}; evidence_detection_id=${item.evidence.detection_id}; evidence_observation_id=${item.evidence.observation_id}; evidence_review_id=${item.evidence.review_id}; evidence_sha256=${item.evidence.sha256}`
              : "",
          ].filter(Boolean).join("\\n"),
        }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível criar a tarefa aprovada.");
      await refresh();
    } finally {
      setApprovalLoadingKey(null);
    }
  }

  const taskRows = useMemo(() => tasks.filter(task => {
    if (taskFocusFilter === "ACTIVE") return ["PENDING", "ASSIGNED", "IN_PROGRESS"].includes(task.status);
    if (taskFocusFilter === "PENDING" || taskFocusFilter === "ASSIGNED" || taskFocusFilter === "IN_PROGRESS" || taskFocusFilter === "COMPLETED") return task.status === taskFocusFilter;
    if (taskFocusFilter === "URGENT") return task.priority === "URGENT" && !["COMPLETED", "CANCELLED"].includes(task.status);
    return true;
  }), [tasks, taskFocusFilter]);
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
        <button type="button" className="nav-item active" onClick={() => navigateToSection("dashboard-top")}><Activity size={18} /> Visão geral</button>
        <button type="button" className="nav-item" onClick={() => { setTaskFocusFilter("ALL"); navigateToSection("replenishment-tasks"); }}><PackageSearch size={18} /> Tarefas de reposição <span className="nav-count">{summary?.active_tasks ?? "—"}</span></button>
        <button type="button" className="nav-item" onClick={() => navigateToSection("operational-decisions")}><Store size={18} /> Operação da loja</button>
        <div className="sidebar-bottom"><div className="status-dot" /> API ligada por sessão</div>
      </aside>
      <main className="main-area">
        <header id="dashboard-top" className="topbar">
          <div><p className="eyebrow">OPERAÇÕES / DASHBOARD</p><h1>Visão geral</h1></div>
          <div className="top-actions">
            <button className="icon-button" onClick={() => void refresh()} title="Atualizar dados" disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} /></button>
            <div className="user-chip"><div className="avatar"><UserRound size={17} /></div><div><strong>{user?.full_name || "A carregar…"}</strong><span>{user?.role || "Sessão"}</span></div></div>
            <button className="icon-button" onClick={logout} title="Terminar sessão"><LogOut size={17} /></button>
          </div>
        </header>
        <section className="toolbar">
          <div><span className="live-dot" /> <strong>Dados operacionais</strong> <span className="subtle-pill">Demo mode · provider mock quando configurado</span><span className="muted"> · {lastUpdated ? `Atualizado às ${formatTime(lastUpdated)}` : "A sincronizar"}</span></div>
          {user?.role === "ADMIN" && <label className="store-filter"><Store size={15} /><input aria-label="Filtrar por ID da loja" placeholder="Todas as lojas · ID opcional" value={storeFilter} onChange={e => setStoreFilter(e.target.value)} onKeyDown={e => { if (e.key === "Enter") void refresh(); }} /><button onClick={() => void refresh()}>Aplicar</button></label>}
        </section>
        {error && <div className="error-banner page-error" role="alert"><AlertTriangle size={17} /> {error}</div>}
        {summary && <>
          <section id="dashboard-metrics" className="metric-grid">
            <Metric icon={<AlertTriangle />} label="Prateleiras a necessitar de atenção" value={summary.shelves_requiring_attention} tone="orange" detail="Rutura ou stock baixo" onClick={() => navigateToSection("operational-decisions")} />
            <Metric icon={<Clock3 />} label="Tarefas ativas" value={summary.active_tasks} tone="blue" detail="Pendentes, atribuídas ou em curso" onClick={() => { setTaskFocusFilter("ACTIVE"); navigateToSection("replenishment-tasks"); }} />
            <Metric icon={<CheckCircle2 />} label="Tarefas concluídas" value={summary.tasks.completed || 0} tone="green" detail="No conjunto de registos consultado" onClick={() => { setTaskFocusFilter("COMPLETED"); navigateToSection("replenishment-tasks"); }} />
            <Metric icon={<Truck />} label="Tarefas urgentes" value={tasks.filter(t => t.priority === "URGENT" && !["COMPLETED", "CANCELLED"].includes(t.status)).length} tone="purple" detail="A aguardar intervenção" onClick={() => { setTaskFocusFilter("URGENT"); navigateToSection("replenishment-tasks"); }} />
          </section>
          <section className="content-grid">
            <article id="replenishment-tasks" className="panel task-panel">
              <div className="panel-heading"><div><p className="eyebrow">EXECUÇÃO</p><h2>Tarefas de reposição</h2><p className="muted">Acompanhamento das intervenções registadas na API.</p></div><div className="task-panel-actions"><span className="subtle-pill">{taskFocusFilter === "ALL" ? `${taskRows.length} de ${tasks.length} registos` : `${taskRows.length} tarefas · ${taskFocusFilter === "ACTIVE" ? "Ativas" : taskFocusFilter === "URGENT" ? "Urgentes" : taskFocusFilter === "PENDING" ? "Pendentes" : taskFocusFilter === "ASSIGNED" ? "Atribuídas" : taskFocusFilter === "IN_PROGRESS" ? "Em execução" : "Concluídas"}`}</span>{taskFocusFilter !== "ALL" && <button type="button" className="filter-reset" onClick={() => setTaskFocusFilter("ALL")}>Limpar filtro ×</button>}</div></div>
              <div className="task-list">
                {taskRows.length === 0 && <div className="empty-state"><PackageSearch size={28} /><strong>{tasks.length ? "Sem tarefas neste filtro" : "Sem tarefas registadas"}</strong><span>{tasks.length ? "Altera o filtro para consultar outras tarefas." : "Quando forem criadas tarefas, aparecerão aqui."}</span>{tasks.length > 0 && <button type="button" className="row-action" onClick={() => setTaskFocusFilter("ALL")}>Mostrar todas as tarefas</button>}</div>}
                {taskRows.map(task => <TaskRow
                  key={task.id}
                  task={task}
                  token={token}
                  evidenceImageId={Number(task.notes?.match(/evidence_image_id=(\d+)/)?.[1] || 0) || null}
                  updating={taskUpdatingId === task.id}
                  canAssign={user?.role === "ADMIN" || user?.role === "SUPERVISOR"}
                  canProgress={user?.role === "EMPLOYEE" ? task.assigned_user_id === user.id : user?.role === "ADMIN" || user?.role === "SUPERVISOR"}
                  canCancel={user?.role === "ADMIN" || user?.role === "SUPERVISOR"}
                  canAudit={user?.role === "ADMIN" || user?.role === "SUPERVISOR"}
                  canReconcile={user?.role === "ADMIN" || user?.role === "SUPERVISOR"}
                  events={taskEvents[task.id] || null}
                  eventsLoading={taskEventsLoading === task.id}
                  reconcileLoading={taskReconcileLoading === task.id}
                  reconcileMessage={taskReconcileMessages[task.id] || ""}
                  onLoadEvents={loadTaskEvents}
                  onReconcile={reconcileTask}
                  onUpdate={updateTask}
                />)}
              </div>
            </article>
            <article id="task-status-summary" className="panel status-panel">
              <div className="panel-heading"><div><p className="eyebrow">RESUMO</p><h2>Estado das tarefas</h2><p className="muted">Distribuição por estado.</p></div></div>
              <div className="status-total"><strong>{taskTotal}</strong><span>tarefas no total</span></div>
              <StatusBar label="Pendentes" value={summary.tasks.pending || 0} total={taskTotal} color="amber" onClick={() => { setTaskFocusFilter("PENDING"); navigateToSection("replenishment-tasks"); }} />
              <StatusBar label="Atribuídas" value={summary.tasks.assigned || 0} total={taskTotal} color="violet" onClick={() => { setTaskFocusFilter("ASSIGNED"); navigateToSection("replenishment-tasks"); }} />
              <StatusBar label="Em execução" value={summary.tasks.in_progress || 0} total={taskTotal} color="blue" onClick={() => { setTaskFocusFilter("IN_PROGRESS"); navigateToSection("replenishment-tasks"); }} />
              <StatusBar label="Concluídas" value={summary.tasks.completed || 0} total={taskTotal} color="green" onClick={() => { setTaskFocusFilter("COMPLETED"); navigateToSection("replenishment-tasks"); }} />
              <div className="panel-note"><AlertTriangle size={16} /><span>{summary.observations.empty || 0} prateleiras sem stock e {summary.observations.low_stock || 0} com stock baixo, segundo as observações registadas.</span></div>
            </article>
          </section>
          {(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && <section id="operational-decisions" className="panel decision-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">INTELIGÊNCIA OPERACIONAL</p><h2>Decisões e alertas por prateleira</h2><p className="muted">Cruza observações, inventário, vendas recentes e tarefas ativas. Apenas recomenda; não cria tarefas nem altera stock.</p></div>
              <button className="row-action" onClick={() => void refresh()} disabled={loading || decisionLoading}>{decisionLoading ? "A atualizar…" : "Atualizar decisões"} <RefreshCw size={14} /></button>
            </div>
            {decisionLoading && !operationalDecisions && <div className="loading-state">A avaliar evidência operacional…</div>}
            {operationalDecisions && <>
              <div className="decision-counts">
                <div><span>Itens avaliados</span><strong>{operationalDecisions.count}</strong></div>
                <div><span>Ação recomendada</span><strong>{operationalDecisions.status_counts.ACTION_RECOMMENDED || 0}</strong></div>
                <div><span>Prioridade alta</span><strong>{operationalDecisions.priority_counts?.HIGH || 0}</strong></div>
                <div><span>Em acompanhamento</span><strong>{operationalDecisions.status_counts.MONITOR || 0}</strong></div>
                <div><span>Já em execução</span><strong>{operationalDecisions.status_counts.ALREADY_IN_PROGRESS || 0}</strong></div>
                <div><span>Observação expirada</span><strong>{operationalDecisions.decisions.filter(item => item.replenishment_assessment?.status === "STALE_OBSERVATION").length}</strong></div>
                <div><span>Retaguarda desatualizada</span><strong>{operationalDecisions.decisions.filter(item => item.backroom_inventory && !item.backroom_inventory.is_fresh).length}</strong></div>
              </div>
              <p className="decision-method">{operationalDecisions.forecast_policy}</p>
              {(operationalDecisions.decisions.some(item => item.replenishment_assessment?.status === "STALE_OBSERVATION") || operationalDecisions.decisions.some(item => item.backroom_inventory && !item.backroom_inventory.is_fresh)) && <p className="decision-freshness-notice" role="status">Existem dados operacionais desatualizados. As observações expiradas não sustentam uma nova recomendação de reposição e o inventário de retaguarda desatualizado não deve ser usado para aprovar movimentos.</p>}
              {(operationalDecisions.zone_summaries ?? []).length > 0 && <div className="decision-zone-grid">
                {(operationalDecisions.zone_summaries ?? []).map(zone => <article role="button" tabIndex={0} className="decision-zone-card" key={`${zone.store_id}-${zone.zone_name}`} aria-label={`Consultar decisões da zona ${zone.zone_name}`} onClick={() => navigateToSection("decision-list")} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); navigateToSection("decision-list"); } }}>
                  <div className="decision-zone-heading"><strong>{zone.zone_name}</strong><span>{zone.items_evaluated} referências</span></div>
                  <div className="decision-zone-metrics">
                    <span><strong>{zone.high_priority}</strong> prioridade alta</span>
                    <span><strong>{zone.action_recommended}</strong> ações</span>
                    <span><strong>{zone.already_in_progress}</strong> em execução</span>
                    <span><strong>{zone.insufficient_evidence}</strong> sem evidência</span>
                  </div>
                  {zone.lowest_coverage_hours != null && <p className="decision-method">Menor cobertura estimada: <strong>{zone.lowest_coverage_hours.toFixed(1)} h</strong></p>}
                  {zone.urgent_items.map(item => <div className="decision-zone-item" key={`${item.shelf_id}-${item.product_id}`}>
                    <span><strong>{item.product_name}</strong><small>{item.product_sku} · {item.shelf_code}</small></span>
                    <b>{item.priority === "HIGH" ? "ALTA" : "NORMAL"}</b>
                  </div>)}
                </article>)}
              </div>}
              <div id="decision-list" className="decision-list">
                {operationalDecisions.decisions.length === 0 && <div className="empty-state"><ShieldCheck size={24} /><strong>Sem produtos associados a prateleiras</strong><span>Quando existirem associações e evidência registada, o motor apresentará as decisões aqui.</span></div>}
                {operationalDecisions.decisions.map(item => <article className="decision-row" key={`${item.shelf_id}-${item.product_id}`}>
                  <div className="decision-product"><strong>{item.product_name}</strong><span>{item.product_sku} · {item.zone_name} · Prateleira {item.shelf_code}</span></div>
                  <span className={`decision-status ${item.decision.status.toLowerCase()}`}>{item.decision.status === "ACTION_RECOMMENDED" ? "Requer avaliação" : item.decision.status === "ALREADY_IN_PROGRESS" ? "Tarefa ativa" : item.decision.status === "INSUFFICIENT_EVIDENCE" ? "Dados insuficientes" : "Monitorizar"}</span>
                  <p>{item.decision.reason}</p>
                  <div className="decision-meta">
                    <span>Prioridade: <strong>{item.decision.priority}</strong></span>
                    <span>Quantidade sugerida: <strong>{item.decision.suggested_replenishment_quantity == null ? "Não calculada" : item.decision.suggested_replenishment_quantity}</strong></span>
                    <span>Cobertura estimada: <strong>{item.decision.inventory_coverage_hours == null ? "—" : `${item.decision.inventory_coverage_hours.toFixed(1)} h`}</strong></span><span>Fontes: <strong>{item.decision.evidence.length}</strong></span>
                    {item.backroom_inventory && <span>Retaguarda disponível: <strong>{item.backroom_inventory.available_quantity}</strong></span>}
                  </div>
                  {item.backroom_inventory && <p className="decision-method">Stock de retaguarda: {item.backroom_inventory.on_hand_quantity} em mão · {item.backroom_inventory.reserved_quantity} reservado · {item.backroom_inventory.available_quantity} disponível · {item.backroom_inventory.is_fresh ? "atualizado" : "desatualizado"} ({formatDurationMinutes(item.backroom_inventory.age_minutes)}). Não representa a quantidade física na prateleira.</p>}
                  {item.replenishment_assessment && <div className="decision-assessment">
                    <strong>Proposta de reposição: {item.replenishment_assessment.status}</strong>
                    <p>{item.replenishment_assessment.explanation}</p>
                    <div className="decision-meta">
                      <span>Quantidade sugerida: <strong>{item.replenishment_assessment.suggested_quantity == null ? "Não calculada" : item.replenishment_assessment.suggested_quantity}</strong></span>
                      <span>Diferença até ao alvo: <strong>{item.replenishment_assessment.shelf_gap_quantity == null ? "—" : item.replenishment_assessment.shelf_gap_quantity}</strong></span>
                      <span>Por cobrir: <strong>{item.replenishment_assessment.remaining_gap_quantity == null ? "—" : item.replenishment_assessment.remaining_gap_quantity}</strong></span>
                      {item.replenishment_assessment.observation_age_minutes != null && <span>Idade da observação: <strong>{formatDurationMinutes(item.replenishment_assessment.observation_age_minutes)}</strong></span>}
                    </div>
                    {item.replenishment_assessment.requires_human_review && <p className="decision-method">Requer validação humana antes de criar uma tarefa ou movimentar stock.</p>}
                    {item.replenishment_assessment.status === "NEEDS_REPLENISHMENT" && item.replenishment_assessment.suggested_quantity != null && <><label className="demo-assignee">Atribuir ao funcionário
                         <select value={employeeSelection[`${item.store_id}:${item.shelf_id}:${item.product_id}`] || ""} onChange={event => setEmployeeSelection(current => ({ ...current, [`${item.store_id}:${item.shelf_id}:${item.product_id}`]: event.target.value }))}>
                           <option value="">Selecionar EMPLOYEE…</option>
                           {employees.filter(employee => employee.store_id === item.store_id).map(employee => <option key={employee.id} value={employee.id}>{employee.full_name} · #{employee.id}</option>)}
                         </select>
                       </label>
                       <button className="row-action decision-approve" onClick={() => void approveOperationalRefill(item)} disabled={approvalLoadingKey === `${item.store_id}:${item.shelf_id}:${item.product_id}` || !item.backroom_inventory?.is_fresh || item.replenishment_assessment.suggested_quantity > (item.backroom_inventory?.available_quantity ?? 0)}>
                      {approvalLoadingKey === `${item.store_id}:${item.shelf_id}:${item.product_id}` ? "A criar tarefa…" : "Aprovar e criar tarefa"}
                    </button></>}
                  </div>}
                  {item.decision.warnings.length > 0 && <ul className="decision-warnings">{item.decision.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
                </article>)}
              </div>
              <p className="decision-method">Gerado em {formatDateTime(operationalDecisions.generated_at)}. Todas as recomendações requerem validação humana.</p>
            </>}
          </section>}
          {(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && <section id="replenishment-plan" className="panel replenishment-plan-panel">
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
                <div><span>Tempo estimado total</span><strong>{replenishmentPlan.effort_estimation.estimated_total_elapsed_minutes == null ? "—" : formatDurationMinutes(replenishmentPlan.effort_estimation.estimated_total_elapsed_minutes)}</strong></div>
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
                    <span className="plan-duration">{item.estimated_elapsed_minutes == null ? "Tempo —" : formatDurationMinutes(item.estimated_elapsed_minutes)}</span>
                    {!item.task_creation_allowed && <span className="plan-review">Requer validação</span>}
                  </div>)}
                </div>)}
              </div>
            </>}
          </section>}
          <section id="capture-workspace" className="capture-grid">
            <article className="panel capture-panel">
              <div className="panel-heading"><div><p className="eyebrow">VISÃO COMPUTACIONAL</p><h2>Nova captura de prateleira</h2><p className="muted">Envia uma fotografia para registo e futura análise automática.</p></div><div className="capture-icon"><PackageSearch size={20} /></div></div>
              <form className="capture-form" onSubmit={uploadCapture}>
                <label>Loja
                  <select value={selectedStoreId} onChange={event => setSelectedStoreId(event.target.value)} required>
                    <option value="">Selecionar loja…</option>
                    {stores.map(store => <option key={store.id} value={store.id}>{store.name} · {store.code}</option>)}
                  </select>
                </label>
                <label>Zona
                  <select value={selectedZoneId} onChange={event => setSelectedZoneId(event.target.value)} required>
                    <option value="">Selecionar zona…</option>
                    {demoZones.map(zone => <option key={zone.id} value={zone.id}>{zone.name}</option>)}
                  </select>
                </label>
                <label>Prateleira
                  <select value={captureShelfId} onChange={event => setCaptureShelfId(event.target.value)} required>
                    <option value="">Selecionar prateleira…</option>
                    {demoShelves.map(shelf => <option key={shelf.id} value={shelf.id}>{shelf.code} · {shelf.description || `Prateleira #${shelf.id}`}</option>)}
                  </select>
                </label>
                
                <label>Fotografia (JPEG, PNG ou WebP)<input key={captureReset} type="file" accept="image/jpeg,image/png,image/webp" onChange={e => setCaptureFile(e.target.files?.[0] || null)} required /></label>
                <div className="capture-submit"><span>{captureFile ? captureFile.name : "Nenhum ficheiro selecionado"}</span><button className="row-action" disabled={captureLoading || !captureFile}>{captureLoading ? "A enviar…" : "Enviar fotografia"} <ArrowUpRight size={14} /></button></div>
                {captureMessage && <p className="capture-feedback" role="status">{captureMessage}</p>}
              </form>
            </article>
            <article id="capture-history" className="panel capture-history">
              <div className="panel-heading"><div><p className="eyebrow">REGISTO DE CAPTURAS</p><h2>Fotografias recentes</h2><p className="muted">O estado indica o processamento pelo provider configurado. No demo é usado um provider mock determinístico, não um modelo de visão treinado.</p></div><span className="subtle-pill">{captures.length} capturas</span></div>
              <div className="capture-list">
                {captures.length === 0 && <div className="empty-state"><PackageSearch size={25} /><strong>Sem fotografias registadas</strong><span>As próximas capturas serão apresentadas aqui.</span></div>}
                {captures.map(item => <div className="capture-item" key={item.id}>
                  <div className="capture-row"><div className="capture-thumb"><Boxes size={17} /></div><div className="capture-meta"><strong>Prateleira #{item.shelf_id} · {item.original_filename}</strong><span>{(item.file_size_bytes / 1024).toFixed(0)} KB · SHA-256 {item.sha256.slice(0, 12)}… · Sessão #{item.capture_session_id ?? "—"} · {formatDateTime(item.created_at)}</span></div><span className={`task-status ${item.analysis_status.toLowerCase()}`}>{item.analysis_status}</span>{(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && item.analysis_status === "FAILED" && <button className="row-action detection-toggle" disabled={retryLoading === item.id} onClick={() => void retryImageAnalysis(item)}>{retryLoading === item.id ? "A repetir…" : "Repetir análise"}</button>}<button className="row-action detection-toggle" onClick={() => void toggleImageDetections(item)}>{detectionLoading === item.id ? "A consultar…" : expandedDetectionImage === item.id ? "Fechar" : "Deteções"}</button></div>
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
                        {canReview && history.length > 0 && history[history.length - 1].decision !== "REJECTED" && <div className="review-actions">
                          <button className="review-button confirm" disabled={observationLoading === detection.id} onClick={() => void createObservationFromDetection(item, detection)}>
                            {observationLoading === detection.id ? "A registar…" : observationByDetection[detection.id] ? `Observação #${observationByDetection[detection.id]} registada` : "Criar observação operacional"}
                          </button>
                        </div>}
                        <div className="review-history">
                          <strong><History size={14} /> Histórico ({history.length})</strong>
                          {history.length === 0 && <span>Sem decisões humanas registadas.</span>}
                          {history.map(review => <div className="review-history-row" key={review.id}><span>{review.decision === "CONFIRMED" ? "Confirmado" : review.decision === "CORRECTED" ? "Corrigido" : "Rejeitado"}</span><span>{review.selected_product_id ? `Produto #${review.selected_product_id}` : "Sem SKU"}</span><time>{formatDateTime(review.created_at)}</time>{review.notes && <small>{review.notes}</small>}</div>)}
                        </div>
                      </article>;
                    })}
                  </div>}
                </div>)}
              </div>
            </article>
          </section>
          {(user?.role === "ADMIN" || user?.role === "SUPERVISOR") && <section id="review-queue" className="panel review-queue-panel">
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
                  <div><strong>Prateleira {item.shelf_code} · Deteção #{item.detection_id}</strong><span>{item.image_filename} · {formatDateTime(item.created_at)}</span></div>
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

function Metric({ icon, label, value, tone, detail, onClick }: { icon: ReactNode; label: string; value: number; tone: string; detail: string; onClick: () => void }) {
  return <button type="button" className="metric-card metric-card-action" onClick={onClick} aria-label={`${label}: ${value}. Abrir informação relacionada.`}>
    <span className={`metric-icon ${tone}`}>{icon}</span><span className="metric-label">{label}</span><strong>{value.toLocaleString("pt-PT")}</strong><span className="metric-detail">{detail}</span><span className="metric-open-hint">Consultar detalhes <ArrowUpRight size={13} /></span>
  </button>;
}
function TaskRow({
  task, token, evidenceImageId, updating, canAssign, canProgress, canCancel, canAudit, canReconcile,
  events, eventsLoading, reconcileLoading, reconcileMessage,
  onLoadEvents, onReconcile, onUpdate,
}: {
  task: Task; token: string; evidenceImageId: number | null; updating: boolean;
  canAssign: boolean; canProgress: boolean; canCancel: boolean;
  canAudit: boolean; canReconcile: boolean; events: TaskEvent[] | null;
  eventsLoading: boolean; reconcileLoading: boolean; reconcileMessage: string;
  onLoadEvents: (taskId: number) => void;
  onReconcile: (task: Task, reason: string) => void;
  onUpdate: (task: Task, status: "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED", assignedUserId?: number, completion?: { actual_quantity: number; exception_reason?: string }, cancellationReason?: string) => void;
}) {
  const [assigneeId, setAssigneeId] = useState("");
  const [actualQuantity, setActualQuantity] = useState(task.requested_quantity?.toString() || "");
  const [exceptionReason, setExceptionReason] = useState("");
  const [cancellationReason, setCancellationReason] = useState("");
  const [reconciliationReason, setReconciliationReason] = useState("");
  const [showEvents, setShowEvents] = useState(false);
  const [evidenceImageUrl, setEvidenceImageUrl] = useState<string | null>(null);
  const next = task.status === "ASSIGNED" ? "IN_PROGRESS" : task.status === "IN_PROGRESS" ? "COMPLETED" : null;
  useEffect(() => {
    setEvidenceImageUrl(null);
    if (!evidenceImageId || !token) return;
    let active = true;
    let objectUrl: string | null = null;
    fetch(`${API_BASE}/api/v1/shelf-images/${evidenceImageId}/content`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(async response => {
      if (!response.ok) throw new Error("Evidência indisponível");
      const blob = await response.blob();
      if (active) {
        objectUrl = URL.createObjectURL(blob);
        setEvidenceImageUrl(objectUrl);
      }
    }).catch(() => {
      if (active) setEvidenceImageUrl(null);
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [evidenceImageId, token]);
  const actual = Number(actualQuantity);
  const isValidCompletion = Number.isFinite(actual) && actual > 0
    && (task.requested_quantity == null || actual <= task.requested_quantity)
    && (task.requested_quantity == null || actual >= task.requested_quantity || exceptionReason.trim().length >= 3);
  const canCancelTask = canCancel && ["PENDING", "ASSIGNED", "IN_PROGRESS"].includes(task.status);
  const alreadyReconciled = events?.some(event => event.event_type === "INVENTORY_RECONCILED") ?? false;
  const canReconcileTask = canReconcile && task.status === "COMPLETED"
    && task.actual_quantity != null && task.actual_quantity > 0 && !alreadyReconciled;
  return <div className="task-row task-row-expanded">
    <div className="task-symbol"><ArrowDownToLine size={18} /></div>
    <div className="task-info">
      <strong>Reposição · Prateleira #{task.shelf_id}</strong>
      <span>Produto #{task.product_id} · {task.assigned_to || "Por atribuir"} · #{task.id}</span>
      {task.status === "COMPLETED" && task.actual_quantity != null && <small className="task-outcome">Quantidade reposta: {task.actual_quantity}{task.exception_reason ? ` · ${task.exception_reason}` : ""}</small>}
      {task.status === "CANCELLED" && task.exception_reason && <small className="task-outcome">Cancelada: {task.exception_reason}</small>}
      {evidenceImageId && <div className="task-evidence">
        <strong>Evidência visual · imagem #{evidenceImageId}</strong>
        {evidenceImageUrl ? <img src={evidenceImageUrl} alt={`Evidência visual da reposição na prateleira #${task.shelf_id}`} /> : <span>A carregar evidência ou imagem indisponível pela política de retenção.</span>}
        {task.notes?.match(/evidence_sha256=([a-f0-9]{64})/)?.[1] && <small>SHA-256 {task.notes.match(/evidence_sha256=([a-f0-9]{64})/)?.[1]}</small>}
      </div>}
    </div>
    <span className={"priority " + task.priority.toLowerCase()}>{task.priority}</span>
    <span className={"task-status " + task.status.toLowerCase()}>{task.status.replace("_", " ")}</span>
    {canAssign && task.status === "PENDING" && <div className="assign-control"><input aria-label={"ID do funcionário para a tarefa " + task.id} inputMode="numeric" placeholder="ID funcionário" value={assigneeId} onChange={e => setAssigneeId(e.target.value)} /><button className="row-action" disabled={updating || !/^\d+$/.test(assigneeId) || Number(assigneeId) < 1} onClick={() => onUpdate(task, "ASSIGNED", Number(assigneeId))}>{updating ? "A atualizar…" : "Atribuir"}</button></div>}
    {canProgress && task.status === "IN_PROGRESS" && <div className="assign-control task-completion">
      <input aria-label={"Quantidade efetivamente reposta na tarefa " + task.id} type="number" min="0.001" step="0.001" placeholder={task.requested_quantity == null ? "Qtd. reposta" : "Qtd. reposta (pedido: " + task.requested_quantity + ")"} value={actualQuantity} onChange={e => setActualQuantity(e.target.value)} />
      {task.requested_quantity != null && Number.isFinite(actual) && actual > 0 && actual < task.requested_quantity && <input aria-label={"Motivo da reposição parcial na tarefa " + task.id} placeholder="Motivo da diferença" value={exceptionReason} onChange={e => setExceptionReason(e.target.value)} />}
      <button className="row-action" disabled={updating || !isValidCompletion} onClick={() => {
        const detail = exceptionReason.trim() ? `\\nMotivo: ${exceptionReason.trim()}` : "";
        if (!updating && window.confirm(`Confirmar conclusão da tarefa #${task.id}?\\nQuantidade efetivamente reposta: ${actual}${detail}\\nEsta ação será auditada.`)) {
          onUpdate(task, "COMPLETED", undefined, { actual_quantity: actual, ...(exceptionReason.trim() ? { exception_reason: exceptionReason.trim() } : {}) });
        }
      }}>{updating ? "A concluir…" : <>Concluir <ArrowUpRight size={14} /></>}</button>
    </div>}
    {canProgress && next === "IN_PROGRESS" && <button className="row-action" onClick={() => {
      if (!updating && window.confirm(`Iniciar a tarefa #${task.id} para a reposição do produto #${task.product_id}?`)) onUpdate(task, "IN_PROGRESS");
    }} disabled={updating}>{updating ? "A iniciar…" : <>Iniciar <ArrowUpRight size={14} /></>}</button>}
    {canCancelTask && <div className="assign-control task-cancel">
      <input aria-label={"Motivo do cancelamento da tarefa " + task.id} placeholder="Motivo do cancelamento" value={cancellationReason} onChange={event => setCancellationReason(event.target.value)} />
      <button className="row-action" disabled={updating || cancellationReason.trim().length < 3} onClick={() => onUpdate(task, "CANCELLED", undefined, undefined, cancellationReason.trim())}>{updating ? "A cancelar…" : "Cancelar"}</button>
    </div>}
    {canAudit && <div className="task-audit-controls">
      <button className="row-action secondary-action" onClick={() => {
        const nextOpen = !showEvents;
        setShowEvents(nextOpen);
        if (nextOpen && events === null) onLoadEvents(task.id);
      }}>
        <History size={13} /> {showEvents ? "Ocultar cronologia" : "Ver cronologia"}
      </button>
    </div>}
    {canReconcileTask && <div className="assign-control task-reconcile">
      <input aria-label={"Motivo da reconciliação da tarefa " + task.id} placeholder="Motivo da reconciliação" value={reconciliationReason} onChange={event => setReconciliationReason(event.target.value)} />
      <button className="row-action" disabled={reconciliationReason.trim().length < 3 || reconcileLoading} onClick={() => {
        if (window.confirm(`Reconciliar o inventário da tarefa #${task.id} com ${task.actual_quantity} unidades?\\nMotivo: ${reconciliationReason.trim()}\\nSerá criado um movimento e um snapshot auditáveis.`)) {
          onReconcile(task, reconciliationReason.trim());
        }
      }}>
        {reconcileLoading ? "A reconciliar…" : "Confirmar stock"}
      </button>
    </div>}
    {reconcileMessage && <small className="task-reconcile-message" role="status">{reconcileMessage}</small>}
    {showEvents && <div className="task-event-timeline">
      <strong>Cronologia auditável</strong>
      {eventsLoading && <span>A carregar eventos…</span>}
      {!eventsLoading && events === null && <span>A cronologia ainda não foi carregada.</span>}
      {!eventsLoading && events?.length === 0 && <span>Sem eventos registados.</span>}
      {!eventsLoading && events && events.length > 0 && <ol>
        {events.map(event => <li key={event.id}>
          <span className="task-event-heading">{event.event_type.replace(/_/g, " ")} · {formatDateTime(event.created_at)}</span>
          <span>{event.from_status ? `${event.from_status} → ${event.to_status}` : event.to_status || "Evento registado"} · Ator #{event.actor_user_id ?? "sistema"}</span>
          {event.actual_quantity != null && <span>Quantidade: {event.actual_quantity}</span>}
          {event.reason && <span>Motivo: {event.reason}</span>}
        </li>)}
      </ol>}
    </div>}
  </div>;
}
function StatusBar({ label, value, total, color, onClick }: { label: string; value: number; total: number; color: string; onClick: () => void }) {
  const percent = total ? Math.round(value / total * 100) : 0;
  return <button type="button" className="status-bar-row status-bar-action" onClick={onClick} aria-label={`Filtrar tarefas: ${label} (${value})`}>
    <span className="status-bar-label"><span>{label}</span><strong>{value}</strong></span>
    <span className="bar-track"><span className={`bar-fill ${color}`} style={{ width: `${percent}%` }} /></span>
  </button>;
}
