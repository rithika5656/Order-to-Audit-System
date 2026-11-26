import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  Activity, AlertTriangle, Archive, ArrowDownToLine, ArrowUpRight, BarChart3,
  Boxes, CalendarDays, CircleDollarSign, ClipboardList, Factory, FileText,
  LayoutDashboard, LogOut, Menu, Package, ReceiptText, ShoppingCart, Truck,
  Users, X,
} from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import api from "./api";

const navItems = [
  { label: "Overview", path: "/", icon: LayoutDashboard, roles: ["Admin", "Owner", "Accountant / Auditor"] },
  { label: "Orders", path: "/orders", icon: ClipboardList, roles: ["Admin", "Owner", "Salesman"] },
  { label: "Customers", path: "/customers", icon: Users, roles: ["Admin", "Owner", "Salesman"] },
  { label: "Suppliers", path: "/suppliers", icon: Truck, roles: ["Admin", "Owner", "Accountant / Auditor"] },
  { label: "Products", path: "/products", icon: Package, roles: ["Admin", "Owner"] },
  { label: "Production", path: "/production", icon: Factory, roles: ["Admin", "Production Supervisor", "Owner"] },
  { label: "BOM / Recipes", path: "/bom", icon: ClipboardList, roles: ["Admin", "Production Supervisor", "Owner"] },
  { label: "Inventory", path: "/inventory", icon: Boxes, roles: ["Admin", "Production Supervisor", "Owner", "Accountant / Auditor"] },
  { label: "Purchases", path: "/purchases", icon: ShoppingCart, roles: ["Admin", "Owner", "Accountant / Auditor"] },
  { label: "Invoices", path: "/invoices", icon: ReceiptText, roles: ["Admin", "Owner", "Accountant / Auditor"] },
  { label: "Reports", path: "/reports", icon: BarChart3, roles: ["Admin", "Owner", "Accountant / Auditor"] },
];

function Login({ onLogin }) {
  const [email, setEmail] = useState("admin@nutriledger.local");
  const [password, setPassword] = useState("NutriLedger2026!");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const { data } = await api.post("/auth/login", { email, password });
      localStorage.setItem("nutriledger_token", data.access_token);
      onLogin(data.user);
    } catch (e) { setError(e.response?.data?.detail || "Unable to sign in. Check that the API is running."); }
    finally { setBusy(false); }
  }
  return <main className="login-shell"><div className="login-brand"><span className="brand-mark"><Activity size={21}/></span><span>NutriLedger</span></div>
    <form className="login-card" onSubmit={submit}><p className="eyebrow">MANUFACTURING OPERATIONS</p><h1>Welcome back</h1><p className="muted">Sign in to your business workspace.</p>
      {error && <div className="error-box">{error}</div>}
      <label>Email address<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
      <button className="primary full" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</button>
      <p className="login-note">Development demo · credentials are documented in README</p>
    </form></main>;
}

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(localStorage.getItem("nutriledger_token")));
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation(); const navigate = useNavigate();
  useEffect(() => {
    if (!localStorage.getItem("nutriledger_token")) { setLoading(false); return; }
    api.get("/auth/me").then(({ data }) => setUser(data))
      .catch(() => { localStorage.removeItem("nutriledger_token"); setUser(null); })
      .finally(() => setLoading(false));
  }, []);
  const links = useMemo(() => navItems.filter((item) => item.roles.includes(user?.role)), [user]);
  function signOut() { localStorage.removeItem("nutriledger_token"); setUser(null); navigate("/login"); }
  if (loading) return <div className="loading-screen">Loading NutriLedger...</div>;
  if (!user) return <Login onLogin={setUser} />;
  const title = links.find((item) => item.path === location.pathname)?.label || "Overview";
  return <div className="app-shell">
    {mobileOpen && <button className="mobile-backdrop" aria-label="Close menu" onClick={() => setMobileOpen(false)} />}
    <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
      <div className="brand"><span className="brand-mark"><Activity size={20}/></span><span>NutriLedger<small>OPERATIONS PLATFORM</small></span><button className="mobile-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={18}/></button></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav>{links.map(({ label, path, icon: Icon }) => <Link key={path} to={path} onClick={() => setMobileOpen(false)} className={`nav-link ${location.pathname === path ? "active" : ""}`}><Icon size={18}/><span>{label}</span></Link>)}</nav>
      <div className="sidebar-bottom"><div className="profile"><div className="avatar">{user.name?.slice(0, 1)}</div><div className="profile-copy"><strong>{user.name}</strong><span>{user.role}</span></div><button className="icon-btn" onClick={signOut} title="Sign out"><LogOut size={17}/></button></div></div>
    </aside>
    <main className="main-area"><header className="topbar"><button className="menu-toggle icon-btn" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu/></button><div><div className="breadcrumbs">NutriLedger <span>/</span> {title}</div><h1>{title}</h1></div><div className="topbar-right"><span className="live-dot"/>Live workspace<div className="top-avatar">{user.name?.slice(0, 1)}</div></div></header>
      <section className="page-content"><Routes>
        <Route path="/" element={<RoleGate role={user.role} allow={["Admin","Owner","Accountant / Auditor"]}><Dashboard/></RoleGate>}/>
        <Route path="/orders" element={<RoleGate role={user.role} allow={["Admin","Owner","Salesman"]}><Orders role={user.role}/></RoleGate>}/>
        <Route path="/customers" element={<RoleGate role={user.role} allow={["Admin","Owner","Salesman"]}><Customers/></RoleGate>}/>
        <Route path="/suppliers" element={<RoleGate role={user.role} allow={["Admin","Owner","Accountant / Auditor"]}><Suppliers/></RoleGate>}/>
        <Route path="/products" element={<RoleGate role={user.role} allow={["Admin","Owner"]}><Products role={user.role}/></RoleGate>}/>
        <Route path="/production" element={<RoleGate role={user.role} allow={["Admin","Owner","Production Supervisor"]}><Production role={user.role}/></RoleGate>}/>
        <Route path="/bom" element={<RoleGate role={user.role} allow={["Admin","Owner","Production Supervisor"]}><Bom role={user.role}/></RoleGate>}/>
        <Route path="/inventory" element={<RoleGate role={user.role} allow={["Admin","Owner","Production Supervisor","Accountant / Auditor"]}><Inventory role={user.role}/></RoleGate>}/>
        <Route path="/purchases" element={<RoleGate role={user.role} allow={["Admin","Owner","Accountant / Auditor"]}><Purchases role={user.role}/></RoleGate>}/>
        <Route path="/invoices" element={<RoleGate role={user.role} allow={["Admin","Owner","Accountant / Auditor"]}><Invoices role={user.role}/></RoleGate>}/>
        <Route path="/reports" element={<RoleGate role={user.role} allow={["Admin","Owner","Accountant / Auditor"]}><Reports/></RoleGate>}/>
        <Route path="*" element={<Navigate to="/" replace/>}/>
      </Routes></section>
    </main>
  </div>;
}

function RoleGate({ role, allow, children }) {
  if (allow.includes(role)) return children;
  const fallback = role === "Salesman" ? "/orders" : role === "Production Supervisor" ? "/production" : "/inventory";
  return <Navigate to={fallback} replace/>;
}

function useResource(url, fallback = []) {
  const [data, setData] = useState(fallback); const [error, setError] = useState(""); const [busy, setBusy] = useState(true);
  async function reload() {
    setBusy(true); setError("");
    try { const result = await api.get(url); setData(result.data); }
    catch (e) { setError(e.response?.data?.detail || "Could not load data from the API."); }
    finally { setBusy(false); }
  }
  useEffect(() => { reload(); }, [url]);
  return { data, error, busy, reload };
}
function ErrorMessage({ children }) { return children ? <div className="error-box">{children}</div> : null; }
function PageIntro({ eyebrow, title, description, action }) { return <div className="page-intro"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p className="muted">{description}</p></div>{action}</div>; }
function StatCard({ title, value, detail, icon: Icon, tone = "blue" }) { return <article className="stat-card"><div className={`stat-icon ${tone}`}><Icon size={19}/></div><p>{title}</p><strong>{value}</strong><span>{detail}</span></article>; }
function DataTable({ columns, rows, empty = "No records found." }) {
  return <div className="table-wrap"><table><thead><tr>{columns.map((col) => <th key={col.key}>{col.label}</th>)}</tr></thead><tbody>
    {rows.map((row, i) => <tr key={row.id || row.reference || i}>{columns.map((col) => <td key={col.key}>{col.render ? col.render(row[col.key], row) : (row[col.key] ?? "—")}</td>)}</tr>)}
    {!rows.length && <tr><td className="empty-cell" colSpan={columns.length}>{empty}</td></tr>}
  </tbody></table></div>;
}
function Badge({ children }) { const cls = String(children).toLowerCase().replaceAll(" ", "-"); return <span className={`badge ${cls}`}>{children}</span>; }
function money(value) { return `₹${Number(value || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }

function Dashboard() {
  const dateInput = (value) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  const [toDate, setToDate] = useState(() => dateInput(new Date()));
  const [fromDate, setFromDate] = useState(() => {
    const start = new Date();
    start.setDate(start.getDate() - 29);
    return dateInput(start);
  });
  const { data, error, busy } = useResource(`/dashboard?from_date=${fromDate}&to_date=${toDate}`, {});
  const materials = data.raw_materials || []; const goods = data.finished_goods || [];
  const performance = data.production_performance || [];
  const expectedOutput = performance.reduce((sum, run) => sum + Number(run.expected), 0);
  const actualOutput = performance.reduce((sum, run) => sum + Number(run.actual), 0);
  const efficiency = expectedOutput ? `${Math.round(actualOutput / expectedOutput * 100)}%` : "—";
  const goodsUnits = goods.reduce((sum, item) => sum + Number(item.available_quantity ?? item.quantity), 0);
  const revenueSeries = data.revenue_analytics?.series || [];
  return <><PageIntro eyebrow={data.company?.demo_data ? "DEMO DATA · BUSINESS SNAPSHOT" : "BUSINESS SNAPSHOT"} title={data.company?.name || "Good business starts with visibility."} description={data.company ? `${data.company.city}, ${data.company.state} · ${data.company.business}` : "A live view of sales, stock and day-to-day operations."}/>
    <ErrorMessage>{error}</ErrorMessage>
    {busy ? <div className="loading-panel">Loading business records…</div> : <>
      <div className="stat-grid">
        <StatCard title="Sales to date" value={money(data.total_sales)} detail="Taxable invoice value" icon={CircleDollarSign}/>
        <StatCard title="Orders received today" value={data.today_orders ?? 0} detail="Orders submitted today" icon={ClipboardList}/>
        <StatCard title="Active production" value={data.active_production_runs ?? 0} detail="Planned or in progress" icon={Factory}/>
        <StatCard title="Pending dispatches" value={data.pending_dispatch_count ?? 0} detail="Invoices with units to ship" icon={Truck}/>
        <StatCard title="Outstanding payments" value={money(data.outstanding_receivables)} detail="Unpaid invoice balances" icon={CircleDollarSign}/>
        <StatCard title="Raw material alerts" value={data.raw_material_alert_count ?? 0} detail="Materials below their stock policy" icon={AlertTriangle} tone="amber"/>
        <StatCard title="Finished goods" value={`${goodsUnits.toLocaleString()} pkts`} detail="Across active products" icon={Archive}/>
        <StatCard title="Production efficiency" value={`${data.production_efficiency_percent ?? efficiency}${data.production_efficiency_percent ? "%" : ""}`} detail="Cumulative good output vs expected" icon={Activity}/>
        <StatCard title="Total orders" value={data.total_orders ?? 0} detail="All recorded order statuses" icon={ClipboardList}/>
        <StatCard title="Inventory valuation" value={money(data.inventory_valuation)} detail="Ledger balance at estimated cost" icon={Boxes}/>
      </div>
      <section className="panel chart-panel"><div className="panel-heading dashboard-chart-heading"><div><h3>Revenue analytics</h3><p>Taxable invoice value by day · select a date range</p></div><div className="date-filter"><label><CalendarDays size={14}/><input aria-label="Revenue start date" type="date" value={fromDate} max={toDate} onChange={(event) => setFromDate(event.target.value)}/></label><span>to</span><label><CalendarDays size={14}/><input aria-label="Revenue end date" type="date" value={toDate} min={fromDate} onChange={(event) => setToDate(event.target.value)}/></label></div></div><div className="chart-height"><ResponsiveContainer width="100%" height="100%"><LineChart data={revenueSeries} margin={{top:8,right:12,left:0,bottom:0}}><CartesianGrid stroke="#e5eaf2" vertical={false}/><XAxis dataKey="date" tick={{fontSize:9,fill:"#8590a2"}} axisLine={false} tickLine={false} minTickGap={24} tickFormatter={(value)=>new Date(`${value}T00:00:00`).toLocaleDateString(undefined,{month:"short",day:"numeric"})}/><YAxis tick={{fontSize:10,fill:"#8590a2"}} axisLine={false} tickLine={false} tickFormatter={(value)=>Number(value).toLocaleString("en-IN")}/><Tooltip labelFormatter={(value)=>new Date(`${value}T00:00:00`).toLocaleDateString()} formatter={(value)=>money(value)} contentStyle={{border:"1px solid #dce5f2",borderRadius:8,boxShadow:"0 8px 24px #172b4d18"}}/><Line type="monotone" dataKey="revenue" name="Taxable revenue" stroke="#2864B4" strokeWidth={2.5} dot={false} activeDot={{r:4}}/></LineChart></ResponsiveContainer></div></section>
      <section className="panel chart-panel"><div className="panel-heading"><div><h3>Production performance</h3><p>Expected versus actual good output · latest completed batches</p></div></div><div className="chart-height">{performance.length?<ResponsiveContainer width="100%" height="100%"><BarChart data={performance} margin={{top:8,right:12,left:0,bottom:0}}><CartesianGrid stroke="#e5eaf2" vertical={false}/><XAxis dataKey="reference" tick={{fontSize:9,fill:"#8590a2"}} axisLine={false} tickLine={false}/><YAxis tick={{fontSize:10,fill:"#8590a2"}} axisLine={false} tickLine={false}/><Tooltip contentStyle={{border:"1px solid #dce5f2",borderRadius:8}}/><Legend wrapperStyle={{fontSize:10}}/><Bar dataKey="expected" name="Expected output" fill="#83B5FF" radius={[4,4,0,0]} maxBarSize={34}/><Bar dataKey="actual" name="Actual good output" fill="#2864B4" radius={[4,4,0,0]} maxBarSize={34}/></BarChart></ResponsiveContainer>:<div className="chart-empty">Production data will appear after the first batch is completed.</div>}</div></section>
      <div className="dashboard-grid">
        <section className="panel"><div className="panel-heading"><div><h3>Today's operations</h3><p>Activity recorded for {new Date().toLocaleDateString()}</p></div><Activity size={18}/></div>
          <div className="goods-grid">
            <div className="goods-item"><span>Orders received</span><strong>{data.today_operations?.orders_received ?? 0}</strong></div>
            <div className="goods-item"><span>Production batches</span><strong>{data.today_operations?.production_batches ?? 0}</strong></div>
            <div className="goods-item"><span>Units produced</span><strong>{data.today_operations?.units_produced ?? 0}</strong></div>
            <div className="goods-item"><span>Dispatches</span><strong>{data.today_operations?.dispatches ?? 0}</strong></div>
            <div className="goods-item"><span>Payments collected</span><strong>{money(data.today_operations?.payments_collected)}</strong></div>
          </div>
        </section>
        <section className="panel chart-panel"><div className="panel-heading"><div><h3>Monthly production</h3><p>Expected versus actual good output</p></div></div><div className="chart-height">
          {(data.monthly_production||[]).length?<ResponsiveContainer width="100%" height="100%"><BarChart data={data.monthly_production}><CartesianGrid stroke="#e5eaf2" vertical={false}/><XAxis dataKey="month" tick={{fontSize:9,fill:"#8590a2"}} axisLine={false} tickLine={false}/><YAxis tick={{fontSize:10,fill:"#8590a2"}} axisLine={false} tickLine={false}/><Tooltip/><Legend wrapperStyle={{fontSize:10}}/><Bar dataKey="expected" name="Expected" fill="#83B5FF" radius={[4,4,0,0]}/><Bar dataKey="actual" name="Actual" fill="#2864B4" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer>:<div className="chart-empty">No production records in this period.</div>}
        </div></section>
      </div>
      <div className="dashboard-grid">
        <section className="panel"><div className="panel-heading"><div><h3>Top-selling products</h3><p>Ranked by invoiced units</p></div><Link className="text-link" to="/products">Catalogue</Link></div>
          <DataTable columns={[{key:"product",label:"Product"},{key:"units_sold",label:"Units"},{key:"revenue",label:"Taxable revenue",render:money}]} rows={data.top_selling_products||[]}/>
        </section>
        <section className="panel"><div className="panel-heading"><div><h3>Top customers</h3><p>Ranked by invoiced sales</p></div><Link className="text-link" to="/customers">Customers</Link></div>
          <DataTable columns={[{key:"customer",label:"Customer"},{key:"invoices",label:"Invoices"},{key:"revenue",label:"Taxable revenue",render:money}]} rows={data.top_customers||[]}/>
        </section>
      </div>
      <div className="dashboard-grid">
        <section className="panel"><div className="panel-heading"><div><h3>Customer payments pending</h3><p>Open invoice balances</p></div><Link className="text-link" to="/invoices">Invoices</Link></div>
          <DataTable columns={[{key:"customer",label:"Customer"},{key:"invoice",label:"Invoice"},{key:"amount_due",label:"Amount due",render:money}]} rows={data.pending_customer_payments||[]}/>
        </section>
      </div>
      <div className="dashboard-grid">
        <section className="panel chart-panel"><div className="panel-heading"><div><h3>Wastage trend</h3><p>Damaged units and expected-output shortfall</p></div></div><div className="chart-height">
          {(data.monthly_wastage||[]).length?<ResponsiveContainer width="100%" height="100%"><BarChart data={data.monthly_wastage}><CartesianGrid stroke="#e5eaf2" vertical={false}/><XAxis dataKey="month" tick={{fontSize:9,fill:"#8590a2"}} axisLine={false} tickLine={false}/><YAxis tick={{fontSize:10,fill:"#8590a2"}} axisLine={false} tickLine={false}/><Tooltip/><Legend wrapperStyle={{fontSize:10}}/><Bar dataKey="damaged" name="Damaged units" fill="#3979C9" radius={[4,4,0,0]}/><Bar dataKey="yield_shortfall" name="Yield shortfall" fill="#83B5FF" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer>:<div className="chart-empty">No production records in this period.</div>}
        </div></section>
        <section className="panel chart-panel"><div className="panel-heading"><div><h3>Payment collection trend</h3><p>Payments received by month</p></div></div><div className="chart-height">
          {(data.monthly_payments||[]).length?<ResponsiveContainer width="100%" height="100%"><LineChart data={data.monthly_payments}><CartesianGrid stroke="#e5eaf2" vertical={false}/><XAxis dataKey="month" tick={{fontSize:9,fill:"#8590a2"}} axisLine={false} tickLine={false}/><YAxis tick={{fontSize:10,fill:"#8590a2"}} axisLine={false} tickLine={false}/><Tooltip formatter={money}/><Line type="monotone" dataKey="collected" name="Collected" stroke="#2864B4" strokeWidth={2.5} dot={{r:3}}/></LineChart></ResponsiveContainer>:<div className="chart-empty">No payment records in this period.</div>}
        </div></section>
        <section className="panel"><div className="panel-heading"><div><h3>Recent production batches</h3><p>Latest recorded production history</p></div><Link className="text-link" to="/production">Production</Link></div>
          <DataTable columns={[{key:"reference",label:"Batch"},{key:"product",label:"Product"},{key:"good_output",label:"Good output"},{key:"damaged",label:"Damaged"},{key:"status",label:"Status",render:v=><Badge>{v}</Badge>}]} rows={data.recent_production_batches||[]}/>
        </section>
      </div>
      <div className="dashboard-actions"><strong>Quick actions</strong><Link to="/orders"><ClipboardList size={16}/>Review orders<ArrowUpRight size={14}/></Link><Link to="/production"><Factory size={16}/>Record production<ArrowUpRight size={14}/></Link><Link to="/inventory"><Package size={16}/>Check inventory<ArrowUpRight size={14}/></Link><Link to="/invoices"><CircleDollarSign size={16}/>View invoices<ArrowUpRight size={14}/></Link></div>
      <section className="panel attention-panel"><div className="panel-heading"><div><h3>What Needs Attention Today?</h3><p>Actionable alerts generated from current orders, stock, batches and invoices</p></div><AlertTriangle size={18}/></div><div className="attention-list">{(data.attention||[]).map((item,index)=><Link className={`attention-item ${item.severity}`} key={`${item.type}-${item.title}-${index}`} to={item.href}><span className="attention-icon"><AlertTriangle size={16}/></span><span className="attention-copy"><strong>{item.title}</strong><small>{item.detail}</small></span><ArrowUpRight size={15}/></Link>)}{!data.attention?.length&&<div className="empty-state">No priority items need attention right now.</div>}</div></section>
      <div className="dashboard-grid"><section className="panel"><div className="panel-heading"><div><h3>Recent orders</h3><p>Latest activity recorded in your workspace</p></div><Link className="text-link" to="/orders">View all</Link></div>
        <DataTable columns={[{key:"reference",label:"Order"},{key:"customer",label:"Customer"},{key:"quantity",label:"Units"},{key:"status",label:"Status",render:v=><Badge>{v}</Badge>}]} rows={data.recent_orders || []}/>
      </section><section className="panel"><div className="panel-heading"><div><h3>Stock watch</h3><p>Current raw-material balances</p></div><Link className="text-link" to="/inventory">Inventory</Link></div>
        <div className="stock-list">{materials.slice(0, 5).map((item) => <div className="stock-row" key={item.material}><div><strong>{item.material}</strong><span>{item.available_quantity} usable of {item.quantity} {item.unit}{item.estimated_days_remaining?` · ${item.estimated_days_remaining} days cover`:""}</span></div>{item.low && <Badge>Low stock</Badge>}</div>)}{!materials.length && <div className="empty-state">No inventory records yet.</div>}</div>
      </section></div>
      <div className="dashboard-grid"><section className="panel goods-panel"><div className="panel-heading"><div><h3>Finished goods overview</h3><p>Available stock and reorder signals</p></div><Package size={18}/></div><div className="goods-grid">{goods.map((item) => <div className="goods-item" key={item.product}><span>{item.product}{item.low&&<Badge>Reorder</Badge>}</span><strong>{item.available_quantity ?? item.quantity} <small>{item.unit}</small></strong></div>)}</div></section><section className="panel activity-panel"><div className="panel-heading"><div><h3>Recent business activity</h3><p>Latest recorded actions</p></div><Activity size={18}/></div><div className="activity-list">{(data.recent_activities||[]).map(item=><div className="activity-row" key={item.id}><span className="activity-mark"><Activity size={13}/></span><div><strong>{item.user} {item.action} {item.entity.replaceAll("_"," ")}</strong><small>{item.entity_id} · {new Date(item.created_at).toLocaleString()}</small></div></div>)}{!data.recent_activities?.length&&<div className="empty-state">Business actions will appear here as they are recorded.</div>}</div></section></div>
    </>}
  </>;
}

function Orders({ role }) {
  const { data: orders, error, busy, reload } = useResource("/orders");
  const { data: customers } = useResource("/customers"); const { data: products } = useResource("/products");
  const [form, setForm] = useState({ customer_id: "", product_id: "", quantity: 1 }); const [message, setMessage] = useState("");
  async function submit(e) { e.preventDefault(); setMessage(""); try { const { data } = await api.post("/orders", {...form, customer_id:Number(form.customer_id), product_id:Number(form.product_id), quantity:Number(form.quantity)}); setMessage(`Order ${data.reference} submitted${Number(data.shortage) ? ` · ${data.shortage} packet shortage warning` : ""}.`); reload(); } catch (x) { setMessage(x.response?.data?.detail || "Unable to submit order."); } }
  async function action(id, path) { try { const result = await api.post(`/orders/${id}/${path}`); setMessage(path === "invoice" ? `Invoice ${result.data.number} created.` : `Order ${result.data.status.toLowerCase()}.`); reload(); } catch (x) { setMessage(x.response?.data?.detail || "Action failed."); } }
  return <><PageIntro eyebrow="SALES WORKFLOW" title="Orders" description="Capture customer demand and follow it through review, invoicing and dispatch."/>
    {role === "Salesman" || role === "Admin" ? <form className="panel form-panel compact-form" onSubmit={submit}><h3>Create an order</h3><div className="form-grid"><label>Customer<select required value={form.customer_id} onChange={e=>setForm({...form,customer_id:e.target.value})}><option value="">Select customer</option>{customers.map(c=><option key={c.id} value={c.id}>{c.name} · {c.state}</option>)}</select></label><label>Product<select required value={form.product_id} onChange={e=>setForm({...form,product_id:e.target.value})}><option value="">Select product</option>{products.map(p=><option key={p.id} value={p.id}>{p.name} · {money(p.selling_price)}</option>)}</select></label><label>Quantity<input type="number" min="1" required value={form.quantity} onChange={e=>setForm({...form,quantity:e.target.value})}/></label><button className="primary">Submit order</button></div>{message && <p className="inline-message">{message}</p>}</form> : null}
    {role !== "Salesman" && message && <p className="inline-message">{message}</p>}<ErrorMessage>{error}</ErrorMessage>
    <section className="panel"><div className="panel-heading"><div><h3>Order register</h3><p>{orders.length} records</p></div></div>{busy ? <div className="loading-panel">Loading orders…</div> : <DataTable columns={[{key:"reference",label:"Reference"},{key:"customer",label:"Customer"},{key:"product",label:"Product"},{key:"quantity",label:"Qty"},{key:"unit_price",label:"Unit price",render:money},{key:"approval_status",label:"Approval",render:v=><Badge>{v}</Badge>},{key:"fulfillment_stage",label:"Fulfilment",render:v=><Badge>{v}</Badge>},{key:"payment_status",label:"Payment",render:v=><Badge>{v}</Badge>},{key:"invoice_total",label:"Invoice",render:v=>v===null?"—":money(v)},{key:"amount_due",label:"Due",render:money},{key:"pending_action",label:"Pending action"},{key:"id",label:"Actions",render:(_,row)=><div className="row-actions">{role==="Admin"&&row.status==="Submitted"&&<button className="small-btn" onClick={()=>action(row.id,"approve")}>Approve</button>}{role==="Admin"&&row.status==="Approved"&&<button className="small-btn" onClick={()=>action(row.id,"invoice")}>Invoice</button>}{role==="Admin"&&Number(row.available_stock)<row.quantity&&<span className="warning-text">Stock check</span>}</div>}]} rows={orders}/>}</section>
  </>;
}

function Customers() {
  const { data, error, busy } = useResource("/customers"); const [query, setQuery] = useState("");
  const rows = data.filter(c => `${c.name} ${c.state} ${c.customer_type}`.toLowerCase().includes(query.toLowerCase()));
  return <><PageIntro eyebrow="CUSTOMER DIRECTORY" title="Customers" description="Retailers and distribution partners across your markets."/><div className="toolbar"><input placeholder="Search customers…" value={query} onChange={e=>setQuery(e.target.value)}/><span>{rows.length} customers</span></div><ErrorMessage>{error}</ErrorMessage><section className="panel">{busy?<div className="loading-panel">Loading customers…</div>:<DataTable columns={[{key:"name",label:"Customer"},{key:"customer_type",label:"Type",render:v=><Badge>{v}</Badge>},{key:"state",label:"State"},{key:"gstin",label:"GSTIN"},{key:"contact",label:"Contact"},{key:"credit_limit",label:"Credit limit",render:money},{key:"outstanding_balance",label:"Outstanding",render:money}]} rows={rows}/>}</section></>;
}
function Suppliers() {
  const { data, error, busy } = useResource("/suppliers");
  return <><PageIntro eyebrow="SUPPLIER DIRECTORY" title="Suppliers" description="Supplier contacts, test GST identifiers, payment terms and supplied materials."/><ErrorMessage>{error}</ErrorMessage><section className="panel">{busy?<div className="loading-panel">Loading suppliers…</div>:<DataTable columns={[{key:"name",label:"Supplier"},{key:"materials",label:"Materials",render:v=>v.join(", ")||"—"},{key:"gstin",label:"GSTIN"},{key:"contact",label:"Contact"},{key:"payment_terms",label:"Payment terms"}]} rows={data}/>}</section></>;
}
function Products({ role }) {
  const { data, error, busy, reload } = useResource("/products"); const [show, setShow] = useState(false); const [form, setForm] = useState({name:"",sku:"",selling_price:"",gst_rate:"5"});
  async function submit(e) { e.preventDefault(); try { await api.post("/products",form); setShow(false); setForm({name:"",sku:"",selling_price:"",gst_rate:"5"}); reload(); } catch(x) { alert(x.response?.data?.detail || "Could not add product."); } }
  return <><PageIntro eyebrow="CATALOG" title="Products" description="Product codes, pack formats, tax rates and selling prices." action={role==="Admin"?<button className="primary" onClick={()=>setShow(!show)}>＋ New product</button>:null}/>
    {show&&<form className="panel form-panel" onSubmit={submit}><h3>Add product</h3><div className="form-grid"><label>Name<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>SKU<input required value={form.sku} onChange={e=>setForm({...form,sku:e.target.value})}/></label><label>Selling price<input type="number" min="0" step=".01" required value={form.selling_price} onChange={e=>setForm({...form,selling_price:e.target.value})}/></label><label>GST %<input type="number" min="0" step=".01" value={form.gst_rate} onChange={e=>setForm({...form,gst_rate:e.target.value})}/></label><button className="primary">Save product</button></div></form>}
    <ErrorMessage>{error}</ErrorMessage><section className="panel">{busy?<div className="loading-panel">Loading products…</div>:<DataTable columns={[{key:"name",label:"Product"},{key:"sku",label:"SKU"},{key:"category",label:"Category"},{key:"pack_size",label:"Pack"},{key:"selling_price",label:"Price",render:money},{key:"gst_rate",label:"GST",render:v=>`${v}%`},{key:"hsn_code",label:"HSN"},{key:"reorder_level",label:"Minimum stock"},{key:"active",label:"Active",render:v=><Badge>{v?"Active":"Inactive"}</Badge>},{key:"stock",label:"Stock",render:(v,row)=>`${v} ${row.unit}`}]} rows={data}/>}</section></>;
}
function Inventory({role}) {
  const {data,error,busy,reload}=useResource("/inventory"); const {data:ledger,error:ledgerError,busy:ledgerBusy}=useResource("/inventory/ledger");
  return <><PageIntro eyebrow="STOCK CONTROL" title="Inventory intelligence" description="Ledger-based balances, reorder policies, historical usage, stock cover and batch expiry."/><ErrorMessage>{error||ledgerError}</ErrorMessage><div className="section-title"><h3>Raw materials & packaging</h3></div><section className="panel">{busy?<div className="loading-panel">Loading stock intelligence…</div>:<DataTable columns={[{key:"name",label:"Material"},{key:"quantity",label:"On hand",render:(v,row)=><span className={row.low_stock?"warning-text":""}>{v} {row.unit}</span>},{key:"available_quantity",label:"Usable",render:(v,row)=>`${v} ${row.unit}`},{key:"average_daily_usage",label:"Avg. daily use",render:(v,row)=>`${v} ${row.unit}`},{key:"estimated_days_remaining",label:"Days remaining",render:v=>v===null?"—":`${v} days`},{key:"suggested_reorder_quantity",label:"Suggested reorder"},{key:"minimum_stock",label:"Minimum stock"},{key:"weighted_average_cost",label:"Weighted avg. cost",render:(v,row)=>`${money(v)} / ${row.unit}`},{key:"lots",label:"Batch / expiry",render:v=><LotList lots={v}/>},{key:"id",label:"Policy",render:(_,row)=>role==="Admin"?<InventoryPolicyEditor item={row} type="material" onSaved={reload}/>:"—"}]} rows={data.materials||[]}/>}</section><div className="section-title"><h3>Finished goods</h3></div><section className="panel">{busy?<div className="loading-panel">Loading stock intelligence…</div>:<DataTable columns={[{key:"name",label:"Product"},{key:"quantity",label:"On hand",render:(v,row)=>`${v} ${row.unit}`},{key:"available_quantity",label:"Available",render:(v,row)=><span className={row.low_stock?"warning-text":""}>{v} {row.unit}</span>},{key:"average_daily_usage",label:"Avg. dispatch / day",render:(v,row)=>`${v} ${row.unit}`},{key:"estimated_days_remaining",label:"Days remaining",render:v=>v===null?"—":`${v} days`},{key:"suggested_reorder_quantity",label:"Suggested reorder"},{key:"minimum_stock",label:"Minimum stock"},{key:"lots",label:"Batch / expiry",render:v=><LotList lots={v}/>},{key:"id",label:"Policy",render:(_,row)=>role==="Admin"?<InventoryPolicyEditor item={row} type="finished" onSaved={reload}/>:"—"}]} rows={data.finished_goods||[]}/>}</section><div className="section-title"><h3>Recent stock movements</h3></div><section className="panel">{ledgerBusy?<div className="loading-panel">Loading ledger…</div>:<DataTable columns={[{key:"created_at",label:"Date",render:v=>new Date(v).toLocaleString()},{key:"item_type",label:"Type"},{key:"item_id",label:"Item ID"},{key:"quantity",label:"Change",render:(v,row)=>`${v} ${row.unit}`},{key:"source_type",label:"Source"},{key:"source_id",label:"Document"},{key:"batch_code",label:"Batch",render:(v,row)=>row.allocations?.length?row.allocations.map(allocation=>`${allocation.batch_code} (${allocation.quantity})`).join(", "):v||"—"},{key:"expiry_date",label:"Expiry"}]} rows={ledger}/>}</section></>;
}
function LotList({lots=[]}) {
  if(!lots.length)return <span className="muted">No tracked lots</span>;
  return <div className="lot-list">{lots.map(lot=><span className={lot.expired||lot.expiring_soon?"warning-text":""} key={lot.id}>{lot.batch_code}: {lot.quantity}{lot.expiry_date?` · exp ${lot.expiry_date}`:""}</span>)}</div>;
}
function InventoryPolicyEditor({item,type,onSaved}) {
  const [minimum,setMinimum]=useState(item.minimum_stock);
  const [days,setDays]=useState(item.target_coverage_days);
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const [saving,setSaving]=useState(false);
  async function save(event) {
    event.preventDefault();setSaving(true);setError("");setNotice("");
    try {
      await api.put(`/inventory/${type}/${item.id}/policy`,{minimum_stock:Number(minimum),target_coverage_days:Number(days)});
      setNotice("Saved");onSaved();
    } catch(e) { setError(e.response?.data?.detail||"Policy update failed."); }
    finally { setSaving(false); }
  }
  return <details className="policy-editor"><summary>Edit</summary><form onSubmit={save}><label>Minimum stock<input type="number" min="0" step=".001" required value={minimum} onChange={e=>setMinimum(e.target.value)}/></label><label>Target coverage days<input type="number" min="1" max="365" required value={days} onChange={e=>setDays(e.target.value)}/></label><button className="small-btn" disabled={saving}>{saving?"Saving…":"Save policy"}</button>{error&&<small className="error-text">{error}</small>}{notice&&<small>{notice}</small>}</form></details>;
}
function Production({role}) {
  const {data:products}=useResource("/products");
  const {data:ledger,error,busy,reload}=useResource("/inventory/ledger");
  const {data:runs,error:runtimeError,busy:runtimeBusy,reload:reloadRuns}=useResource("/production-runs");
  const [form,setForm]=useState({product_id:"",expected_output:200,good_output:"",damaged:0,reference:`RUN-${Date.now()}`,finished_expiry_date:"",actual_consumption:{}});
  const {data:bom}=useResource(form.product_id?`/bom/${form.product_id}`:"/bom/0");
  const [notice,setNotice]=useState("");
  async function submit(e) {
    e.preventDefault();
    try {
      const payload={...form,product_id:Number(form.product_id),expected_output:Number(form.expected_output),good_output:Number(form.good_output),damaged:Number(form.damaged),actual_consumption:Object.fromEntries(Object.entries(form.actual_consumption).map(([k,v])=>[k,Number(v)]))};
      if(!payload.finished_expiry_date)delete payload.finished_expiry_date;
      const {data}=await api.post("/production-runs",payload);
      setNotice(`Production completed. Yield variance: ${data.yield_variance_percent}%.${data.variance_alert?" Variance exceeds 3%.":""}`);
      setForm({...form,reference:`RUN-${Date.now()}`,good_output:"",damaged:0,finished_expiry_date:"",actual_consumption:{}});
      reload();reloadRuns();
    } catch(x) { setNotice(x.response?.data?.detail||"Production run failed."); }
  }
  async function recordExpense(run) {
    const category=prompt("Expense category (for example Labour or Gas and power):");
    if(!category)return;
    const amount=prompt("Expense amount in rupees:");
    if(amount===null)return;
    try {
      await api.post(`/production-runs/${run.id}/expenses`,{category,amount,reference:`EXP-${Date.now()}`});
      setNotice(`Expense recorded for ${run.reference}.`);
    } catch(x) { setNotice(x.response?.data?.detail||"Expense could not be recorded."); }
  }
  return <><PageIntro eyebrow="FACTORY FLOOR" title="Production" description="Record planned batches, actual consumption, output and variance."/><ErrorMessage>{error||runtimeError}</ErrorMessage>{(role==="Admin"||role==="Production Supervisor")&&<form className="panel form-panel" onSubmit={submit}><h3>Record production run</h3><div className="form-grid"><label>Product<select required value={form.product_id} onChange={e=>setForm({...form,product_id:e.target.value,actual_consumption:{}})}><option value="">Choose product</option>{products.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>Batch reference<input required value={form.reference} onChange={e=>setForm({...form,reference:e.target.value})}/></label><label>Expected output<input type="number" min="1" required value={form.expected_output} onChange={e=>setForm({...form,expected_output:e.target.value})}/></label><label>Good output<input type="number" min="0" required value={form.good_output} onChange={e=>setForm({...form,good_output:e.target.value})}/></label><label>Damaged pouches<input type="number" min="0" required value={form.damaged} onChange={e=>setForm({...form,damaged:e.target.value})}/></label><label>Finished-goods expiry (optional)<input type="date" value={form.finished_expiry_date} onChange={e=>setForm({...form,finished_expiry_date:e.target.value})}/></label></div><p className="form-caption">Record actual use for every BOM material. Damaged pouches are issued separately from good output.</p><div className="form-grid">{bom.map(item=><label key={item.material_id}>{item.material} · planned {Number(item.quantity)*Number(form.expected_output)/Number(item.per_output)} {item.unit}<input required type="number" min="0" step=".001" placeholder={`Actual ${item.unit}`} value={form.actual_consumption[item.material_id]||""} onChange={e=>setForm({...form,actual_consumption:{...form.actual_consumption,[item.material_id]:e.target.value}})}/></label>)}</div><button className="primary" disabled={!bom.length}>Post production & stock movements</button>{notice&&<p className="inline-message">{notice}</p>}</form>}<section className="panel"><div className="panel-heading"><div><h3>Production runs</h3><p>Recorded output and variance</p></div></div>{runtimeBusy?<div className="loading-panel">Loading runs…</div>:<DataTable columns={[{key:"reference",label:"Batch"},{key:"product",label:"Product"},{key:"expected_output",label:"Expected"},{key:"good_output",label:"Good output"},{key:"damaged",label:"Damaged"},{key:"yield_variance_percent",label:"Yield variance",render:(v,row)=><span className={row.variance_alert?"warning-text":""}>{v}%</span>},{key:"id",label:"Actions",render:(_,row)=>role==="Admin"?<button className="small-btn" onClick={()=>recordExpense(row)}>Add overhead</button>:null}]} rows={runs}/>}</section><section className="panel"><div className="panel-heading"><div><h3>Movement history</h3><p>Production issues and finished output from the inventory ledger</p></div></div>{busy?<div className="loading-panel">Loading records…</div>:<DataTable columns={[{key:"source_id",label:"Batch / source"},{key:"item_type",label:"Stock type"},{key:"quantity",label:"Quantity movement"},{key:"unit",label:"Unit"},{key:"created_at",label:"Date",render:v=>new Date(v).toLocaleString()}]} rows={ledger.filter(m=>m.source_type==="production"||m.source_type==="production-damage")}/>}</section></>;
}
function Bom({role}) {
  const {data:products}=useResource("/products");
  const {data:inventory}=useResource("/inventory");
  const [productId,setProductId]=useState("");
  const {data:bom,error,busy,reload}=useResource(`/bom/${productId||0}`);
  const [items,setItems]=useState([]); const [notice,setNotice]=useState("");
  useEffect(()=>{if(!productId&&products.length)setProductId(String(products[0].id));},[productId,products]);
  useEffect(()=>{setItems(bom.map(row=>({material_id:String(row.material_id),quantity:row.quantity,per_output:row.per_output})));},[bom]);
  function update(index,key,value){setItems(items.map((item,i)=>i===index?{...item,[key]:value}:item));}
  async function save(e){e.preventDefault();setNotice("");try{await api.put(`/bom/${productId}`,{items:items.map(item=>({material_id:Number(item.material_id),quantity:Number(item.quantity),per_output:Number(item.per_output)}))});setNotice("Recipe saved.");reload();}catch(x){setNotice(x.response?.data?.detail||"Could not save recipe.");}}
  const materials=inventory.materials||[];
  return <><PageIntro eyebrow="PRODUCTION RECIPES" title="Bill of materials" description="Define required ingredients and packaging per expected output."/><ErrorMessage>{error}</ErrorMessage><section className="panel bom-panel"><label className="bom-product">Product<select value={productId} onChange={e=>setProductId(e.target.value)}>{products.map(product=><option key={product.id} value={product.id}>{product.name}</option>)}</select></label>{busy?<div className="loading-panel">Loading recipe…</div>:<form onSubmit={save}><div className="table-wrap"><table><thead><tr><th>Material</th><th>Quantity</th><th>Per output</th>{role==="Admin"&&<th/>}</tr></thead><tbody>{items.map((item,index)=><tr key={`${productId}-${index}`}><td><select disabled={role!=="Admin"} value={item.material_id} onChange={e=>update(index,"material_id",e.target.value)}>{materials.map(material=><option key={material.id} value={material.id}>{material.name} ({material.unit})</option>)}</select></td><td><input disabled={role!=="Admin"} type="number" min=".001" step=".001" required value={item.quantity} onChange={e=>update(index,"quantity",e.target.value)}/></td><td><input disabled={role!=="Admin"} type="number" min=".001" step=".001" required value={item.per_output} onChange={e=>update(index,"per_output",e.target.value)}/></td>{role==="Admin"&&<td><button type="button" className="small-btn" onClick={()=>setItems(items.filter((_,i)=>i!==index))}>Remove</button></td>}</tr>)}</tbody></table>{!items.length&&<div className="empty-state">No recipe items are configured.</div>}</div>{role==="Admin"&&<div className="bom-actions"><button type="button" className="small-btn" onClick={()=>setItems([...items,{material_id:materials[0]?String(materials[0].id):"",quantity:"",per_output:"200"}])} disabled={!materials.length}>Add material</button><button className="primary" disabled={!productId||!items.length}>Save recipe</button></div>}{notice&&<p className="inline-message">{notice}</p>}</form>}</section></>;
}
function Purchases({role}) {
  const {data:inventory,reload:reloadInventory}=useResource("/inventory"); const {data,error,busy,reload}=useResource("/purchases"); const [form,setForm]=useState({material_id:"",quantity:"",unit_rate:"",reference:"PUR-",batch_code:"",expiry_date:""}); const [notice,setNotice]=useState("");
  async function submit(e){e.preventDefault();try{const payload={...form,material_id:Number(form.material_id),quantity:Number(form.quantity),unit_rate:Number(form.unit_rate)};if(!payload.batch_code)delete payload.batch_code;if(!payload.expiry_date)delete payload.expiry_date;const {data:r}=await api.post("/purchases",payload);setNotice(`Purchase posted: ${money(r.total)}.`);reload();reloadInventory();}catch(x){setNotice(x.response?.data?.detail||"Purchase failed.");}}
  return <><PageIntro eyebrow="PROCUREMENT" title="Purchases" description="Record supplier receipts with optional batch and expiry details. All stock is posted through ledger movements."/><ErrorMessage>{error}</ErrorMessage>{role==="Admin"&&<form className="panel form-panel compact-form" onSubmit={submit}><h3>Record purchase</h3><div className="form-grid"><label>Material<select required value={form.material_id} onChange={e=>setForm({...form,material_id:e.target.value})}><option value="">Select material</option>{(inventory.materials||[]).map(m=><option key={m.id} value={m.id}>{m.name} ({m.unit})</option>)}</select></label><label>Quantity<input required type="number" min=".001" step=".001" value={form.quantity} onChange={e=>setForm({...form,quantity:e.target.value})}/></label><label>Unit rate<input required type="number" min="0" step=".01" value={form.unit_rate} onChange={e=>setForm({...form,unit_rate:e.target.value})}/></label><label>Reference<input required value={form.reference} onChange={e=>setForm({...form,reference:e.target.value})}/></label><label>Batch code (optional)<input maxLength="80" value={form.batch_code} onChange={e=>setForm({...form,batch_code:e.target.value})}/></label><label>Expiry date (requires batch code)<input type="date" value={form.expiry_date} onChange={e=>setForm({...form,expiry_date:e.target.value})}/></label><button className="primary">Post purchase</button></div>{notice&&<p className="inline-message">{notice}</p>}</form>}<section className="panel">{busy?<div className="loading-panel">Loading purchases…</div>:<DataTable columns={[{key:"reference",label:"Reference"},{key:"material",label:"Material"},{key:"quantity",label:"Quantity"},{key:"unit_rate",label:"Unit rate",render:money},{key:"total",label:"Total",render:money},{key:"created_at",label:"Date",render:v=>new Date(v).toLocaleDateString()}]} rows={data}/>}</section></>;
}
function Invoices({role}) {
  const {data,error,busy,reload}=useResource("/invoices"); const [notice,setNotice]=useState("");
  async function dispatch(row){try{const qty=prompt(`Quantity to dispatch (up to ${row.remaining ?? "invoice quantity"}):`);if(qty===null)return;const {data:r}=await api.post(`/invoices/${row.id}/dispatch`,{quantity:Number(qty)});setNotice(`Dispatch recorded. ${r.remaining} units remain.`);reload();}catch(x){setNotice(x.response?.data?.detail||"Dispatch failed.");}}
  async function pay(row){try{const amount=prompt(`Payment amount (outstanding ${money(row.outstanding)}):`);if(amount===null)return;const {data:r}=await api.post(`/invoices/${row.id}/payments`,{amount:Number(amount),reference:`PAY-${Date.now()}`});setNotice(`Payment recorded. Outstanding ${money(r.outstanding)}.`);reload();}catch(x){setNotice(x.response?.data?.detail||"Payment failed.");}}
  async function download(row){try{const result=await api.get(`/invoices/${row.id}/pdf`,{responseType:"blob"});const url=URL.createObjectURL(result.data);const a=document.createElement("a");a.href=url;a.download=`${row.number.replaceAll("/","-")}.pdf`;a.click();URL.revokeObjectURL(url);}catch(x){setNotice(x.response?.data?.detail||"PDF download failed.");}}
  return <><PageIntro eyebrow="GST COMPLIANCE" title="Invoices" description="Posted tax invoices, dispatches and receivables."/><ErrorMessage>{error}</ErrorMessage>{notice&&<p className="inline-message">{notice}</p>}<section className="panel">{busy?<div className="loading-panel">Loading invoices…</div>:<DataTable columns={[{key:"number",label:"Invoice"},{key:"customer",label:"Customer"},{key:"taxable",label:"Taxable",render:money},{key:"cgst",label:"CGST",render:money},{key:"sgst",label:"SGST",render:money},{key:"igst",label:"IGST",render:money},{key:"total",label:"Total",render:money},{key:"outstanding",label:"Due",render:v=><strong>{money(v)}</strong>},{key:"id",label:"Actions",render:(_,row)=><div className="row-actions"><button className="small-btn" onClick={()=>download(row)}>PDF</button>{role==="Admin"&&<button className="small-btn" onClick={()=>dispatch(row)}>Dispatch</button>}{role!=="Salesman"&&<button className="small-btn" onClick={()=>pay(row)}>Payment</button>}</div>}]} rows={data}/>}</section></>;
}
function Reports() {
  const {data,error,busy}=useResource("/reports/summary",{});
  const [exportName,setExportName]=useState("sales-register");
  const [exportFormat,setExportFormat]=useState("csv");
  const [fromDate,setFromDate]=useState("");
  const [toDate,setToDate]=useState("");
  const [exportError,setExportError]=useState("");
  const gst=data.gst_summary||{};
  async function exportReport(e) {
    e.preventDefault();setExportError("");
    try {
      const params=new URLSearchParams({format:exportFormat});
      if(fromDate)params.set("from_date",fromDate);
      if(toDate)params.set("to_date",toDate);
      const result=await api.get(`/reports/export/${exportName}?${params.toString()}`,{responseType:"blob"});
      const url=URL.createObjectURL(result.data);const a=document.createElement("a");
      a.href=url;a.download=`${exportName}.${exportFormat}`;a.click();URL.revokeObjectURL(url);
    } catch(x) { setExportError(x.response?.data?.detail||"Report export failed."); }
  }
  const ageing=Object.entries(data.receivables_ageing||{}).map(([bucket,amount])=>({bucket:bucket.replaceAll("_"," "),amount}));
  return <>
    <PageIntro eyebrow="FINANCE & AUDIT" title="Reports" description="Financial and production reporting based on posted business transactions."/>
    <ErrorMessage>{error}</ErrorMessage>
    <form className="export-toolbar" onSubmit={exportReport}>
      <label>Report<select value={exportName} onChange={e=>setExportName(e.target.value)}><option value="sales-register">Sales register</option><option value="stock-ledger">Stock movement ledger</option><option value="production">Production report</option><option value="receivables">Outstanding receivables</option></select></label>
      <label>Format<select value={exportFormat} onChange={e=>setExportFormat(e.target.value)}><option value="csv">CSV</option><option value="xlsx">Excel</option><option value="pdf">PDF</option></select></label>
      <label>From<input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/></label>
      <label>To<input type="date" value={toDate} onChange={e=>setToDate(e.target.value)}/></label>
      <button className="primary">Export report</button>
    </form>
    <ErrorMessage>{exportError}</ErrorMessage>
    {busy?<div className="loading-panel">Loading reports…</div>:<>
      <div className="stat-grid"><StatCard title="Taxable sales" value={money(gst.taxable)} detail="From invoices" icon={CircleDollarSign}/><StatCard title="CGST collected" value={money(gst.cgst)} detail="Posted invoice tax" icon={FileText} tone="blue"/><StatCard title="SGST collected" value={money(gst.sgst)} detail="Posted invoice tax" icon={FileText} tone="blue"/><StatCard title="IGST collected" value={money(gst.igst)} detail="Posted invoice tax" icon={ArrowDownToLine} tone="amber"/></div>
      <div className="dashboard-grid">
        <section className="panel"><div className="panel-heading"><div><h3>Sales register</h3><p>Invoice-level totals</p></div></div><DataTable columns={[{key:"invoice",label:"Invoice"},{key:"customer",label:"Customer"},{key:"taxable",label:"Taxable",render:money},{key:"gst",label:"GST",render:money},{key:"total",label:"Total",render:money}]} rows={data.sales_register||[]}/></section>
        <section className="panel"><div className="panel-heading"><div><h3>Outstanding receivables</h3><p>Invoice balances after payments</p></div></div><DataTable columns={[{key:"invoice",label:"Invoice"},{key:"customer",label:"Customer"},{key:"amount",label:"Due",render:money}]} rows={data.receivables||[]}/></section>
      </div>
      <section className="panel"><div className="panel-heading"><div><h3>Production yield report</h3><p>Good output against expected batch output</p></div></div><DataTable columns={[{key:"reference",label:"Batch"},{key:"expected",label:"Expected"},{key:"good_output",label:"Good output"},{key:"damaged",label:"Damaged"},{key:"yield_variance_percent",label:"Yield variance",render:v=><span className={Number(v)<-3?"warning-text":""}>{v}%</span>}]} rows={data.production||[]}/></section>
      <div className="dashboard-grid">
        <section className="panel"><div className="panel-heading"><div><h3>Cost per good packet</h3><p>Weighted-average material valuation plus batch overhead</p></div></div><DataTable columns={[{key:"reference",label:"Batch"},{key:"good_output",label:"Good output"},{key:"raw_material_cost",label:"Materials",render:money},{key:"overhead_cost",label:"Overhead",render:money},{key:"cost_per_packet",label:"Per packet",render:money}]} rows={data.cost_per_packet||[]}/></section>
        <section className="panel"><div className="panel-heading"><div><h3>Receivables ageing</h3><p>Outstanding by days since invoice</p></div></div><DataTable columns={[{key:"bucket",label:"Age bucket"},{key:"amount",label:"Outstanding",render:money}]} rows={ageing}/></section>
      </div>
      <section className="panel"><div className="panel-heading"><div><h3>Purchase register</h3><p>Receipts and invoice values</p></div></div><DataTable columns={[{key:"reference",label:"Reference"},{key:"material",label:"Material"},{key:"quantity",label:"Quantity"},{key:"unit_rate",label:"Rate",render:money},{key:"total",label:"Total",render:money}]} rows={data.purchase_register||[]}/></section>
    </>}
  </>;
}

export default App;
