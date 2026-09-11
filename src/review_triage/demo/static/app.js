const API_BASE_URL = "https://llm-translation-review-decision-agent.onrender.com";
const TRAJECTORY_SCHEMA_VERSION = "review-agent-trajectory/v1";
const LIVE_BACKEND_UNAVAILABLE_MESSAGE = "本次审校已安全停止，未生成任何结论。请稍后重新提交。";

const contentTypeLabels = {
  MARKETING: "营销文案",
  CUSTOMER_SUPPORT: "客服话术",
  UI: "界面文案",
};
const dimensionLabels = {
  TERMINOLOGY: "术语",
  ACCURACY: "准确性",
  LOCALE: "本地化",
  AUDIENCE: "受众",
};
const severityLabels = {
  Neutral: "无问题",
  Minor: "轻微问题",
  Major: "严重问题",
  Critical: "极严重问题",
};
const verificationLabels = {
  AUTO_TRUST: "自动信任",
  SAMPLE_AUDIT: "抽样复核",
  HUMAN_VERIFY: "人工确认",
};
const routeLabels = {
  AUTO_PASS: "自动通过",
  SAMPLE_POOL: "抽样复核",
  HUMAN_REQUIRED: "人工复核",
};
const stepStatusLabels = {
  COMPLETE: "完成",
  SKIPPED: "跳过",
  HIT: "命中",
  MISS: "未命中",
  SAFE_ABSTAIN: "安全弃权",
};

const workspace = document.querySelector("#review-workspace");
const replayStatus = document.querySelector("#replay-status");
const replayTabs = [...document.querySelectorAll(".case-tab")];
const caseSwitcher = document.querySelector("#cases");
const caseWorkspaceCard = document.querySelector(".case-workspace-card");
const mobileCasePicker = document.querySelector("#mobile-case-picker");
const mobileCaseLabel = document.querySelector("#mobile-case-label");
const trajectoryList = document.querySelector("#trajectory-list");
const evidenceList = document.querySelector("#evidence-list");
const reliabilityList = document.querySelector("#reliability-list");
const dialog = document.querySelector("#live-review-dialog");
const form = document.querySelector("#review-form");
const reviewProgress = document.querySelector("#review-progress");
const reviewProgressKicker = document.querySelector("#review-progress-kicker");
const reviewProgressTitle = document.querySelector("#review-progress-title");
const reviewProgressMessage = document.querySelector("#review-progress-message");
const submitButton = document.querySelector("#submit-button");
const siteHeader = document.querySelector(".site-header");
const primaryNavigation = document.querySelector("#primary-navigation");
const mobileMenuToggle = document.querySelector("#mobile-menu-toggle");
let replayRequestSequence = 0;
let currentTrajectory = null;

const mobileCaseLayout = window.matchMedia("(max-width: 760px), (max-width: 900px) and (max-height: 500px)");

function setMobileCasePicker(open, { restoreFocus = false } = {}) {
  caseSwitcher.classList.toggle("is-mobile-open", open);
  mobileCasePicker.setAttribute("aria-expanded", String(open));
  if (!open && restoreFocus) mobileCasePicker.focus();
}

mobileCasePicker.addEventListener("click", () => {
  setMobileCasePicker(mobileCasePicker.getAttribute("aria-expanded") !== "true");
});

mobileCaseLayout.addEventListener("change", () => setMobileCasePicker(false));

function setMobileMenu(open, { restoreFocus = false } = {}) {
  siteHeader.classList.toggle("is-menu-open", open);
  mobileMenuToggle.setAttribute("aria-expanded", String(open));
  mobileMenuToggle.setAttribute("aria-label", open ? "关闭主导航" : "打开主导航");
  if (!open && restoreFocus) mobileMenuToggle.focus();
}

mobileMenuToggle.addEventListener("click", () => {
  setMobileMenu(mobileMenuToggle.getAttribute("aria-expanded") !== "true");
});

primaryNavigation.querySelectorAll("a, button").forEach((link) => {
  link.addEventListener("click", () => setMobileMenu(false));
});

document.addEventListener("click", (event) => {
  if (siteHeader.classList.contains("is-menu-open") && !siteHeader.contains(event.target)) {
    setMobileMenu(false);
  }
  if (mobileCasePicker.getAttribute("aria-expanded") === "true" && !caseWorkspaceCard.contains(event.target)) {
    setMobileCasePicker(false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && siteHeader.classList.contains("is-menu-open")) {
    setMobileMenu(false, { restoreFocus: true });
  }
  if (event.key === "Escape" && mobileCasePicker.getAttribute("aria-expanded") === "true") {
    setMobileCasePicker(false, { restoreFocus: true });
  }
});

const desktopNavigation = window.matchMedia("(min-width: 761px)");
desktopNavigation.addEventListener("change", (event) => {
  if (event.matches) setMobileMenu(false);
});

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value ?? "—";
}

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function isSafeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

function assertTrajectory(value) {
  if (!value || value.schema_version !== TRAJECTORY_SCHEMA_VERSION || !Array.isArray(value.steps)) {
    throw new Error("Replay does not contain the required trajectory contract");
  }
  return value;
}

function finalRouteStep(trajectory) {
  return trajectory.steps.find((step) => step.kind === "FINAL_ROUTE");
}

function renderTrajectory(trajectory) {
  trajectoryList.replaceChildren();
  if (!trajectory.steps.length) {
    trajectoryList.append(make("li", "step-copy", "本轮未生成可安全展示的行动轨迹。"));
    return;
  }
  trajectory.steps.forEach((step, index) => {
    const item = make("li", "trajectory-step");
    item.dataset.status = step.status;
    const number = make("span", "step-index", String(index + 1).padStart(2, "0"));
    const copy = make("div", "step-copy");
    const header = make("header");
    header.append(
      make("strong", "", step.title_zh),
      make("span", "step-state", stepStatusLabels[step.status] || step.status),
    );
    copy.append(header, make("p", "", step.summary_zh));
    item.append(number, copy);
    trajectoryList.append(item);
  });
}

function renderEvidence(trajectory) {
  const evidence = trajectory.evidence;
  const routeCode = trajectory.final_route?.code || "REVIEW_INCOMPLETE";
  const routeCard = document.querySelector("#route-card");
  routeCard.dataset.route = routeCode;

  const safeAbstain = evidence.status === "INSUFFICIENT" && routeCode === "HUMAN_REQUIRED";
  setText("#route-title", safeAbstain ? "证据不足 · 安全弃权 → 人工复核" : routeLabels[routeCode] || "审校未完成");
  setText("#route-summary", finalRouteStep(trajectory)?.summary_zh || "本轮尚未生成最终处理路径。");
  setText("#evidence-status", evidence.status_label_zh);

  let explanation = "当前判断不依赖外部事实，Review Agent 跳过外部查证。";
  if (evidence.status === "SUFFICIENT") {
    explanation = `受控检索产生 ${evidence.tool_calls.length} 次工具调用，并接纳 ${evidence.verified_evidence.length} 条可信证据。`;
  } else if (evidence.status === "INSUFFICIENT") {
    const hits = evidence.tool_calls.filter((call) => call.result_status === "HIT").length;
    explanation = hits
      ? "检索命中过候选，但没有足够证据进入可信证据链，因此停止自主判断。"
      : "受控检索未获得可接纳的充分证据，因此停止自主判断。";
  } else if (evidence.required) {
    explanation = "当前流程需要外部证据，但尚未返回可安全展示的证据状态。";
  }
  setText("#evidence-explanation", explanation);

  evidenceList.replaceChildren();
  if (!evidence.verified_evidence.length) {
    const empty = make("li", "evidence-empty", evidence.required ? "本轮没有被接纳的可信证据。" : "本轮无需外部证据。" );
    evidenceList.append(empty);
  } else {
    evidence.verified_evidence.forEach((item, index) => {
      const row = make("li");
      row.append(make("strong", "", `已接纳证据 ${index + 1}`));
      row.append(document.createTextNode(` · ${item.relevance_reason || item.provenance}`));
      if (isSafeUrl(item.source_ref)) {
        const link = make("a", "", "查看来源");
        link.href = item.source_ref;
        link.target = "_blank";
        link.rel = "noreferrer";
        row.append(document.createElement("br"), link);
      }
      evidenceList.append(row);
    });
  }
}

function renderReliability(trajectory) {
  reliabilityList.replaceChildren();
  const decisionByDimension = new Map(
    trajectory.reliability_decisions.map((item) => [item.dimension, item]),
  );
  trajectory.dimensions.forEach((dimension) => {
    const row = make("div", "reliability-row");
    const decision = decisionByDimension.get(dimension.dimension);
    const label = `${dimensionLabels[dimension.dimension] || dimension.dimension} · ${severityLabels[dimension.severity] || dimension.severity}`;
    row.append(
      make("span", "", label),
      make("strong", "", verificationLabels[decision?.verification_route] || "待确认"),
    );
    reliabilityList.append(row);
  });
  if (!trajectory.dimensions.length) {
    reliabilityList.append(make("p", "", "本轮未返回四维审校结果。"));
  }
}

function renderWorkspace(trajectory, presentation = {}) {
  const verifiedTrajectory = assertTrajectory(trajectory);
  currentTrajectory = verifiedTrajectory;
  const reviewCase = verifiedTrajectory.case;
  setText("#case-id", presentation.displayCaseId || verifiedTrajectory.case_id || "LIVE");
  setText("#content-type", contentTypeLabels[reviewCase?.content_type] || reviewCase?.content_type || "内容类型待确认");
  setText("#risk-label", verifiedTrajectory.risk?.label_zh || "风险待确认");
  setText("#source-text", reviewCase?.source_text || "本轮没有可展示的原文。");
  setText("#translation-text", reviewCase?.translation || "本轮没有可展示的候选译文。");
  setText("#trajectory-version", verifiedTrajectory.schema_version.replace("review-agent-trajectory/", ""));
  const evidence = verifiedTrajectory.evidence;
  setText("#tool-call-summary", `${evidence.tool_calls.length} 次工具调用 · ${evidence.verified_evidence.length} 条已接纳证据`);
  renderTrajectory(verifiedTrajectory);
  renderEvidence(verifiedTrajectory);
  renderReliability(verifiedTrajectory);
  workspace.setAttribute("aria-busy", "false");
}

function setActiveTab(activeTab) {
  replayTabs.forEach((tab) => {
    const active = tab === activeTab;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  if (activeTab) {
    mobileCaseLabel.textContent = activeTab.querySelector("span")?.textContent || "当前案例";
    mobileCasePicker.dataset.activeCase = String(replayTabs.indexOf(activeTab) + 1);
    workspace.setAttribute("aria-labelledby", activeTab.id);
    workspace.removeAttribute("aria-label");
  } else {
    workspace.removeAttribute("aria-labelledby");
    workspace.setAttribute("aria-label", "Live Review 结果");
  }
}

function setReplayLoading(active) {
  workspace.setAttribute("aria-busy", String(active));
  replayTabs.forEach((tab) => { tab.disabled = active; });
  mobileCasePicker.disabled = active;
}

async function loadReplay(tab, options = {}) {
  const requestSequence = ++replayRequestSequence;
  setReplayLoading(true);
  replayStatus.textContent = "正在加载冻结案例。";
  try {
    const response = await fetch(tab.dataset.replayUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(`Replay fetch failed: ${response.status}`);
    const snapshot = await response.json();
    if (snapshot?.replay_metadata?.type !== "VERIFIED_REPLAY") throw new Error("Invalid replay metadata");
    const trajectory = assertTrajectory(snapshot?.result?.trajectory);
    if (requestSequence !== replayRequestSequence) return;
    setActiveTab(tab);
    renderWorkspace(trajectory, {
      displayCaseId: snapshot.replay_metadata.display_case_id || tab.dataset.displayCaseId,
    });
    replayStatus.textContent = `已加载${snapshot.replay_metadata.label}。`;
  } catch {
    if (requestSequence !== replayRequestSequence) return;
    replayStatus.textContent = "冻结案例加载失败，当前页面没有生成替代结论。";
    workspace.setAttribute("aria-busy", "false");
  } finally {
    if (requestSequence === replayRequestSequence) {
      setReplayLoading(false);
      if (options.focusPicker) mobileCasePicker.focus();
      else if (options.focus) tab.focus();
    }
  }
}

replayTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const focusPicker = mobileCaseLayout.matches;
    if (focusPicker) setMobileCasePicker(false);
    loadReplay(tab, { focusPicker });
  });
  tab.addEventListener("keydown", (event) => {
    const currentIndex = replayTabs.indexOf(tab);
    let nextIndex = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (currentIndex + 1) % replayTabs.length;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (currentIndex - 1 + replayTabs.length) % replayTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = replayTabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    loadReplay(replayTabs[nextIndex], { focus: true });
  });
});

function openLiveDialog() {
  if (!dialog.open) dialog.showModal();
  window.requestAnimationFrame(() => form.elements.source_text.focus());
}

function setReviewSubmissionState(state, message = "") {
  const submitting = state === "loading";
  form.setAttribute("aria-busy", String(submitting));
  [...form.elements].forEach((control) => { control.disabled = submitting; });
  submitButton.disabled = submitting;

  if (state === "idle") {
    reviewProgress.hidden = true;
    reviewProgress.classList.remove("is-error");
    submitButton.textContent = "开始审校";
    return;
  }

  reviewProgress.hidden = false;
  reviewProgress.classList.toggle("is-error", state === "error");
  if (state === "loading") {
    reviewProgressKicker.textContent = "LIVE REVIEW · RUNNING";
    reviewProgressTitle.textContent = "提交成功，Review Agent 正在分析";
    reviewProgressMessage.textContent = "正在进行风险扫描、证据检索与可靠性判定，请稍候…";
    submitButton.textContent = "正在审校…";
  } else {
    reviewProgressKicker.textContent = "LIVE REVIEW · SAFE STOP";
    reviewProgressTitle.textContent = "无法连接 Review Agent";
    reviewProgressMessage.textContent = message || LIVE_BACKEND_UNAVAILABLE_MESSAGE;
    submitButton.textContent = "重新提交";
  }
}

document.querySelectorAll("[data-open-live]").forEach((button) => {
  button.addEventListener("click", openLiveDialog);
});
document.querySelector("[data-close-live]").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  const values = Object.fromEntries(new FormData(form).entries());
  for (const key of ["brand_or_domain", "context_notes"]) values[key] = values[key]?.trim() || null;
  setReviewSubmissionState("loading");
  try {
    const response = await fetch(`${API_BASE_URL}/api/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.error?.message || LIVE_BACKEND_UNAVAILABLE_MESSAGE);
    const trajectory = assertTrajectory(data?.trajectory);
    renderWorkspace(trajectory, { displayCaseId: data.case_id ? `LIVE · ${String(data.case_id).slice(0, 8)}` : "LIVE" });
    setActiveTab(null);
    replayStatus.textContent = "Live Review 已完成，并在当前工作台中展示。";
    setReviewSubmissionState("idle");
    dialog.close();
    workspace.tabIndex = -1;
    workspace.focus({ preventScroll: true });
    workspace.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  } catch (error) {
    const message = error instanceof TypeError
      ? LIVE_BACKEND_UNAVAILABLE_MESSAGE
      : `${error.message}；本次审校已安全停止，未生成任何替代结论。`;
    setReviewSubmissionState("error", message);
  }
});

window.__REVIEW_DEMO__ = {
  getCurrentTrajectory: () => currentTrajectory,
  loadReplayByIndex: (index) => loadReplay(replayTabs[index]),
};

const defaultReplay = document.querySelector("[data-default-replay]");
if (defaultReplay) loadReplay(defaultReplay);
