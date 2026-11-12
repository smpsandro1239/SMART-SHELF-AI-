import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowUpRight, Boxes, CheckCircle2,
  CircleUserRound, Clock3, LogOut, PackageSearch, RefreshCw, ShieldCheck,
  Store, Truck, UserRound, Warehouse,
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
type ShelfImage = { id: number; shelf_id: number; original_filename: string; mime_type: string; file_size_bytes: number; sha256: string; analysis_status: string; captured_at: string; created_at: string };
type ShelfImageDetection = { id: number; shelf_image_id: number; product_id: number | null; label: string; confidence: number; x_min: number; y_min: number; x_max: number; y_max: number; model_version: string; created_at: string };
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
  const [tasks, setTasks] = useState<Task[]>([]);
  const [captures, setCaptures] = useState<ShelfImage[]>([]);
  const [imageDetections, setImageDetections] = useState<Record<number, ShelfImageDetection[]>>({});
  const [expandedDetectionImage, setExpandedDetectionImage] = useState<number | null>(null);
  const [detectionLoading, setDetectionLoading] = useState<number | null>(null);
  const [captureShelfId, setCaptureShelfId] = useState("");
  const [captureFile, setCaptureFile] = useState<File | null>(null);
  const [captureReset, setCaptureReset] = useState(0);
  const [captureLoading, setCaptureLoading] = useState(false);
  const [captureMessage, setCaptureMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

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
    setToken(""); setUser(null); setSummary(null); setTasks([]); setCaptures([]); setImageDetections({}); setExpandedDetectionImage(null);
  }, []);

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


  async function toggleImageDetections(item: ShelfImage) {
    if (expandedDetectionImage === item.id) {
      setExpandedDetectionImage(null);
      return;
    }
    setExpandedDetectionImage(item.id);
    if (imageDetections[item.id]) return;
    setDetectionLoading(item.id);
    try {
      const result = await request<ShelfImageDetection[]>(`/api/v1/shelf-images/${item.id}/detections`);
      setImageDetections(current => ({ ...current, [item.id]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível consultar as deteções.");
      setExpandedDetectionImage(null);
    } finally {
      setDetectionLoading(null);
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
                  <div className="capture-row"><div className="capture-thumb"><Boxes size={17} /></div><div className="capture-meta"><strong>Prateleira #{item.shelf_id} · {item.original_filename}</strong><span>{(item.file_size_bytes / 1024).toFixed(0)} KB · {new Date(item.created_at).toLocaleString("pt-PT")}</span></div><span className="task-status pending">{item.analysis_status}</span><button className="row-action detection-toggle" onClick={() => void toggleImageDetections(item)}>{detectionLoading === item.id ? "A consultar…" : expandedDetectionImage === item.id ? "Fechar" : "Deteções"}</button></div>
                  {expandedDetectionImage === item.id && <div className="detection-list">
                    {!imageDetections[item.id]?.length && <p className="detection-empty">Ainda não existem deteções guardadas para esta fotografia. A análise automática ainda não está ativa.</p>}
                    {imageDetections[item.id]?.map(detection => <div className="detection-row" key={detection.id}><strong>{detection.label}</strong><span>{(detection.confidence * 100).toFixed(1)}% confiança</span><span>Caixa: {(detection.x_min * 100).toFixed(1)}%, {(detection.y_min * 100).toFixed(1)}% – {(detection.x_max * 100).toFixed(1)}%, {(detection.y_max * 100).toFixed(1)}%</span><small>Modelo {detection.model_version}{detection.product_id ? ` · Produto #${detection.product_id}` : ""}</small></div>)}
                  </div>}
                </div>)}
              </div>
            </article>
          </section>
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
