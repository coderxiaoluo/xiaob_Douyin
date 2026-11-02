(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  const MODULE_FIELDS = {
    search_work: [
      { name: "query", label: "关键词", type: "text", required: true, placeholder: "例如：街头美食", row: "primary" },
      { name: "require_num", label: "数量", type: "number", value: 12, row: "primary" },
      { name: "sort_type", label: "排序", type: "select", options: [["0", "综合"], ["1", "最多点赞"], ["2", "最新发布"]], row: "primary" },
      { name: "publish_time", label: "时间", type: "select", options: [["0", "不限"], ["1", "一天内"], ["7", "一周内"], ["180", "半年内"]], row: "secondary" },
      { name: "filter_duration", label: "时长", type: "select", options: [["", "不限"], ["0-1", "1分钟内"], ["1-5", "1-5分钟"], ["5-10000", "5分钟以上"]], row: "secondary" },
      { name: "content_type", label: "类型", type: "select", options: [["0", "不限"], ["1", "视频"], ["2", "图文"]], row: "secondary" },
    ],
    search_user: [
      { name: "query", label: "关键词", type: "text", required: true },
      { name: "require_num", label: "数量", type: "number", value: 12 },
    ],
    search_live: [
      { name: "query", label: "关键词", type: "text", required: true },
      { name: "require_num", label: "数量", type: "number", value: 12 },
    ],
    user_works: [
      { name: "user_url", label: "用户主页链接", type: "text", required: true, placeholder: "https://www.douyin.com/user/MS4w…" },
    ],
    user_profile: [
      { name: "user_url", label: "用户主页链接", type: "text", required: true },
    ],
    followers: [
      { name: "user_url", label: "用户主页链接", type: "text", required: true },
      { name: "require_num", label: "数量", type: "number", value: 20 },
    ],
    following: [
      { name: "user_url", label: "用户主页链接", type: "text", required: true },
      { name: "require_num", label: "数量", type: "number", value: 20 },
    ],
    work_detail: [
      { name: "work_url", label: "作品链接", type: "text", required: true, placeholder: "https://www.douyin.com/video/…" },
    ],
    comments: [
      { name: "work_url", label: "作品链接", type: "text", required: true },
    ],
    work_urls: [
      { name: "urls", label: "作品链接（每行一条）", type: "textarea", required: true },
      { name: "excel_name", label: "默认文件名", type: "text", value: "works" },
    ],
    favorites: [
      { name: "user_url", label: "用户链接（空=我的收藏夹）", type: "text", placeholder: "可留空" },
      { name: "require_num", label: "作品数量上限", type: "number", value: 30 },
    ],
    feed: [
      { name: "require_num", label: "数量", type: "number", value: 20 },
    ],
    notices: [
      { name: "require_num", label: "数量", type: "number", value: 20 },
      { name: "notice_group", label: "类型", type: "select", options: [
        ["700", "全部"], ["401", "粉丝"], ["601", "@我"], ["2", "评论"], ["3", "点赞"], ["520", "弹幕"],
      ] },
    ],
  };

  let modules = [];
  let currentModule = "search_work";
  let pollTimer = null;
  let currentScanJobId = "";
  let currentKind = "work";
  let viewMode = "work"; // work | config
  let lastWorkUrl = ""; // 评论区发表/回复时回填目标作品
  const actionState = new Map(); // "digg:123" / "collect:123" -> "0" | "1"

  function escapeHtml(s) {
    return String(s || "").replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
  }
  function fmtNum(n) {
    const x = Number(n) || 0;
    if (x >= 10000) return (x / 10000).toFixed(1).replace(/\.0$/, "") + "万";
    return String(x);
  }
  function fmtTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * (ts > 1e12 ? 1 : 1000));
    return d.toLocaleString("zh-CN", { hour12: false });
  }
  function fmtCardTime(ts) {
    const n = Number(ts);
    if (!n) return "";
    const d = new Date(n > 1e12 ? n : n * 1000);
    if (Number.isNaN(d.getTime())) return "";
    const p = (x) => String(x).padStart(2, "0");
    return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  function fieldClass(f) {
    if (f.type === "textarea") return "field-wide";
    if (f.type === "number") return "field-sm";
    if (f.type === "select") return "field-md";
    if (["query", "user_url", "work_url"].includes(f.name)) return "field-grow";
    return "field-grow";
  }

  function fieldHtml(f) {
    const cls = fieldClass(f);
    if (f.type === "textarea") {
      return `<label class="${cls}"><span>${f.label}</span>
        <textarea name="${f.name}" ${f.required ? "required" : ""} placeholder="${f.placeholder || ""}"></textarea></label>`;
    }
    if (f.type === "select") {
      const opts = (f.options || []).map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
      return `<label class="${cls}"><span>${f.label}</span><select name="${f.name}">${opts}</select></label>`;
    }
    return `<label class="${cls}"><span>${f.label}</span>
      <input name="${f.name}" type="${f.type || "text"}" ${f.required ? "required" : ""}
        value="${f.value ?? ""}" placeholder="${f.placeholder || ""}"
        ${f.type === "number" ? 'min="1" max="100"' : ""} /></label>`;
  }

  function renderFields() {
    const fields = MODULE_FIELDS[currentModule] || [];
    const primary = fields.filter((f) => (f.row || "primary") === "primary");
    const secondary = fields.filter((f) => f.row === "secondary");
    const primaryEl = $("#fieldsPrimary");
    const secondaryEl = $("#fieldsSecondary");
    const secondaryWrap = $("#querySecondary");
    if (primaryEl) primaryEl.innerHTML = primary.map(fieldHtml).join("");
    if (secondaryEl) secondaryEl.innerHTML = secondary.map(fieldHtml).join("");
    if (secondaryWrap) secondaryWrap.hidden = secondary.length === 0;
    // 同步到隐藏 #fields，兼容旧表单序列化（实际上 serialize 用 taskForm 内 name）
    const all = $("#fields");
    if (all) all.innerHTML = "";
  }

  function renderNav() {
    const groups = {};
    modules.forEach((m) => { (groups[m.group] ||= []).push(m); });
    $("#moduleNav").innerHTML = Object.entries(groups)
      .map(([group, items]) => {
        const btns = items
          .map((m) => `<button type="button" data-id="${m.id}" class="${m.id === currentModule ? "active" : ""}">
            <span class="nav-label">${m.label}</span>
          </button>`)
          .join("");
        return `<div class="nav-group"><div class="nav-group-title">${group}</div>${btns}</div>`;
      })
      .join("");
    $$("#moduleNav button").forEach((btn) => {
      btn.addEventListener("click", () => selectModule(btn.dataset.id));
    });
  }

  function selectModule(id) {
    currentModule = id;
    const meta = modules.find((m) => m.id === id) || {};
    $("#moduleTitle").textContent = meta.label || id;
    $("#moduleDesc").textContent = meta.desc || "";
    if (meta.view === "live") showLiveView();
    else showWorkView();
    renderNav();
    if (meta.view !== "live") renderFields();
  }

  function clearSideNavActive() {
    $("#configNavBtn")?.classList.remove("active");
    $("#agentNavBtn")?.classList.remove("active");
    $("#archiveNavBtn")?.classList.remove("active");
    $("#createNavBtn")?.classList.remove("active");
  }

  function hideAllViews() {
    $("#workView").hidden = true;
    $("#configView").hidden = true;
    $("#agentView").hidden = true;
    $("#liveView").hidden = true;
    $("#createView").hidden = true;
    const archive = $("#archiveView");
    if (archive) archive.hidden = true;
  }

  function showWorkView() {
    viewMode = "work";
    hideAllViews();
    $("#workView").hidden = false;
    clearSideNavActive();
    stopLivePoll();
    renderNav();
  }

  function openLowfreqNav() {
    const box = $("#sidebarLowfreq");
    if (box) box.open = true;
  }

  function showArchiveView() {
    viewMode = "archive";
    hideAllViews();
    $("#archiveView").hidden = false;
    clearSideNavActive();
    $("#archiveNavBtn")?.classList.add("active");
    $$("#moduleNav button").forEach((b) => b.classList.remove("active"));
    $("#moduleTitle").textContent = "本地档案";
    $("#moduleDesc").textContent = "已导出文件 · 点击下载";
    stopLivePoll();
    refreshStatus().catch(() => {});
  }

  function showConfigView() {
    viewMode = "config";
    hideAllViews();
    $("#configView").hidden = false;
    clearSideNavActive();
    $("#configNavBtn").classList.add("active");
    $$("#moduleNav button").forEach((b) => b.classList.remove("active"));
    $("#moduleTitle").textContent = "会话配置";
    $("#moduleDesc").textContent = "Cookie、扫码登录、代理";
    openLowfreqNav();
    stopLivePoll();
    loadConfig().catch((e) => showCfgMsg(e.message || String(e), false));
  }

  function showAgentView() {
    viewMode = "agent";
    hideAllViews();
    $("#agentView").hidden = false;
    clearSideNavActive();
    $("#agentNavBtn").classList.add("active");
    $$("#moduleNav button").forEach((b) => b.classList.remove("active"));
    $("#moduleTitle").textContent = "Agent 配置";
    $("#moduleDesc").textContent = "填目标 → 开能力 → 预览计划 → 保存（暂不执行）";
    openLowfreqNav();
    stopLivePoll();
    loadAgent().catch((e) => showAgentMsg(e.message || String(e), false));
  }

  function showCreateView() {
    viewMode = "create";
    hideAllViews();
    $("#createView").hidden = false;
    clearSideNavActive();
    $("#createNavBtn")?.classList.add("active");
    $$("#moduleNav button").forEach((b) => b.classList.remove("active"));
    $("#moduleTitle").textContent = "私信 / 发布";
    $("#moduleDesc").textContent = "建会话发私信 · STS 上传发布视频 · 素材库";
    stopLivePoll();
    toggleDmKind();
    loadMedia(true).catch((err) => createMsg("mediaMsg", err.message || String(err), false));
  }

  const AGENT_TOOLS = ["gen_video", "gen_cover", "publish_video", "comment", "hot_reply", "dm_reply"];

  function showAgentMsg(text, ok) {
    const el = document.getElementById("agentMsg");
    if (!el) return;
    el.hidden = !text;
    el.textContent = text || "";
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("err", !ok);
  }

  function agentEl(id) {
    return document.getElementById(id);
  }

  function setAgentField(id, value, asCheck = false) {
    const el = agentEl(id);
    if (!el) return false;
    if (asCheck) el.checked = !!value;
    else el.value = value ?? "";
    return true;
  }

  function getAgentField(id, fallback = "") {
    const el = agentEl(id);
    if (!el) return fallback;
    return el.type === "checkbox" ? el.checked : el.value;
  }

  function fillAgent(agent = {}) {
    const goal = agent.goal || {};
    const persona = agent.persona || {};
    const tools = agent.tools || {};
    const quotas = agent.quotas || {};
    const safety = agent.safety || {};
    setAgentField("agentEnabled", !!agent.enabled, true);
    setAgentField("agentCategory", goal.category || "");
    setAgentField("agentDailyVideos", goal.daily_videos ?? 1);
    setAgentField("agentFunnel", goal.funnel || "comment");
    setAgentField("agentBrief", goal.brief || "");
    setAgentField("agentTone", persona.tone || "轻松专业");
    setAgentField("agentForbidden", persona.forbidden || "");
    for (const key of AGENT_TOOLS) {
      setAgentField("tool_" + key, tools[key] === true, true);
    }
    const engage = agent.engage || {};
    setAgentField("agentMaxPublish", quotas.max_publish_per_day ?? 3);
    setAgentField("agentMaxComments", quotas.max_comments_per_day ?? 20);
    setAgentField("agentMaxDm", quotas.max_dm_per_day ?? 10);
    setAgentField("agentMinInterval", quotas.min_action_interval_sec ?? 180);
    setAgentField("agentWorkMinDigg", engage.work_min_digg ?? 0);
    setAgentField("agentCommentMinDigg", engage.comment_min_digg ?? 0);
    setAgentField("agentCommentKeyword", engage.comment_keyword || "");
    setAgentField("agentCommentExclude", engage.comment_exclude || "");
    setAgentField("agentMaxCommentsPerWork", engage.max_comments_per_work ?? 5);
    setAgentField("agentIntentOnly", engage.intent_only === true, true);
    setAgentField("agentManualConfirm", safety.require_manual_confirm !== false, true);
    setAgentField("agentSensitiveCheck", safety.sensitive_word_check !== false, true);
    setAgentField("agentCoolDown", safety.cooldown_after_errors ?? 3);
  }

  function readAgent() {
    const tools = {};
    for (const key of AGENT_TOOLS) tools[key] = !!getAgentField("tool_" + key, false);
    return {
      enabled: !!getAgentField("agentEnabled", false),
      goal: {
        category: String(getAgentField("agentCategory", "")).trim(),
        daily_videos: Number(getAgentField("agentDailyVideos", 1)),
        funnel: String(getAgentField("agentFunnel", "comment")),
        brief: String(getAgentField("agentBrief", "")).trim(),
      },
      persona: {
        tone: String(getAgentField("agentTone", "")).trim() || "轻松专业",
        forbidden: String(getAgentField("agentForbidden", "")).trim(),
      },
      tools,
      quotas: {
        max_publish_per_day: Number(getAgentField("agentMaxPublish", 3)),
        max_comments_per_day: Number(getAgentField("agentMaxComments", 20)),
        max_dm_per_day: Number(getAgentField("agentMaxDm", 10)),
        min_action_interval_sec: Number(getAgentField("agentMinInterval", 180)),
      },
      engage: {
        work_min_digg: Number(getAgentField("agentWorkMinDigg", 0)),
        comment_min_digg: Number(getAgentField("agentCommentMinDigg", 0)),
        comment_keyword: String(getAgentField("agentCommentKeyword", "")).trim(),
        comment_exclude: String(getAgentField("agentCommentExclude", "")).trim(),
        max_comments_per_work: Number(getAgentField("agentMaxCommentsPerWork", 5)),
        intent_only: !!getAgentField("agentIntentOnly", false),
      },
      safety: {
        require_manual_confirm: !!getAgentField("agentManualConfirm", true),
        sensitive_word_check: !!getAgentField("agentSensitiveCheck", true),
        cooldown_after_errors: Number(getAgentField("agentCoolDown", 3)),
      },
    };
  }

  const PLAN_STATUS = {
    ready: "可执行",
    needs_confirm: "需确认",
    blocked: "已阻断",
    pending: "待定",
    approved: "已批准",
    rejected: "已拒绝",
  };
  const QUEUE_STATUS = {
    pending: "待确认",
    approved: "已批准",
    rejected: "已拒绝",
  };

  function renderPlan(plan) {
    const summary = $("#agentPlanSummary");
    const warnings = $("#agentPlanWarnings");
    const steps = $("#agentPlanSteps");
    const empty = $("#agentPlanEmpty");
    const lead = $("#agentPlanLead");
    if (!summary || !steps) return;
    if (!plan) {
      summary.textContent = "—";
      steps.innerHTML = "";
      if (warnings) { warnings.hidden = true; warnings.innerHTML = ""; }
      if (empty) empty.hidden = false;
      if (lead) lead.textContent = "保存或点「预览计划」后，这里显示只读步骤（不会执行）。";
      return;
    }
    const stats = plan.stats || {};
    summary.textContent = plan.summary || "—";
    if (lead) {
      lead.textContent =
        `预览 · ${stats.total || 0} 步 · 待确认 ${stats.needs_confirm || 0}` +
        ` · 已批准 ${stats.approved || 0} · 阻断 ${stats.blocked || 0}`;
    }
    const warns = plan.warnings || [];
    if (warnings) {
      warnings.innerHTML = warns.map((w) => `<li>${escapeHtml(w)}</li>`).join("");
      warnings.hidden = !warns.length;
    }
    const rows = plan.steps || [];
    steps.innerHTML = rows.map((step, i) => {
      const status = step.status || "pending";
      const count = step.count != null ? ` ×${step.count}` : "";
      return `<li class="is-${escapeHtml(status)}">
        <div class="step-top">
          <span class="step-title">${i + 1}. ${escapeHtml(step.title || step.tool || "步骤")}${count}</span>
          <span class="step-status">${escapeHtml(PLAN_STATUS[status] || status)}</span>
        </div>
        <p class="step-desc">${escapeHtml(step.description || "")}</p>
        ${step.note ? `<p class="step-note">${escapeHtml(step.note)}</p>` : ""}
      </li>`;
    }).join("");
    if (empty) empty.hidden = rows.length > 0;
  }

  function renderWorkerResult(item) {
    const status = item.worker_status || "";
    if (!status) return "";
    if (status === "error") {
      return `<div class="agent-worker-result"><p class="wr-err">准备失败：${escapeHtml(item.worker_error || "未知错误")}</p></div>`;
    }
    const result = item.worker_result || {};
    const filters = result.filters || {};
    const works = result.works || [];
    const comments = result.comments || [];
    const msg = result.message || (status === "prepared" ? "只读准备完成" : "已跳过");
    const canSelect = status === "prepared" && item.status === "approved";
    const workLines = works.slice(0, 12).map((w) => {
      const id = String(w.work_id || "");
      const out = w.filtered_out ? " is-filtered" : "";
      const checked = w.selected && !w.filtered_out ? " checked" : "";
      const disabled = w.filtered_out || !canSelect ? " disabled" : "";
      return `<li class="${out}">
        <label class="wr-pick">
          <input type="checkbox" data-pick-work value="${escapeHtml(id)}"${checked}${disabled} />
          <span>${escapeHtml((w.title || id || "作品").slice(0, 36))} · @${escapeHtml(w.nickname || "")} · 赞 ${fmtNum(w.digg_count)}</span>
        </label>
      </li>`;
    }).join("");
    const commentLines = comments.slice(0, 20).map((c) => {
      const cid = String(c.cid || "");
      const out = c.filtered_out ? " is-filtered" : "";
      const checked = c.selected && !c.filtered_out ? " checked" : "";
      const disabled = c.filtered_out || !canSelect ? " disabled" : "";
      const intent = c.is_intent ? " · 意向" : "";
      return `<li class="${out}">
        <label class="wr-pick">
          <input type="checkbox" data-pick-comment value="${escapeHtml(cid)}"${checked}${disabled} />
          <span>${escapeHtml((c.text || "").slice(0, 40))} · @${escapeHtml(c.nickname || "")} · 赞 ${fmtNum(c.digg_count)}${intent}</span>
        </label>
      </li>`;
    }).join("");
    const draft = item.write_draft || {};
    const drafts = draft.drafts || [];
    const draftLines = drafts.slice(0, 8).map((d) =>
      `<li class="${d.blocked ? "is-blocked" : ""}">${escapeHtml((d.content || "").slice(0, 60))}${
        d.blocked ? " · 禁区" : ""
      } · ${escapeHtml(d.work_id || "")}</li>`).join("");
    const writeRes = item.write_result || {};
    const writeMsg = writeRes.message || (item.write_status === "error" ? (item.write_error || "写操作失败") : "");
    const filterBar = canSelect ? `<div class="wr-filters" data-item-id="${escapeHtml(item.id)}">
        <label>作品最低赞 <input type="number" min="0" data-f-work-digg value="${escapeHtml(String(filters.work_min_digg ?? 0))}" /></label>
        <label>评论最低赞 <input type="number" min="0" data-f-comment-digg value="${escapeHtml(String(filters.comment_min_digg ?? 0))}" /></label>
        <label>含关键词 <input type="text" maxlength="64" data-f-keyword value="${escapeHtml(filters.comment_keyword || "")}" placeholder="可选" /></label>
        <label>排除词 <input type="text" maxlength="64" data-f-exclude value="${escapeHtml(filters.comment_exclude || "")}" placeholder="可选" /></label>
        <label class="inline-check"><input type="checkbox" data-f-intent-only ${filters.intent_only ? "checked" : ""} /><span>仅意向</span></label>
        <button type="button" class="btn btn-secondary" data-apply-select="${escapeHtml(item.id)}">应用筛选</button>
      </div>` : "";
    return `<div class="agent-worker-result" data-result-item="${escapeHtml(item.id)}">
      <p class="wr-msg">${escapeHtml(msg)}</p>
      ${filterBar}
      ${workLines ? `<p class="wr-label">相关作品（勾选参与草稿）</p><ul class="wr-list wr-select">${workLines}</ul>` : ""}
      ${commentLines ? `<p class="wr-label">评论候选（勾选后用于热评回复；不是你要发的正文）</p><ul class="wr-list wr-select">${commentLines}</ul>` : ""}
      ${draftLines ? `<p class="wr-label">待发草稿</p><ul class="wr-list">${draftLines}</ul>` : ""}
      ${writeMsg ? `<p class="wr-msg">${escapeHtml(writeMsg)}</p>` : ""}
      ${item.write_status === "error" && item.write_error ? `<p class="wr-err">${escapeHtml(item.write_error)}</p>` : ""}
    </div>`;
  }

  function renderQueue(queue) {
    const list = $("#agentQueueList");
    const empty = $("#agentQueueEmpty");
    const count = $("#agentQueueCount");
    if (!list) return;
    const items = (queue && queue.items) || [];
    const pending = (queue && queue.pending) || items.filter((i) => i.status === "pending");
    const approved = items.filter((i) => i.status === "approved").length;
    if (count) count.textContent = `待确认 ${pending.length} · 已批准 ${approved}`;
    list.innerHTML = items.slice(0, 20).map((item) => {
      const status = item.status || "pending";
      const countText = item.count != null ? ` ×${item.count}` : "";
      const actions = status === "pending"
        ? `<div class="agent-queue-actions">
            <button type="button" class="btn btn-primary" data-queue-action="approve" data-queue-id="${escapeHtml(item.id)}">批准</button>
            <button type="button" class="btn btn-secondary" data-queue-action="reject" data-queue-id="${escapeHtml(item.id)}">拒绝</button>
          </div>`
        : (status === "approved" && item.worker_status !== "prepared"
          ? `<div class="agent-queue-actions">
              <button type="button" class="btn btn-secondary" data-worker-id="${escapeHtml(item.id)}">只读准备此项</button>
            </div>`
          : (status === "approved" && item.worker_status === "prepared" && item.write_status !== "drafted" && item.write_status !== "done"
            ? `<div class="agent-queue-actions">
                <button type="button" class="btn btn-secondary" data-draft-id="${escapeHtml(item.id)}">生成草稿</button>
              </div>`
            : (status === "approved" && item.write_status === "drafted"
              ? `<div class="agent-queue-actions">
                  <button type="button" class="btn btn-primary" data-write-id="${escapeHtml(item.id)}">执行评论</button>
                </div>`
              : "")));
      const prepTag = item.worker_status === "prepared" ? " · 已准备" : "";
      const writeTag = item.write_status === "drafted" ? " · 有草稿"
        : (item.write_status === "done" ? " · 已执行" : (item.write_status === "error" ? " · 写失败" : ""));
      return `<li class="is-${escapeHtml(status)}">
        <div class="queue-top">
          <span class="queue-title">${escapeHtml(item.title || item.tool || "条目")}${countText}</span>
          <span class="queue-status">${escapeHtml(QUEUE_STATUS[status] || status)}${prepTag}${writeTag}</span>
        </div>
        <p class="queue-desc">${escapeHtml(item.description || item.plan_summary || "")}</p>
        ${actions}
        ${renderWorkerResult(item)}
      </li>`;
    }).join("");
    if (empty) empty.hidden = items.length > 0;
  }

  async function runWorkerWrite(action, itemId = "", dryRun = false) {
    const res = await fetch("/api/agent/worker/write", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        item_id: itemId || "",
        dry_run: !!dryRun,
      }),
    });
    let data = {};
    try { data = await res.json(); } catch { /* ignore */ }
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : "写操作失败"));
    }
    renderPlan(data.plan);
    renderQueue(data.queue);
    return data;
  }

  async function runWorkerPrep(itemId = "") {
    const res = await fetch("/api/agent/worker/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId || "" }),
    });
    let data = {};
    try { data = await res.json(); } catch { /* ignore */ }
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : "只读准备失败"));
    }
    renderPlan(data.plan);
    renderQueue(data.queue);
    return data;
  }

  async function loadAgent() {
    const res = await fetch("/api/agent");
    let data = {};
    try { data = await res.json(); } catch { /* ignore */ }
    if (!res.ok) {
      if (res.status === 404) throw new Error("接口未找到：请重启工作台后再试");
      throw new Error(data.detail || "读取 Agent 配置失败");
    }
    fillAgent(data.agent || {});
    renderPlan(data.plan);
    renderQueue(data.queue);
    const path = agentEl("agentPath");
    if (path) path.textContent = data.path || "—";
    showAgentMsg("", true);
  }

  async function previewAgentPlan() {
    const res = await fetch("/api/agent/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readAgent()),
    });
    let data = {};
    try { data = await res.json(); } catch { /* ignore */ }
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : "预览失败"));
    }
    renderPlan(data.plan);
    renderQueue(data.queue);
    return data.plan;
  }

  async function decideQueueItem(id, action) {
    const res = await fetch(`/api/agent/queue/${encodeURIComponent(id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    let data = {};
    try { data = await res.json(); } catch { /* ignore */ }
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : "处理失败"));
    }
    renderPlan(data.plan);
    renderQueue(data.queue);
    return data;
  }

  function showCfgMsg(text, ok) {
    const el = $("#cfgMsg");
    el.hidden = !text;
    el.textContent = text || "";
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("err", !ok);
  }

  function fillFpForm(fp = {}) {
    if (fp.ua) $("#cfgUa").value = fp.ua;
    if (fp.browser_version) $("#cfgBrowserVersion").value = fp.browser_version;
    if (fp.engine_version) $("#cfgEngineVersion").value = fp.engine_version;
    if (fp.accept_language) $("#cfgAcceptLanguage").value = fp.accept_language;
    if (fp.screen_width) $("#cfgScreenWidth").value = fp.screen_width;
    if (fp.screen_height) $("#cfgScreenHeight").value = fp.screen_height;
    if (fp.cpu_core_num) $("#cfgCpu").value = fp.cpu_core_num;
    if (fp.device_memory) $("#cfgMemory").value = fp.device_memory;
  }

  function applyParsed(parsed = {}) {
    if (parsed.cookies) $("#cfgCookies").value = parsed.cookies;
    fillFpForm({
      ua: parsed.ua,
      browser_version: parsed.browser_version,
      engine_version: parsed.engine_version || parsed.browser_version,
      accept_language: parsed.accept_language,
      screen_width: parsed.screen_width,
      screen_height: parsed.screen_height,
      cpu_core_num: parsed.cpu_core_num,
      device_memory: parsed.device_memory,
    });
  }

  function renderConfigStatus(data) {
    $("#cfgHasCookies").textContent = data.has_cookies
      ? `已配置 · ${data.cookie_length} 字符`
      : "未配置";
    $("#cfgHasSession").textContent = data.has_sessionid
      ? `有 · ${data.sessionid_preview || ""}`
      : "无";
    $("#cfgHasTtwid").textContent = data.has_ttwid ? "有" : "无";
    $("#cfgHasUifid").textContent = data.has_uifid ? "有" : "无";
    $("#cfgEnvPath").textContent = data.env_path || "—";
    $("#cfgProxyState").textContent = data.proxy ? data.proxy : "直连";
    if (data.proxy) $("#cfgProxy").value = data.proxy;
    fillFpForm(data.fp || {});
  }

  async function loadConfig() {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "读取配置失败");
    renderConfigStatus(data);
    showCfgMsg("", true);
  }

  async function refreshStatus() {
    const res = await fetch("/api/status");
    const data = await res.json();
    modules = data.modules || [];
    renderNav();
    if (!$("#fieldsPrimary")?.children.length) selectModule(currentModule);
    $("#sessionDot").className = "dot " + (data.logged_in ? "on" : "off");
    $("#sessionText").textContent = data.ok
      ? (data.logged_in
        ? `会话有效 · uid ${data.uid || "—"}`
        : "未检测到 sessionid")
      : (data.error || "初始化失败");
    $("#sessionText").title = data.logged_in
      ? "能取到 uid 不等于搜作品可用；若搜索报 2483，请从浏览器搜索请求重贴 Cookie"
      : "";
    {
      const pathInfo = shortPath(data.excel_dir || "");
      const dirEl = $("#excelDir");
      if (dirEl) {
        dirEl.textContent = pathInfo.full || pathInfo.short;
        dirEl.title = pathInfo.full || "";
      }
    }
    const files = (data.excels || []).filter(
      (f) => f.name && !String(f.name).startsWith("~$") && !String(f.name).startsWith(".")
    );
    $("#excelCount").textContent = String(files.length);
    const countLabel = $("#excelCountLabel");
    if (countLabel) countLabel.textContent = String(files.length);
    const listEl = $("#excelList");
    const emptyEl = $("#archiveEmpty");
    if (listEl) {
      listEl.innerHTML = files.length
        ? files
            .map(
              (f, i) => `<li style="--i:${i}">
          <a class="archive-file-card" href="/api/excels/${encodeURIComponent(f.name)}" download>
            <span class="archive-file-ext">${escapeHtml((f.name.split(".").pop() || "file").toUpperCase())}</span>
            <span class="file-body">
              <span class="file-name">${escapeHtml(f.name)}</span>
              <span class="file-meta">${fmtTime(f.mtime)} · ${(f.size / 1024).toFixed(1)} KB</span>
            </span>
            <span class="archive-file-action">下载 <span class="arrow" aria-hidden="true">→</span></span>
          </a>
        </li>`
            )
            .join("")
        : "";
    }
    if (emptyEl) emptyEl.hidden = files.length > 0;
  }

  function getSaveChoice() {
    const sel = $("#saveChoiceSelect");
    if (sel && sel.value) return sel.value;
    const el = document.querySelector('input[name="saveChoice"]:checked');
    return el ? el.value : "all";
  }

  function setSaveChoice(value) {
    const sel = $("#saveChoiceSelect");
    if (sel) {
      sel.value = value;
      return;
    }
    const el = document.querySelector(`input[name="saveChoice"][value="${value}"]`);
    if (el) el.checked = true;
  }

  function shortPath(full) {
    const raw = String(full || "").trim();
    if (!raw) return { short: "—", full: "" };
    const parts = raw.replace(/[\\/]+$/, "").split(/[\\/]/);
    const name = parts[parts.length - 1] || raw;
    return { short: name, full: raw };
  }

  function syncCardSelected(input) {
    const card = input.closest(".card");
    if (card) card.classList.toggle("is-selected", input.checked);
  }

  function selectedIds() {
    return $$(".card-check:checked").map((el) => el.value);
  }

  function updateSelectedCount() {
    const boxes = $$(".card-check");
    boxes.forEach(syncCardSelected);
    const n = selectedIds().length;
    $("#selectedCount").textContent = `已选 ${n}`;
    $("#checkAll").checked = boxes.length > 0 && n === boxes.length;
    $("#checkAll").indeterminate = n > 0 && n < boxes.length;
  }

  function pickHtml(id) {
    return `<label class="pick" title="选择">
      <input class="card-check" type="checkbox" value="${id}" checked />
      <span class="visually-hidden">选择</span>
    </label>`;
  }

  function mediaUrl(url) {
    return String(url || "").trim();
  }

  function coverImgHtml(rawUrl) {
    const raw = mediaUrl(rawUrl);
    if (!raw) return "";
    const safe = escapeHtml(raw);
    const proxied = `/api/cover?u=${encodeURIComponent(raw)}`;
    return `<img class="cover-img" src="${safe}" data-proxy="${escapeHtml(proxied)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="if(this.dataset.proxy&&this.src!==this.dataset.proxy){this.src=this.dataset.proxy;return;}this.classList.add('is-broken');" />`;
  }

  function cardHtml(item, i) {
    const rawId = String(item.id || item.work_id || i);
    const id = escapeHtml(rawId);
    const diggOn = actionState.get(`digg:${rawId}`) === "1";
    const collectOn = actionState.get(`collect:${rawId}`) === "1";
    const kind = item.kind || currentKind;
    const time = fmtCardTime(item.create_time);
    if (kind === "work") {
      const url = escapeHtml(item.work_url || "#");
      const title = item.title || "无标题";
      const tip = escapeHtml([
        title,
        item.nickname ? `@${item.nickname}` : "",
        time || "",
      ].filter(Boolean).join(" · "));
      const avatar = mediaUrl(item.author_avatar);
      const typeLabel = item.work_type && item.work_type !== "未知" ? item.work_type : "作品";
      const avatarHtml = avatar
        ? `<span class="card-avatar" style="background-image:url('${escapeHtml(avatar)}')"></span>`
        : `<span class="card-avatar card-avatar-empty" aria-hidden="true"></span>`;
      return `<article class="card card-work is-selected" style="--i:${i}" title="${tip}">
        ${pickHtml(id)}
        <a class="cover" href="${url}" target="_blank" rel="noopener" title="打开作品">
          ${coverImgHtml(item.video_cover)}
          <span class="cover-fallback" aria-hidden="true">${escapeHtml(typeLabel)}</span>
          <span class="cover-shine" aria-hidden="true"></span>
          <span class="cover-tag">${escapeHtml(typeLabel)}</span>
        </a>
        <div class="meta">
          <h3>${escapeHtml(title)}</h3>
          <div class="card-user">
            ${avatarHtml}
            <span class="card-author">${item.nickname ? "@" + escapeHtml(item.nickname) : "未知作者"}</span>
          </div>
          <div class="card-stats">
            <span title="点赞">赞 ${fmtNum(item.digg_count)}</span>
            <span title="评论">评 ${fmtNum(item.comment_count)}</span>
            <span title="收藏">藏 ${fmtNum(item.collect_count)}</span>
            <span title="分享">转 ${fmtNum(item.share_count)}</span>
          </div>
          <div class="card-actions">
            <button type="button" class="chip-action${diggOn ? " is-on" : ""}" data-act="digg" data-aweme="${id}" data-on="${diggOn ? "1" : "0"}" aria-pressed="${diggOn}">${diggOn ? "已赞" : "点赞"}</button>
            <button type="button" class="chip-action${collectOn ? " is-on" : ""}" data-act="collect" data-aweme="${id}" data-on="${collectOn ? "1" : "0"}" aria-pressed="${collectOn}">${collectOn ? "已藏" : "收藏"}</button>
          </div>
          ${time ? `<time class="card-time" datetime="${escapeHtml(String(item.create_time))}">${escapeHtml(time)}</time>` : ""}
        </div>
      </article>`;
    }
    if (kind === "user") {
      return `<article class="card card-user is-selected">
        ${pickHtml(id)}
        <div class="user-row">
          <div class="avatar" style="background-image:url('${escapeHtml(item.avatar || "")}')"></div>
          <div class="meta bare">
            <h3>${escapeHtml(item.nickname || "")}</h3>
            <div class="card-author">ID ${escapeHtml(item.unique_id || item.uid || "")}</div>
            <div class="card-stats">
              <span>粉 ${fmtNum(item.follower_count)}</span>
              <span>作 ${fmtNum(item.aweme_count)}</span>
            </div>
            ${item.user_url ? `<a class="card-link" href="${escapeHtml(item.user_url)}" target="_blank" rel="noopener"><span>打开主页</span><span class="arrow" aria-hidden="true">→</span></a>` : ""}
          </div>
        </div>
      </article>`;
    }
    if (kind === "comment") {
      const replyTotal = Number(item.reply_count) || (item.replies || []).length || 0;
      const replies = (item.replies || [])
        .map((r) => {
          const rTime = fmtCardTime(r.create_time);
          const name = escapeHtml(r.nickname || "未知用户");
          const avatar = escapeHtml(r.avatar || "");
          const uid = escapeHtml(r.unique_id || r.uid || "");
          const nameHtml = r.user_url
            ? `<a class="cmt-name" href="${escapeHtml(r.user_url)}" target="_blank" rel="noopener">${name}</a>`
            : `<span class="cmt-name">${name}</span>`;
          return `<div class="reply-item">
            <div class="avatar avatar-sm" style="background-image:url('${avatar}')"></div>
            <div class="reply-body">
              <div class="cmt-who">
                <span class="cmt-role">回复</span>
                ${nameHtml}
                ${uid ? `<span class="cmt-id">@${uid}</span>` : ""}
                ${rTime ? `<time class="card-time">${escapeHtml(rTime)}</time>` : ""}
              </div>
              <p class="comment-text">${escapeHtml(r.text || "")}</p>
              <div class="card-stats"><span>赞 ${fmtNum(r.digg_count)}</span></div>
            </div>
          </div>`;
        })
        .join("");
      const name = escapeHtml(item.nickname || "未知用户");
      const uid = escapeHtml(item.unique_id || item.uid || "");
      const nameHtml = item.user_url
        ? `<a class="cmt-name" href="${escapeHtml(item.user_url)}" target="_blank" rel="noopener">${name}</a>`
        : `<span class="cmt-name">${name}</span>`;
      const intentBadge = item.is_intent
        ? `<span class="badge badge-intent">意向${item.intent_score != null ? " " + item.intent_score : ""}</span>`
        : (item.intent_blocked && item.intent_blocked.length
          ? `<span class="badge badge-risk">风险</span>`
          : "");
      const metaBits = [
        item.ip_label ? `属地 ${escapeHtml(item.ip_label)}` : "",
        item.gender ? escapeHtml(item.gender) : "",
        item.is_verified ? "认证" : "",
      ].filter(Boolean);
      return `<article class="card card-comment wide is-selected${item.is_intent ? " is-intent" : ""}">
        ${pickHtml(id)}
        <div class="cmt-main">
          <div class="avatar" style="background-image:url('${escapeHtml(item.avatar || "")}')"></div>
          <div class="meta bare">
            <div class="cmt-who">
              <span class="cmt-role cmt-role-main">主评</span>
              ${intentBadge}
              ${nameHtml}
              ${uid ? `<span class="cmt-id">@${uid}</span>` : ""}
              ${time ? `<time class="card-time">${escapeHtml(time)}</time>` : ""}
            </div>
            <p class="comment-text">${escapeHtml(item.text || "")}</p>
            <div class="card-stats">
              <span>赞 ${fmtNum(item.digg_count)}</span>
              <span>回复 ${fmtNum(replyTotal)}</span>
              ${metaBits.map((b) => `<span>${b}</span>`).join("")}
            </div>
            <div class="card-actions">
              <button type="button" class="chip-action" data-act="reply" data-cid="${id}" data-nick="${name}">回复</button>
            </div>
            <form class="reply-composer" hidden>
              <input type="text" class="reply-input" maxlength="200" placeholder="回复 @${name}…" aria-label="回复内容" />
              <button type="submit" class="btn btn-primary btn-sm">
                <span class="btn-label">发送</span>
              </button>
            </form>
          </div>
        </div>
        ${replies ? `<div class="reply-block"><div class="reply-head">回复线程 · ${escapeHtml(String((item.replies || []).length))}</div>${replies}</div>` : ""}
      </article>`;
    }
    if (kind === "live") {
      return `<article class="card is-selected">
        ${pickHtml(id)}
        <div class="meta">
          <div class="meta-top"><span class="badge">直播</span></div>
          <h3>${escapeHtml(item.title || "")}</h3>
          <div class="card-author">@${escapeHtml(item.nickname || "")}</div>
          <div class="card-stats"><span>在线 ${fmtNum(item.user_count)}</span></div>
        </div>
      </article>`;
    }
    return `<article class="card wide is-selected">
      ${pickHtml(id)}
      <div class="meta">
        <span class="badge">${escapeHtml(kind)}</span>
        <h3>${escapeHtml(item.title || item.nickname || id)}</h3>
        <pre class="log dump">${escapeHtml(JSON.stringify(item, null, 2))}</pre>
      </div>
    </article>`;
  }

  let rawResults = [];
  let resultMeta = { excelPath: "", selectable: false, defaultName: "", resultKind: "work" };

  function filterCommentItems(items) {
    const intentOnly = !!$("#cfIntentOnly")?.checked;
    const ip = String($("#cfIp")?.value || "").trim();
    const gender = String($("#cfGender")?.value || "").trim();
    const keyword = String($("#cfKeyword")?.value || "").trim();
    const verifiedOnly = !!$("#cfVerified")?.checked;
    return (items || []).filter((item) => {
      if (intentOnly && !item.is_intent) return false;
      if (ip && !(item.ip_label || "").includes(ip)) return false;
      if (gender && item.gender !== gender) return false;
      if (keyword && !(item.text || "").includes(keyword)) return false;
      if (verifiedOnly && !item.is_verified) return false;
      return true;
    });
  }

  function filterResultItems(items, kind) {
    if (kind === "comment") return filterCommentItems(items);
    const q = String($("#resultSearch")?.value || "").trim().toLowerCase();
    if (!q) return items || [];
    return (items || []).filter((item) => {
      const blob = [
        item.title, item.nickname, item.text, item.unique_id, item.uid, item.work_id,
      ].map((x) => String(x || "").toLowerCase()).join(" ");
      return blob.includes(q);
    });
  }

  function paintResults(list) {
    const kind = resultMeta.resultKind || "work";
    const hasRaw = (rawResults || []).length > 0;
    $("#resultCount").textContent = `${list.length}${hasRaw && list.length !== rawResults.length ? ` / ${rawResults.length}` : ""}`;
    const chrome = $("#resultChrome");
    const cf = $("#commentFilters");
    const exportMore = $("#exportMore");
    if (cf) {
      cf.hidden = kind !== "comment" || !hasRaw;
      if (kind === "comment" && hasRaw) {
        const intentN = (rawResults || []).filter((x) => x.is_intent).length;
        const stats = $("#cfStats");
        if (stats) stats.textContent = `· ${list.length}/${rawResults.length} · 意向 ${intentN}`;
      }
    }
    const searchEl = $("#resultSearch");
    if (searchEl) {
      searchEl.placeholder = kind === "comment"
        ? "结果内再搜昵称/内容…"
        : "结果内搜索标题/作者…";
    }
    if (resultMeta.excelPath) {
      const name = resultMeta.excelPath.split(/[/\\]/).pop();
      $("#excelLink").hidden = false;
      $("#excelLink").href = `/api/excels/${encodeURIComponent(name)}`;
      $("#excelLink").textContent = `下载 ${name} →`;
    } else {
      $("#excelLink").hidden = true;
    }
    const showChrome = !!(resultMeta.selectable && hasRaw);
    if (chrome) chrome.hidden = !showChrome;
    if (exportMore) exportMore.hidden = !showChrome;
    if (showChrome) {
      if (resultMeta.defaultName && !$("#saveName")?.dataset.touched) {
        $("#saveName").value = resultMeta.defaultName;
      }
      setSaveChoice(kind !== "work" ? "excel" : "all");
    }
    const composer = $("#commentComposer");
    if (composer) {
      const showComposer = kind === "comment" && !!lastWorkUrl;
      composer.hidden = !showComposer;
      if (showComposer) {
        const wid = lastWorkUrl.split(/[/?]/).filter(Boolean).pop() || "";
        $("#composerTarget").textContent = wid ? `对作品 ${wid} 发表评论` : "发表评论";
      }
    }
    if (!list.length) {
      $("#resultGrid").innerHTML = "";
      $("#emptyState").hidden = false;
      return;
    }
    $("#emptyState").hidden = true;
    $("#resultGrid").innerHTML = list.map((item, i) => cardHtml(item, i)).join("");
    $$(".card-check").forEach((el) => el.addEventListener("change", updateSelectedCount));
    updateSelectedCount();
  }

  function renderResults(items, { excelPath = "", selectable = false, defaultName = "", resultKind = "work" } = {}) {
    currentKind = resultKind || "work";
    rawResults = items || [];
    resultMeta = { excelPath, selectable, defaultName, resultKind: currentKind };
    const nameEl = $("#saveName");
    if (nameEl) {
      delete nameEl.dataset.touched;
      if (defaultName) nameEl.value = defaultName;
    }
    paintResults(filterResultItems(rawResults, currentKind));
  }

  function refreshFilteredResults() {
    paintResults(filterResultItems(rawResults, resultMeta.resultKind || currentKind || "work"));
  }

  function setBusy(busy) {
    $("#scanBtn").disabled = busy;
    $("#saveBtn").disabled = busy;
    const label = $("#scanBtn").querySelector(".btn-label");
    if (label) label.textContent = busy ? "进行中…" : "扫描 / 拉取";
    $("#scanBtn").classList.toggle("is-busy", busy);
    $("#saveBtn").classList.toggle("is-busy", busy);
  }

  function syncJobChrome(job) {
    const box = $("#jobBox");
    const log = $("#jobLog");
    const status = job.status || "—";
    const done = status === "done";
    const error = status === "error";
    const running = status === "running" || status === "queued";
    box.classList.toggle("is-done", done || error);
    box.classList.toggle("is-error", error);
    $("#jobStatus").textContent = error ? "失败" : status;
    $("#jobPct").textContent = `${job.progress || 0}%`;
    $("#jobBar").style.width = `${job.progress || 0}%`;
    $("#jobMsg").textContent = job.message || "";
    const lines = (job.logs || []).slice(-40).map((l) => l.msg).join("\n").trim();
    log.textContent = lines;
    log.hidden = !(error || (lines && !done));
    log.classList.toggle("has-error", error && !!lines);

    const chip = $("#jobChip");
    const chipWrap = $("#jobInline");
    if (chip && chipWrap) {
      chipWrap.hidden = false;
      chip.className = "status-chip"
        + (done && !error ? " is-ok" : "")
        + (error ? " is-err" : "")
        + (running ? " is-run" : "");
      if (error) chip.textContent = `失败 · ${job.message || ""}`;
      else if (done) chip.textContent = job.message || "完成";
      else chip.textContent = `${status}${job.message ? " · " + job.message : ""}`;
    }
    // 成功时收起冗长 job 面板，保留 chip
    if (done && !error && !lines) box.hidden = true;
  }

  async function pollJob(jobId, { isSave = false } = {}) {
    $("#jobBox").hidden = false;
    clearInterval(pollTimer);
    const tick = async () => {
      const res = await fetch(`/api/jobs/${jobId}`);
      const job = await res.json();
      syncJobChrome(job);
      if (!isSave && job.results) {
        renderResults(job.results, {
          excelPath: job.excel_path,
          selectable: !!job.selectable,
          defaultName: job.default_name || "",
          resultKind: job.result_kind || "work",
        });
      }
      if (isSave && job.status === "done" && job.excel_path) {
        const name = job.excel_path.split(/[/\\]/).pop();
        $("#excelLink").hidden = false;
        $("#excelLink").href = `/api/excels/${encodeURIComponent(name)}`;
        $("#excelLink").textContent = `下载 ${name} →`;
      }
      if (job.status === "done" || job.status === "error") {
        clearInterval(pollTimer);
        setBusy(false);
        refreshStatus();
        if (!isSave && job.status === "done") {
          currentScanJobId = jobId;
          if (job.default_name) $("#saveName").value = job.default_name;
        }
      }
    };
    await tick();
    pollTimer = setInterval(() => tick().catch((e) => {
      clearInterval(pollTimer);
      setBusy(false);
      $("#jobMsg").textContent = e.message || String(e);
    }), 1200);
  }

  $("#checkAll").addEventListener("change", () => {
    const on = $("#checkAll").checked;
    $$(".card-check").forEach((el) => {
      el.checked = on;
      syncCardSelected(el);
    });
    updateSelectedCount();
  });

  $("#saveBtn").addEventListener("click", async () => {
    const ids = selectedIds();
    if (!currentScanJobId) return alert("请先扫描");
    if (!ids.length) return alert("请至少勾选一条");
    setBusy(true);
    try {
      const res = await fetch("/api/jobs/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_job_id: currentScanJobId,
          work_ids: ids,
          ids,
          save_choice: getSaveChoice(),
          excel_name: $("#saveName").value.trim() || "selected",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "保存失败");
      await pollJob(data.job_id, { isSave: true });
    } catch (err) {
      setBusy(false);
      alert(err.message || String(err));
    }
  });

  $("#configNavBtn").addEventListener("click", () => showConfigView());
  $("#agentNavBtn").addEventListener("click", () => showAgentView());
  $("#archiveNavBtn")?.addEventListener("click", () => showArchiveView());
  $("#archiveRefreshBtn")?.addEventListener("click", () => {
    refreshStatus().catch((e) => alert(e.message || String(e)));
  });
  $("#saveName")?.addEventListener("input", () => {
    if ($("#saveName")) $("#saveName").dataset.touched = "1";
  });

  $("#agentPreviewBtn")?.addEventListener("click", async () => {
    showAgentMsg("生成计划预览…", true);
    $("#agentPreviewBtn").disabled = true;
    try {
      await previewAgentPlan();
      showAgentMsg("已生成计划并同步确认队列（未执行）", true);
    } catch (err) {
      showAgentMsg(err.message || String(err), false);
    } finally {
      $("#agentPreviewBtn").disabled = false;
    }
  });

  $("#cfApplyBtn")?.addEventListener("click", () => refreshFilteredResults());
  ["cfIntentOnly", "cfVerified"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      if ((resultMeta.resultKind || currentKind) === "comment") refreshFilteredResults();
    });
  });
  $("#resultSearch")?.addEventListener("input", () => refreshFilteredResults());

  $("#agentWorkerBtn")?.addEventListener("click", async () => {
    showAgentMsg("正在跑只读准备…", true);
    $("#agentWorkerBtn").disabled = true;
    try {
      const data = await runWorkerPrep("");
      showAgentMsg(data.message || "只读准备完成", !!data.ok);
    } catch (err) {
      showAgentMsg(err.message || String(err), false);
    } finally {
      $("#agentWorkerBtn").disabled = false;
    }
  });

  $("#agentDraftBtn")?.addEventListener("click", async () => {
    showAgentMsg("正在生成评论草稿…", true);
    $("#agentDraftBtn").disabled = true;
    try {
      const data = await runWorkerWrite("draft", "");
      showAgentMsg(data.message || "草稿已生成", !!data.ok);
    } catch (err) {
      showAgentMsg(err.message || String(err), false);
    } finally {
      $("#agentDraftBtn").disabled = false;
    }
  });

  $("#agentWriteBtn")?.addEventListener("click", async () => {
    if (!confirm("将按草稿真实发布评论到抖音，确认继续？")) return;
    showAgentMsg("正在执行评论发布…", true);
    $("#agentWriteBtn").disabled = true;
    try {
      const data = await runWorkerWrite("execute", "", false);
      showAgentMsg(data.message || "写操作完成", !!data.ok);
    } catch (err) {
      showAgentMsg(err.message || String(err), false);
    } finally {
      $("#agentWriteBtn").disabled = false;
    }
  });

  async function applyCandidateSelect(itemId, root) {
    const box = root || document.querySelector(`[data-result-item="${CSS.escape(itemId)}"]`);
    if (!box) throw new Error("找不到候选列表");
    const workIds = [...box.querySelectorAll("[data-pick-work]:checked:not(:disabled)")].map((el) => el.value);
    const commentCids = [...box.querySelectorAll("[data-pick-comment]:checked:not(:disabled)")].map((el) => el.value);
    const filters = box.querySelector(".wr-filters");
    const body = {
      item_id: itemId,
      work_ids: workIds,
      comment_cids: commentCids,
    };
    if (filters) {
      body.work_min_digg = Number(filters.querySelector("[data-f-work-digg]")?.value || 0);
      body.comment_min_digg = Number(filters.querySelector("[data-f-comment-digg]")?.value || 0);
      body.comment_keyword = String(filters.querySelector("[data-f-keyword]")?.value || "").trim();
      body.comment_exclude = String(filters.querySelector("[data-f-exclude]")?.value || "").trim();
      body.intent_only = !!filters.querySelector("[data-f-intent-only]")?.checked;
    }
    const res = await fetch("/api/agent/worker/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch { /* ignore */ }
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : "筛选失败"));
    }
    renderPlan(data.plan);
    renderQueue(data.queue);
    return data;
  }

  $("#agentQueueList")?.addEventListener("click", async (e) => {
    const applyBtn = e.target.closest("[data-apply-select]");
    if (applyBtn) {
      const id = applyBtn.dataset.applySelect;
      applyBtn.disabled = true;
      try {
        const data = await applyCandidateSelect(id, applyBtn.closest(".agent-worker-result"));
        showAgentMsg(data.message || "筛选已更新", true);
      } catch (err) {
        showAgentMsg(err.message || String(err), false);
      } finally {
        applyBtn.disabled = false;
      }
      return;
    }
    const workerBtn = e.target.closest("[data-worker-id]");
    if (workerBtn) {
      const id = workerBtn.dataset.workerId;
      workerBtn.disabled = true;
      try {
        const data = await runWorkerPrep(id);
        showAgentMsg(data.message || "只读准备完成", !!data.ok);
      } catch (err) {
        showAgentMsg(err.message || String(err), false);
      } finally {
        workerBtn.disabled = false;
      }
      return;
    }
    const draftBtn = e.target.closest("[data-draft-id]");
    if (draftBtn) {
      const id = draftBtn.dataset.draftId;
      draftBtn.disabled = true;
      try {
        const data = await runWorkerWrite("draft", id);
        showAgentMsg(data.message || "草稿已生成", !!data.ok);
      } catch (err) {
        showAgentMsg(err.message || String(err), false);
      } finally {
        draftBtn.disabled = false;
      }
      return;
    }
    const writeBtn = e.target.closest("[data-write-id]");
    if (writeBtn) {
      if (!confirm("将按该条草稿真实发布评论，确认继续？")) return;
      const id = writeBtn.dataset.writeId;
      writeBtn.disabled = true;
      try {
        const data = await runWorkerWrite("execute", id, false);
        showAgentMsg(data.message || "写操作完成", !!data.ok);
      } catch (err) {
        showAgentMsg(err.message || String(err), false);
      } finally {
        writeBtn.disabled = false;
      }
      return;
    }
    const btn = e.target.closest("[data-queue-action]");
    if (!btn) return;
    const id = btn.dataset.queueId;
    const action = btn.dataset.queueAction;
    if (!id || !action) return;
    btn.disabled = true;
    try {
      await decideQueueItem(id, action);
      showAgentMsg(action === "approve" ? "已批准，可跑只读准备" : "已拒绝该步骤", true);
    } catch (err) {
      showAgentMsg(err.message || String(err), false);
    } finally {
      btn.disabled = false;
    }
  });

  $("#agentForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    showAgentMsg("保存中…", true);
    $("#agentSaveBtn").disabled = true;
    try {
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(readAgent()),
      });
      let data = {};
      try { data = await res.json(); } catch { /* 非 JSON，如旧进程 404 HTML */ }
      if (!res.ok) {
        if (res.status === 404) throw new Error("接口未找到：请重启工作台后再保存");
        const detail = data.detail;
        throw new Error(typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : "保存失败"));
      }
      fillAgent(data.agent || {});
      renderPlan(data.plan);
      renderQueue(data.queue);
      const path = agentEl("agentPath");
      if (path) path.textContent = data.path || "—";
      showAgentMsg("策略已保存（不会自动执行）", true);
    } catch (err) {
      showAgentMsg(err.message || String(err), false);
    } finally {
      $("#agentSaveBtn").disabled = false;
    }
  });

  $("#cfgParseBtn").addEventListener("click", async () => {
    showCfgMsg("解析中…", true);
    try {
      const res = await fetch("/api/config/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dump: $("#cfgDump").value,
          cookies: $("#cfgCookies").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "解析失败");
      applyParsed(data.parsed || {});
      const keys = Object.keys(data.parsed || {});
      showCfgMsg(keys.length ? `已提取：${keys.join(", ")}` : "未识别到可用字段，请检查粘贴内容", !!keys.length);
    } catch (err) {
      showCfgMsg(err.message || String(err), false);
    }
  });

  $("#configForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    showCfgMsg("保存中…", true);
    $("#cfgSaveBtn").disabled = true;
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dump: $("#cfgDump").value,
          cookies: $("#cfgCookies").value,
          ua: $("#cfgUa").value,
          browser_version: $("#cfgBrowserVersion").value,
          engine_version: $("#cfgEngineVersion").value,
          accept_language: $("#cfgAcceptLanguage").value,
          screen_width: $("#cfgScreenWidth").value,
          screen_height: $("#cfgScreenHeight").value,
          cpu_core_num: $("#cfgCpu").value,
          device_memory: $("#cfgMemory").value,
          proxy: $("#cfgProxy").value.trim(),
          reload_auth: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "保存失败");
      renderConfigStatus(data);
      const uid = data.uid ? ` · uid ${data.uid}` : "";
      const reload = data.reloaded ? `会话已重载${uid}` : (data.reload_error || "已写入，但重载失败");
      showCfgMsg(`已保存 ${ (data.saved_keys || []).join(", ") }。${reload}`, !!data.reloaded || !!data.has_sessionid);
      await refreshStatus();
    } catch (err) {
      showCfgMsg(err.message || String(err), false);
    } finally {
      $("#cfgSaveBtn").disabled = false;
    }
  });

  $("#taskForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd.entries());
    body.module = currentModule;
    body.require_num = Number(body.require_num || 12);
    if (body.urls) {
      body.urls = String(body.urls).split(/\n+/).map((s) => s.trim()).filter(Boolean);
    }
    if (body.work_url) lastWorkUrl = String(body.work_url).trim();
    setBusy(true);
    try {
      const res = await fetch("/api/jobs/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "提交失败");
      await pollJob(data.job_id);
    } catch (err) {
      setBusy(false);
      alert(err.message || String(err));
    }
  });

  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || "操作失败");
    return data;
  }

  // 作品卡片的点赞 / 收藏，评论卡片的回复展开
  $("#resultGrid").addEventListener("click", async (e) => {
    const btn = e.target.closest(".chip-action");
    if (!btn) return;
    const act = btn.dataset.act;

    if (act === "reply") {
      const box = btn.closest(".card")?.querySelector(".reply-composer");
      if (!box) return;
      box.hidden = !box.hidden;
      if (!box.hidden) box.querySelector(".reply-input")?.focus();
      return;
    }

    const aweme = btn.dataset.aweme || "";
    if (!aweme) return;
    const next = btn.dataset.on === "1" ? "0" : "1";
    const url = act === "digg" ? "/api/action/digg" : "/api/action/collect";
    btn.disabled = true;
    try {
      const data = await postJson(url, { aweme_id: aweme, action: next });
      if (!data.ok) throw new Error(data.message || "操作失败");
      actionState.set(`${act}:${aweme}`, next);
      btn.dataset.on = next;
      btn.classList.toggle("is-on", next === "1");
      btn.setAttribute("aria-pressed", String(next === "1"));
      btn.textContent = act === "digg"
        ? (next === "1" ? "已赞" : "点赞")
        : (next === "1" ? "已藏" : "收藏");
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      btn.disabled = false;
    }
  });

  // 单条评论回复
  $("#resultGrid").addEventListener("submit", async (e) => {
    const form = e.target.closest(".reply-composer");
    if (!form) return;
    e.preventDefault();
    const input = form.querySelector(".reply-input");
    const content = String(input?.value || "").trim();
    if (!content) return;
    const trigger = form.closest(".card")?.querySelector('[data-act="reply"]');
    const btn = form.querySelector("button");
    btn.disabled = true;
    try {
      const data = await postJson("/api/action/comment", {
        work_url: lastWorkUrl,
        content,
        reply_id: trigger?.dataset.cid || "",
      });
      if (!data.ok) throw new Error(data.message || "发布失败");
      input.value = "";
      form.hidden = true;
      const label = btn.querySelector(".btn-label");
      if (label) label.textContent = "已发送";
      setTimeout(() => { if (label) label.textContent = "发送"; }, 2000);
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      btn.disabled = false;
    }
  });

  // 评论区针对当前作品的自由输入
  $("#commentComposer").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#composerText");
    const msg = $("#composerMsg");
    const content = String(input.value || "").trim();
    if (!content) {
      msg.hidden = false;
      msg.className = "composer-msg is-error";
      msg.textContent = "评论内容不能为空";
      return;
    }
    if (!lastWorkUrl) {
      msg.hidden = false;
      msg.className = "composer-msg is-error";
      msg.textContent = "缺少目标作品，请先在评论区扫描一条作品链接";
      return;
    }
    const btn = $("#composerSend");
    btn.disabled = true;
    msg.hidden = true;
    try {
      const data = await postJson("/api/action/comment", { work_url: lastWorkUrl, content });
      if (!data.ok) throw new Error(data.message || "发布失败");
      input.value = "";
      msg.hidden = false;
      msg.className = "composer-msg is-ok";
      msg.textContent = data.message || "评论已发布";
    } catch (err) {
      msg.hidden = false;
      msg.className = "composer-msg is-error";
      msg.textContent = err.message || String(err);
    } finally {
      btn.disabled = false;
    }
  });

  // ===== 私信 / 发布视频 / 素材库 =====
  let mediaItems = [];
  let mediaLoaded = false;

  function createMsg(elId, text, ok) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.hidden = !text;
    el.textContent = text || "";
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("err", !ok);
  }

  function fmtSize(n) {
    const size = Number(n) || 0;
    if (size >= 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + " MB";
    if (size >= 1024) return Math.round(size / 1024) + " KB";
    return size + " B";
  }

  function fillMediaSelect() {
    const select = $("#dmMedia");
    if (!select) return;
    const kind = $("#dmKind")?.value || "text";
    const usable = mediaItems.filter((item) => item.kind === kind);
    const current = select.value;
    select.innerHTML = `<option value="">选择素材</option>${usable.map((item) =>
      `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}（${fmtSize(item.size)}）</option>`
    ).join("")}`;
    if (usable.some((item) => item.name === current)) select.value = current;
  }

  function renderMedia() {
    const list = $("#mediaList");
    const empty = $("#mediaEmpty");
    if (!list) return;
    if (!mediaItems.length) {
      list.innerHTML = "";
      empty.hidden = false;
      fillMediaSelect();
      return;
    }
    empty.hidden = true;
    const KIND_LABEL = { image: "图片", video: "视频", file: "文件" };
    list.innerHTML = mediaItems.map((item) => {
      const label = KIND_LABEL[item.kind] || "文件";
      const thumb = item.kind === "image"
        ? `<img class="media-thumb" src="${escapeHtml(item.url)}" alt="" loading="lazy" />`
        : `<span class="media-thumb media-thumb-kind">${label}</span>`;
      return `<li class="media-item">
        ${thumb}
        <div class="media-meta">
          <strong>${escapeHtml(item.name)}</strong>
          <span>${label} · ${fmtSize(item.size)} · ${escapeHtml(fmtCardTime(item.mtime))}</span>
        </div>
        <a class="text-link" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">预览</a>
      </li>`;
    }).join("");
    fillMediaSelect();
  }

  async function loadMedia(force = false) {
    if (mediaLoaded && !force) return;
    const res = await fetch("/api/media/list");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "素材列表加载失败");
    mediaItems = data.items || [];
    mediaLoaded = true;
    renderMedia();
  }

  function toggleDmKind() {
    const kind = $("#dmKind")?.value || "text";
    const textField = $("#dmTextField");
    const mediaField = $("#dmMediaField");
    if (textField) textField.hidden = kind !== "text";
    if (mediaField) mediaField.hidden = kind === "text";
    fillMediaSelect();
  }

  async function uploadMediaFiles(files) {
    const list = [...files];
    if (!list.length) return;
    const input = $("#mediaFileInput");
    if (input) input.disabled = true;
    try {
      for (const file of list) {
        createMsg("mediaMsg", `上传 ${file.name} …`, true);
        const form = new FormData();
        form.append("file", file);
        const res = await fetch("/api/media/upload", { method: "POST", body: form });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `上传 ${file.name} 失败`);
      }
      await loadMedia(true);
      createMsg("mediaMsg", `已上传 ${list.length} 个文件`, true);
    } catch (err) {
      createMsg("mediaMsg", err.message || String(err), false);
    } finally {
      if (input) {
        input.disabled = false;
        input.value = "";
      }
    }
  }

  $("#createNavBtn")?.addEventListener("click", () => showCreateView());
  $("#mediaRefreshBtn")?.addEventListener("click", () => {
    loadMedia(true).catch((err) => createMsg("mediaMsg", err.message || String(err), false));
  });
  $("#mediaFileInput")?.addEventListener("change", (e) => uploadMediaFiles(e.target.files));
  $("#dmKind")?.addEventListener("change", toggleDmKind);

  $("#dmForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const kind = $("#dmKind").value;
    const target = $("#dmTarget").value.trim();
    const text = $("#dmText").value.trim();
    const mediaName = $("#dmMedia").value;
    if (!target) {
      createMsg("dmMsg", "请填写目标用户链接或 uid", false);
      return;
    }
    if (kind === "text" && !text) {
      createMsg("dmMsg", "私信内容不能为空", false);
      return;
    }
    if (kind !== "text" && !mediaName) {
      createMsg("dmMsg", "请先在素材库上传并选择素材", false);
      return;
    }
    const btn = $("#dmSendBtn");
    btn.disabled = true;
    createMsg("dmMsg", "发送中…", true);
    try {
      const data = await postJson("/api/create/dm", {
        target, text, media_kind: kind, media_name: mediaName,
      });
      if (!data.ok) throw new Error(data.message || "发送失败");
      createMsg("dmMsg", data.message || "私信已发送", true);
    } catch (err) {
      createMsg("dmMsg", err.message || String(err), false);
    } finally {
      btn.disabled = false;
    }
  });

  $("#publishCheckBtn")?.addEventListener("click", async () => {
    createMsg("publishMsg", "检测中…", true);
    try {
      const res = await fetch("/api/create/publish/preflight");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "风控检测未通过");
      createMsg("publishMsg", data.message || "发布安全凭据校验通过", true);
    } catch (err) {
      createMsg("publishMsg", err.message || String(err), false);
    }
  });

  $("#publishForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = $("#publishFile").files[0];
    if (!file) {
      createMsg("publishMsg", "请选择视频文件", false);
      return;
    }
    const btn = $("#publishBtn");
    btn.disabled = true;
    createMsg("publishMsg", "上传并发布中，视频较大时需要等几分钟…", true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", $("#publishTitle").value.trim());
      form.append("desc", $("#publishDesc").value.trim());
      form.append("visibility", $("#publishVisibility").value);
      form.append("allow_download", $("#publishDownload").checked ? "true" : "false");
      const res = await fetch("/api/create/publish", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "发布失败");
      if (!data.ok) throw new Error(data.message || "发布失败");
      createMsg("publishMsg", data.message || "发布成功", true);
      loadMedia(true).catch(() => {});
    } catch (err) {
      createMsg("publishMsg", err.message || String(err), false);
    } finally {
      btn.disabled = false;
    }
  });

  refreshStatus().catch((e) => {
    $("#sessionText").textContent = e.message || String(e);
    $("#sessionDot").className = "dot off";
  });

  let qrTimer = null;
  let liveTimer = null;
  let liveSince = 0;
  let liveEvents = [];
  let liveFilter = "all";
  const LIVE_KIND = {
    chat: "弹幕", gift: "礼物", enter: "进场", like: "点赞",
    social: "关注", emoji: "表情", pk: "PK", control: "状态", system: "系统",
  };

  function showLiveView() {
    viewMode = "live";
    hideAllViews();
    $("#liveView").hidden = false;
    clearSideNavActive();
    startLivePoll();
  }

  function stopLivePoll() {
    clearInterval(liveTimer);
    liveTimer = null;
  }

  function renderLiveEvent(item) {
    const kind = item.kind || "system";
    if (liveFilter !== "all" && kind !== liveFilter) return "";
    const time = fmtCardTime(item.ts);
    return `<li class="feed-item kind-${escapeHtml(kind)}">
      <span class="feed-kind">${escapeHtml(LIVE_KIND[kind] || kind)}</span>
      <span class="feed-body">
        ${item.user ? `<strong>${escapeHtml(item.user)}</strong> ` : ""}
        <span>${escapeHtml(item.text || "")}</span>
      </span>
      <time>${escapeHtml(time)}</time>
    </li>`;
  }

  function renderLiveFeed() {
    const html = liveEvents.map(renderLiveEvent).filter(Boolean).join("");
    const feed = $("#liveFeed");
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    const previous = feed.scrollTop;
    feed.innerHTML = html;
    $("#liveEmpty").hidden = html.length > 0;
    feed.scrollTop = nearBottom ? feed.scrollHeight : previous;
  }

  function applyLiveSnapshot(data, reset) {
    if (reset) {
      liveEvents = data.events || [];
      liveSince = data.seq || 0;
    } else if (data.events && data.events.length) {
      liveEvents = liveEvents.concat(data.events).slice(-800);
      liveSince = data.seq || liveSince;
    } else if (data.seq) {
      liveSince = data.seq;
    }
    const stats = data.stats || {};
    $("#statOnline").textContent = stats.online || "—";
    $("#statChat").textContent = fmtNum(stats.chat);
    $("#statGift").textContent = fmtNum(stats.gift);
    $("#statEnter").textContent = fmtNum(stats.enter);
    $("#statLike").textContent = fmtNum(stats.like);
    $("#statSocial").textContent = fmtNum(stats.social);
    const room = data.room || {};
    const title = [room.nickname, room.title].filter(Boolean).join(" · ");
    const labels = {
      idle: "未连接",
      connecting: "正在连接…",
      live: "监听中",
      stopped: "已停止",
      error: "出错",
    };
    $("#liveStatus").textContent = data.message || title || labels[data.status] || "—";
    if (reset || (data.events && data.events.length)) renderLiveFeed();
  }

  async function pollLive() {
    const res = await fetch(`/api/live?since=${liveSince || 0}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "监听状态读取失败");
    applyLiveSnapshot(data, liveSince === 0);
  }

  function startLivePoll() {
    stopLivePoll();
    pollLive().catch((err) => { $("#liveStatus").textContent = err.message || String(err); });
    liveTimer = setInterval(() => {
      pollLive().catch((err) => { $("#liveStatus").textContent = err.message || String(err); });
    }, 1200);
  }

  function renderRankUsers(rows) {
    if (!rows || !rows.length) return `<li class="rank-empty">暂无</li>`;
    return rows.map((row) => `<li>
      <span class="rank-no">${escapeHtml(row.rank)}</span>
      <span class="rank-name">${escapeHtml(row.nickname || "")}</span>
      <span class="rank-score">${escapeHtml(row.score ?? "")}</span>
    </li>`).join("");
  }

  async function refreshRanks() {
    $("#pkMsg").textContent = "拉取中…";
    $("#contribMsg").textContent = "拉取中…";
    const res = await fetch("/api/live/ranks");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "榜单拉取失败");
    const pk = data.pk || {};
    $("#pkMsg").textContent = pk.message || "";
    $("#pkList").innerHTML = (pk.sides || []).map((side) => `<div class="rank-side">
      <h3>${escapeHtml(side.nickname || side.anchor_id || "主播")}</h3>
      <ol class="rank-list">${renderRankUsers(side.users)}</ol>
    </div>`).join("") || "";
    const contrib = data.contribution || {};
    $("#contribMsg").textContent = contrib.message || "";
    $("#contribList").innerHTML = renderRankUsers(contrib.users);
  }

  $("#liveForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#liveStartBtn").disabled = true;
    $("#liveStatus").textContent = "正在连接…";
    try {
      const res = await fetch("/api/live/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ live: $("#liveInput").value.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "无法开始监听");
      liveSince = 0;
      liveEvents = [];
      applyLiveSnapshot(data, true);
      startLivePoll();
    } catch (err) {
      $("#liveStatus").textContent = err.message || String(err);
    } finally {
      $("#liveStartBtn").disabled = false;
    }
  });

  $("#liveStopBtn").addEventListener("click", async () => {
    try {
      const res = await fetch("/api/live/stop", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "停止失败");
      applyLiveSnapshot(data, false);
    } catch (err) {
      $("#liveStatus").textContent = err.message || String(err);
    }
  });

  $("#liveExportBtn").addEventListener("click", async () => {
    try {
      const res = await fetch("/api/live/export", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "导出失败");
      const link = $("#liveExportLink");
      link.hidden = false;
      link.href = `/api/excels/${encodeURIComponent(data.name)}`;
      link.textContent = `下载 ${data.name} →`;
      refreshStatus();
    } catch (err) {
      $("#liveStatus").textContent = err.message || String(err);
    }
  });

  $("#pkRefreshBtn").addEventListener("click", () => {
    refreshRanks().catch((err) => { $("#pkMsg").textContent = err.message || String(err); });
  });
  $("#contribRefreshBtn").addEventListener("click", () => {
    refreshRanks().catch((err) => { $("#contribMsg").textContent = err.message || String(err); });
  });
  $$("#liveFilter input").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) {
        liveFilter = input.value;
        renderLiveFeed();
      }
    });
  });

  function applyQr(data) {
    const msg = $("#qrMsg");
    const frame = $("#qrFrame");
    const img = $("#qrImg");
    const status = data.status || "";
    msg.textContent = data.message || "";
    msg.classList.toggle("is-ok", status === "confirmed");
    msg.classList.toggle("is-err", status === "error" || status === "timeout");
    if (data.image) {
      img.src = data.image;
      frame.hidden = false;
    } else {
      frame.hidden = true;
      img.removeAttribute("src");
      img.removeAttribute("srcset");
    }
  }

  async function pollQr() {
    const res = await fetch("/api/login/qr");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "二维码状态读取失败");
    applyQr(data);
    if (["confirmed", "error", "timeout"].includes(data.status)) {
      clearInterval(qrTimer);
      qrTimer = null;
      $("#qrStartBtn").disabled = false;
      if (data.status === "confirmed") {
        await refreshStatus();
        await loadConfig();
        showCfgMsg(data.message || "登录成功", true);
      }
    }
  }

  $("#qrStartBtn").addEventListener("click", async () => {
    $("#qrStartBtn").disabled = true;
    $("#qrMsg").textContent = "正在获取二维码…";
    try {
      const res = await fetch("/api/login/qr", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "无法生成二维码");
      applyQr(data);
      clearInterval(qrTimer);
      qrTimer = setInterval(() => {
        pollQr().catch((err) => {
          $("#qrMsg").textContent = err.message || String(err);
        });
      }, 1500);
    } catch (err) {
      $("#qrStartBtn").disabled = false;
      $("#qrMsg").textContent = err.message || String(err);
    }
  });
})();
