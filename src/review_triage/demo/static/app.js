const form = document.querySelector("#review-form");
const landing = document.querySelector("#landing-view");
const architectureView = document.querySelector("#architecture-view");
const resultView = document.querySelector("#result-view");
const submitButton = document.querySelector("#submit-button");
const formStatus = document.querySelector("#form-status");
const replayButtons = [...document.querySelectorAll(".replay-option")];
const replayStatus = document.querySelector("#replay-status");
const viewSwitchButtons = [...document.querySelectorAll("[data-view-target]")];
const evidenceAgentVisual = document.querySelector("[data-evidence-agent]");
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
let evidenceInteractionTimer = null;

const dimensionLabels = {
  TERMINOLOGY: "术语一致性", ACCURACY: "准确性",
  LOCALE: "本地化规范", AUDIENCE: "受众适配性",
};
const severityLabels = { Neutral: "无问题", Minor: "轻微问题", Major: "严重问题", Critical: "极严重问题" };
const routeProductLabels = { AUTO_PASS: "自动通过", SAMPLE_POOL: "抽样复核", HUMAN_REQUIRED: "人工复核" };
const verificationLabels = { AUTO_TRUST: "自动信任", SAMPLE_AUDIT: "抽样复核", HUMAN_VERIFY: "人工确认" };
const processingStatusLabels = { ROUTED: "已完成", NEEDS_CONTEXT: "需要补充上下文", OUT_OF_SCOPE: "暂不支持", PROCESSING_ERROR: "处理未完成" };
const riskLevelLabels = { LOW: "低", MEDIUM: "中", HIGH: "高" };
const evidenceStatusLabels = {
  SUFFICIENT: "已获得并接纳与当前术语判断相关的证据。",
  INSUFFICIENT: "未获得足以支持术语判断的已验证证据，流程已停止自主判断。",
  NOT_REQUIRED: "现有信息足够，本轮无需进入外部术语查证。",
};
const evidenceResultStatusLabels = { HIT: "命中", MISS: "未命中" };
const admissionReasonLabels = {
  ASSESSOR_REJECTED: "相关性或上下文判断未通过",
  SOURCE_NOT_ADMISSIBLE: "来源不满足准入要求",
  NORMATIVE_SUPPORT_UNDECLARED: "来源未声明支持规范性结论",
  TERM_MISMATCH: "术语对象与注册术语不一致",
  TERM_PAIR_NOT_ATTESTED: "原文与译文的术语对应关系未被证据明确支持",
  LOCALE_SCOPE_MISMATCH: "语言或地区范围不匹配",
  AUTHORITY_SCOPE_MISMATCH: "权威主体范围不匹配",
  CLAIM_SCOPE_INVALID: "候选资料无法覆盖当前判断命题",
};
const contentTypeLabels = { MARKETING: "营销文案", CUSTOMER_SUPPORT: "客服话术", UI: "UI 文案" };
const riskReasonDisplayOverrides = {
  "LOW|The source is a short, non-technical marketing message with no high-stakes obligations or instructions. The main potential impact of a mistranslation is reduced marketing effectiveness or slightly confused brand perception, which is low in an ex-ante risk sense.": "这是一条简短的非技术营销信息，不涉及高风险义务或操作指令。若发生误译，主要影响营销效果或品牌认知，因此属于低风险。",
};
const reasonCodeLabels = {
  TERMINOLOGY_HUMAN_VERIFY: "术语判断需要人工确认",
  ACCURACY_BLOCKING_SEVERITY: "准确性维度出现需要阻断的问题",
  ACCURACY_SAMPLE_AUDIT: "准确性维度触发抽样策略",
  LOCALE_SAMPLE_AUDIT: "本地化维度触发抽样策略",
  ALL_DIMENSIONS_NON_BLOCKING_AUTO_TRUST: "四个维度均满足自动信任条件",
};
const routeConclusionLabels = {
  AUTO_PASS: "本案例因此自动通过",
  SAMPLE_POOL: "本案例因此进入抽样复核",
  HUMAN_REQUIRED: "本案例因此交给人工复核",
};
const overrideReasonLabels = {
  TERMINOLOGY_EVIDENCE_INSUFFICIENT: "术语查证未获得足够证据，因此需要人工确认。",
  TERMINOLOGY_EVIDENCE_CONFLICT: "术语证据存在冲突，因此需要人工确认。",
  ACCURACY_UNRESOLVED_EXTERNAL_SUPPORT: "准确性判断仍依赖未解决的外部依据，因此需要人工确认。",
  LOCALE_UNRESOLVED_EXTERNAL_SUPPORT: "本地化判断仍依赖未解决的外部依据，因此需要人工确认。",
  AUDIENCE_UNRESOLVED_EXTERNAL_SUPPORT: "受众适配判断仍依赖未解决的外部依据，因此需要人工确认。",
};
const toolLabels = {
  official_docs: "官方证据检索",
  glossary: "术语表检索",
  case_memory: "历史案例检索",
  search_official_docs: "官方证据检索",
  search_glossary: "术语表检索",
  search_case_memory: "历史案例检索",
};

function text(selector, value) { document.querySelector(selector).textContent = value ?? "—"; }
function make(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
function isUrl(value) { try { const url = new URL(value); return url.protocol === "https:" || url.protocol === "http:"; } catch { return false; } }
function fixtureText(value) { return typeof value === "string" && /offline|离线集成夹具|夹具/i.test(value); }
function dimensionList(items) { return (items || []).map((item) => dimensionLabels[item] || "未标注维度").join("、"); }
function shortCaseId(caseId) { return caseId ? `Case ${String(caseId).slice(0, 8)}` : "—"; }
function policyCellLabel(item) {
  const [dimension, risk] = String(item?.policy_cell || "").split("×");
  const riskLabel = riskLevelLabels[risk] ? `${riskLevelLabels[risk]}风险` : "当前风险";
  return `${dimensionLabels[dimension] || "当前维度"} × ${riskLabel}`;
}

function renderReplayIdentity(metadata) {
  const identity = document.querySelector("#replay-identity");
  identity.hidden = !metadata;
  text("#replay-label", metadata?.label || "");
  text("#replay-description", metadata?.description?.replace(/\bAgent\b/g, "Review Agent") || "");
}

function evidenceCandidateReviews(data) {
  return (data.evidence?.tool_calls || []).flatMap((item) => item.candidate_reviews || []);
}

function evidenceCandidateCount(evidence) {
  const reviews = (evidence?.tool_calls || []).flatMap((item) => item.candidate_reviews || []);
  if (reviews.length) return reviews.length;
  return (evidence?.tool_calls || []).reduce((total, item) => {
    if (item.result_status !== "HIT") return total;
    const match = String(item.result_summary || "").match(/(\d+) candidate/);
    return total + (match ? Number(match[1]) : 1);
  }, 0);
}

function evidenceCandidateStats(data) {
  const evidence = data.evidence;
  const reviews = evidenceCandidateReviews(data);
  const candidateCount = evidenceCandidateCount(evidence);
  const hitCount = (evidence?.tool_calls || []).filter((item) => item.result_status === "HIT").length;
  const assessed = reviews.filter((item) => item.relevant !== null && item.relevant !== undefined);
  const relevant = assessed.filter((item) => item.relevant && item.context_match !== false).length;
  const admitted = reviews.filter((item) => item.admitted === true).length || data.evidence?.verified_evidence?.length || 0;
  const rejected = reviews.filter((item) => item.admitted === false).length;
  return { reviews, candidateCount, hitCount, assessedCount: assessed.length, relevantCount: relevant, admittedCount: admitted, rejectedCount: rejected };
}

function appendEvidenceStatusStep(host, label, technical, state) {
  const step = make("article", `evidence-status-step ${state || ""}`.trim());
  step.append(make("strong", "evidence-status-label", label));
  if (technical) step.append(make("span", "evidence-status-technical", technical));
  host.append(step);
}

function renderEvidenceStatusSummary(data) {
  const section = document.querySelector("#evidence-status-summary");
  const steps = document.querySelector("#evidence-status-steps");
  steps.replaceChildren();
  const hasControl = Boolean(data.post_eval_control);
  const needsEvidence = data.post_eval_control?.terminology_requires_external_evidence === true;
  section.hidden = !hasControl;
  if (!hasControl) return;

  if (!needsEvidence) {
    appendEvidenceStatusStep(steps, "无需外部查证", "Evidence Need Gate", "complete");
    appendEvidenceStatusStep(steps, "Review Agent 直接进入后续判断", "Route", "complete");
    text("#evidence-status-explanation", "当前判断不依赖外部事实，Review Agent 跳过证据查证，直接进入可靠性策略与最终处理。");
    return;
  }

  const stats = evidenceCandidateStats(data);
  const evidence = data.evidence;
  appendEvidenceStatusStep(steps, "需要外部查证", "Evidence Need Gate", "complete");
  appendEvidenceStatusStep(
    steps,
    stats.candidateCount ? `检索命中 ${stats.candidateCount} 条候选` : "尚未检索到候选",
    "Retrieval",
    stats.candidateCount ? "complete" : "pending",
  );
  if (stats.assessedCount) {
    appendEvidenceStatusStep(
      steps,
      `相关性判断 ${stats.relevantCount}/${stats.assessedCount} 条通过`,
      "Assessor",
      stats.relevantCount ? "complete" : "blocked",
    );
  } else {
    appendEvidenceStatusStep(steps, "相关性判断已执行", "Assessor", "complete");
  }
  if (stats.candidateCount || stats.admittedCount) {
    const admissionTotal = stats.candidateCount || stats.admittedCount;
    appendEvidenceStatusStep(
      steps,
      `规范证据准入 ${stats.admittedCount}/${admissionTotal} 条`,
      "Admission",
      stats.admittedCount ? "complete" : "blocked",
    );
  }
  const sufficient = evidence?.status === "SUFFICIENT";
  appendEvidenceStatusStep(steps, sufficient ? "证据充分" : "证据不足", "Sufficiency", sufficient ? "complete" : "blocked");
  appendEvidenceStatusStep(
    steps,
    data.final_route?.code === "AUTO_PASS" ? "Review Agent 完成后续处理" : "必须人工复核",
    "Route",
    data.final_route?.code === "AUTO_PASS" ? "complete" : "blocked",
  );

  const explanation = sufficient
    ? "Review Agent 找到并接纳了能够覆盖当前判断的证据，确定性规则停止继续查证。"
    : stats.candidateCount
      ? "Review Agent 找到了相关候选，但没有把“看起来相关”的资料直接当成可信证据；候选未通过准入，因此安全转交人工复核。"
      : "Review Agent 未获得足以支持当前判断的证据，因此停止自主判断并转交人工复核。";
  text("#evidence-status-explanation", explanation);
}

function setReplayLoading(activeButton = null) {
  for (const button of replayButtons) button.disabled = Boolean(activeButton);
  replayStatus.textContent = activeButton ? "正在加载已验证历史回放…" : "";
  document.querySelector(".replay-selector").setAttribute("aria-busy", String(Boolean(activeButton)));
}

function setActiveNavigation(view) {
  for (const button of viewSwitchButtons) {
    const active = button.dataset.viewTarget === view;
    button.classList.toggle("is-active", active && button.classList.contains("nav-link"));
    if (button.classList.contains("nav-link")) {
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
  }
}

function replayEvidenceInteraction() {
  if (motionPreference.matches || !evidenceAgentVisual) return;
  window.clearTimeout(evidenceInteractionTimer);
  evidenceAgentVisual.classList.remove("is-exploring");
  void evidenceAgentVisual.offsetWidth;
  evidenceAgentVisual.classList.add("is-exploring");
  evidenceInteractionTimer = window.setTimeout(() => evidenceAgentVisual.classList.remove("is-exploring"), 2700);
}

if (evidenceAgentVisual) evidenceAgentVisual.addEventListener("click", replayEvidenceInteraction);

function scrollToLandingTarget(target) {
  target.scrollIntoView({ behavior: motionPreference.matches ? "auto" : "smooth", block: "start" });
  window.setTimeout(() => {
    target.classList.remove("landing-arrival");
    void target.offsetWidth;
    target.classList.add("landing-arrival");
    window.setTimeout(() => target.classList.remove("landing-arrival"), 900);
  }, 520);
}

for (const heroLink of document.querySelectorAll('.hero-actions a[href^="#"]')) heroLink.addEventListener("click", (event) => {
  const target = document.querySelector(heroLink.getAttribute("href"));
  if (!target) return;
  event.preventDefault();
  scrollToLandingTarget(target);
});

for (const button of document.querySelectorAll("[data-scroll-target]")) button.addEventListener("click", (event) => {
  event.preventDefault();
  const target = document.querySelector(button.dataset.scrollTarget);
  if (!target) return;
  showLandingTarget(target);
});

for (const button of document.querySelectorAll("[data-scroll-top]")) button.addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: motionPreference.matches ? "auto" : "smooth" });
});

function showLandingTarget(target) {
  architectureView.hidden = true;
  resultView.hidden = true;
  landing.hidden = false;
  setActiveNavigation("demo");
  window.requestAnimationFrame(() => scrollToLandingTarget(target));
}

function showDemo() {
  architectureView.hidden = true;
  resultView.hidden = true;
  landing.hidden = false;
  setActiveNavigation("demo");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showArchitecture() {
  landing.hidden = true;
  resultView.hidden = true;
  architectureView.hidden = false;
  setActiveNavigation("architecture");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function policyBasisLabel(item) {
  const [dimension, risk] = String(item?.policy_cell || "").split("×");
  const riskLabel = riskLevelLabels[risk] ? riskLevelLabels[risk] + "风险" : "当前风险";
  return riskLabel + " × " + (dimensionLabels[dimension] || "当前维度");
}

function routeExplanation(data) {
  const stats = evidenceCandidateStats(data);
  const route = data.final_route;
  if (route?.code === "HUMAN_REQUIRED" && data.evidence?.status === "INSUFFICIENT" && stats.candidateCount && !stats.admittedCount) {
    return "证据未被接纳，术语判断需要人工进一步确认，本案例因此交给人工复核。";
  }
  const sampleDecision = (data.reliability_decisions || []).find((item) => item.verification_route === "SAMPLE_AUDIT");
  if (route?.code === "SAMPLE_POOL" && sampleDecision) {
    return "本案例“" + policyBasisLabel(sampleDecision) + "”组合按照前置评测结果需要抽样复核。";
  }
  const labels = (data.route_reason_codes || []).map((code) => reasonCodeLabels[code]).filter(Boolean);
  const routeConclusion = route ? routeConclusionLabels[route.code] || "本案例最终进入" + route.label_zh : null;
  if (labels.length) return labels.join("，且") + (routeConclusion ? "，" + routeConclusion : "") + "。";
  return routeConclusion ? "Review Agent 已结合当前审校结果和既定策略完成分诊，" + routeConclusion + "。" : "本轮尚未生成可安全展示的最终分诊。";
}

function renderDrivers(data) {
  const host = document.querySelector("#route-drivers"); host.replaceChildren();
  text("#route-explanation", routeExplanation(data));
  const sampleDecision = (data.reliability_decisions || []).find((item) => item.verification_route === "SAMPLE_AUDIT");
  const policyCopy = sampleDecision
    ? "当前版本采用冻结的“质量维度 × 业务风险”可靠性策略，根据前期评测结果决定各质量维度可以自动信任、需要抽样复核，或必须人工确认。本案例“" + policyBasisLabel(sampleDecision) + "”组合按照前置评测结果需要抽样复核。"
    : "当前版本采用冻结的“质量维度 × 业务风险”可靠性策略，根据前期评测结果决定各质量维度可以自动信任、需要抽样复核，或必须人工确认。";
  host.append(make("p", "driver-policy-copy", policyCopy));
}

function renderCase(data) {
  const host = document.querySelector("#submitted-case"); host.replaceChildren();
  if (!data.case) return;
  const rows = [["英文原文", data.case.source_text], ["候选译文", data.case.translation], ["内容类型", contentTypeLabels[data.case.content_type] || "未标注"]];
  for (const [label, value] of rows) { const dt = make("dt", "", label); const dd = make("dd", "", value); host.append(dt, dd); }
}

function renderRisk(risk) {
  text("#risk-label", risk?.label_zh || "未生成案例风险");
  const displayReason = risk && riskReasonDisplayOverrides[`${risk.level}|${risk.reason}`] || risk?.clarification_question || risk?.reason;
  const hasEnglishRationale = typeof displayReason === "string" && /[A-Za-z]{3,}/.test(displayReason);
  text("#risk-reason", !risk || fixtureText(displayReason) ? "" : hasEnglishRationale ? "Review Agent 已根据原文内容和业务影响完成案例风险判断。" : displayReason);
}

function renderReliability(items) {
  const host = document.querySelector("#reliability-list"); host.replaceChildren();
  if (!items?.length) { host.append(make("p", "quiet", "当前流程未返回维度级决策。")); return; }
  for (const item of items) {
    const row = make("div", "reliability-row");
    const overrideCopy = overrideReasonLabels[item.override_reason];
    row.append(make("strong", "", `${policyCellLabel(item)}${item.override_reason ? " · 安全覆盖" : ""} → ${verificationLabels[item.verification_route] || "待确认"}`));
    if (overrideCopy) row.append(make("p", "", overrideCopy));
    host.append(row);
  }
}

function renderDimensions(items) {
  const host = document.querySelector("#dimension-list"); host.replaceChildren();
  if (!items?.length) { host.append(make("p", "quiet", "当前流程未完成四维质量审校。")); return; }
  for (const item of items) {
    const card = make("article", "dimension"); const header = make("header");
    header.append(make("h3", "", dimensionLabels[item.dimension] || "未标注维度"), make("span", "severity", severityLabels[item.severity] || "待确认")); card.append(header);
    host.append(card);
  }
}

function traceStep(number, title) {
  const step = make("section", "trace-step");
  const marker = make("span", "trace-marker", String(number).padStart(2, "0"));
  const body = make("div", "trace-step-body");
  const heading = make("h3", "", title);
  body.append(heading); step.append(marker, body);
  return { step, body };
}

function appendFact(host, label, value, className = "") {
  if (!value) return;
  const row = make("div", `trace-fact ${className}`.trim());
  row.append(make("span", "trace-label", label), make("p", "", value)); host.append(row);
}

function appendTraceSummary(host, title, copy, className = "") {
  const card = make("article", `trace-card trace-summary-card ${className}`.trim());
  card.append(make("strong", "", title), make("p", "", copy));
  host.append(card);
}

function qualitySummary(items) {
  if (!items?.length) return "本轮没有可展示的四维审校结果。";
  const issues = items.filter((item) => item.severity !== "Neutral");
  if (!issues.length) return "四个质量维度均为无问题。";
  return issues.map((item) => `${dimensionLabels[item.dimension] || "当前维度"}为${severityLabels[item.severity] || "待确认"}`).join("；") + "。";
}

function policySummary(items) {
  if (!items?.length) return "当前流程未返回可展示的可靠性策略。";
  const constrained = items.filter((item) => item.verification_route !== "AUTO_TRUST");
  if (!constrained.length) return "四个维度均满足自动信任条件。";
  return constrained.map((item) => {
    const overrideCopy = overrideReasonLabels[item.override_reason];
    return (overrideCopy || `${policyCellLabel(item)} → ${verificationLabels[item.verification_route] || "待确认"}`).replace(/[。；，]+$/, "");
  }).join("；") + "。";
}

function finalRouteSummary(data) {
  const route = data.final_route;
  if (!route) return "本轮尚未生成最终处理路径。";
  if (route.code === "AUTO_PASS") return "所有维度均满足非阻断与自动信任条件，本案例自动通过。";
  if (route.code === "SAMPLE_POOL") {
    const dimensions = dimensionList(route.sample_audit_dimensions);
    return `${dimensions || "当前维度"}触发抽样策略，最严格路径生效，本案例进入抽样复核。`;
  }
  const dimensions = dimensionList(route.triggering_dimensions);
  return `${dimensions || "当前判断"}触发安全升级，最严格路径生效，本案例交给人工复核。`;
}

function candidateSourceLabel(provenance) {
  return { OFFICIAL_DOCS: "官方资料", GLOSSARY: "术语表", CASE_MEMORY: "已批准历史案例" }[provenance] || "候选资料";
}

function candidateAssessmentLabel(item) {
  if (item.relevant === null || item.relevant === undefined) return "未完成判断";
  if (item.relevant && item.context_match !== false) return "相关";
  return "不采用";
}

function candidateAdmissionLabel(item) {
  if (item.admitted === true) return "已准入";
  if (item.admitted === false) return "未准入";
  return "未完成判断";
}

function candidateAdmissionReasons(item) {
  const reasons = (item.admission_reason_codes || []).map((code) => admissionReasonLabels[code] || code);
  return reasons.length ? reasons.join("；") : item.admitted === true ? "通过当前证据准入规则" : "暂无准入原因记录";
}

function renderEvidenceJudgmentDetails(host, data) {
  const details = make("details", "evidence-judgment-details");
  details.append(make("summary", "", "查看证据判断详情"));
  const body = make("div", "evidence-judgment-details-body");
  const reviews = evidenceCandidateReviews(data);
  if (!reviews.length) {
    body.append(make("p", "trace-empty", "本次历史回放仅保存了聚合判断记录，未保存候选级详情。当前仍可确认：检索结果与最终准入数量均来自 Review Agent 的真实运行记录。"));
  } else {
    for (const item of reviews) {
      const card = make("article", `trace-card candidate-review-card ${item.admitted === true ? "candidate-admitted" : "candidate-rejected"}`.trim());
      const heading = make("div", "trace-card-heading");
      heading.append(make("strong", "", item.candidate_id || "候选资料"));
      card.append(heading, make("span", "feedback-status", candidateAdmissionLabel(item)));
      appendFact(card, "来源", candidateSourceLabel(item.provenance));
      appendFact(card, "候选摘要", item.claim_value || item.content);
      appendFact(card, "相关性判断", `${candidateAssessmentLabel(item)}${item.assessment_reason ? ` · ${item.assessment_reason}` : ""}`);
      appendFact(card, "证据准入", candidateAdmissionReasons(item));
      if (item.admission_policy_version) appendFact(card, "准入规则", item.admission_policy_version);
      if (isUrl(item.source_ref)) { const link = make("a", "evidence-link", "查看来源 →"); link.href = item.source_ref; link.target = "_blank"; link.rel = "noreferrer"; card.append(link); }
      body.append(card);
    }
  }
  details.append(body);
  host.append(details);
}

function evidenceConclusion(item, data) {
  const sourceText = data.case?.source_text?.trim();
  const translation = data.case?.translation?.trim();
  if (sourceText && translation && sourceText.length <= 40 && translation.length <= 40) {
    return `该官方资料支持“${sourceText}”与“${translation}”的对应关系。`;
  }
  return item.relevance_reason?.trim() || "该资料通过证据准入，并支持当前术语判断。";
}

function renderAgentDetail(data) {
  const section = document.querySelector("#agent-detail"); const host = document.querySelector("#agent-trace"); host.replaceChildren();
  const control = data.post_eval_control;
  if (!control && !data.final_route) { section.hidden = true; return; }
  section.hidden = false;

  const quality = traceStep(1, "质量审校");
  appendTraceSummary(quality.body, "四维判断", qualitySummary(data.dimensions), "quality-trace-card");
  host.append(quality.step);

  const evidenceStep = traceStep(2, "证据判断");
  if (control?.terminology_requires_external_evidence !== true) {
    appendTraceSummary(evidenceStep.body, "无需外部查证", evidenceStatusLabels.NOT_REQUIRED, "evidence-bypass-card");
  } else {
    const evidence = data.evidence;
    const terminology = data.dimensions?.find((item) => item.dimension === "TERMINOLOGY");
    const rawTermCandidate = terminology?.details?.term_candidate;
    const termCandidate = typeof rawTermCandidate === "string" && rawTermCandidate.length <= 32 && !/[()（）]/.test(rawTermCandidate) ? rawTermCandidate : null;
    appendTraceSummary(
      evidenceStep.body,
      "进入术语查证",
      termCandidate ? `“${termCandidate}”的判断依赖外部依据，Review Agent 开始查证。` : "术语判断依赖外部依据，Review Agent 开始查证。",
      "evidence-trigger-card",
    );

    const hitCount = (evidence?.tool_calls || []).filter((item) => item.result_status === "HIT").length;
    const admittedCount = evidence?.verified_evidence?.length || 0;
    let evidenceOutcome = "当前结果未返回可展示的证据状态。";
    if (evidence?.status === "SUFFICIENT") evidenceOutcome = "已接纳充分证据，确定性规则停止继续查证，并将证据送入独立术语复评。";
    else if (evidence?.status === "INSUFFICIENT" && hitCount && !admittedCount) evidenceOutcome = "Review Agent 找到了相关候选，但候选没有通过证据准入，不能进入可信证据链，因此停止自主判断。";
    else if (evidence?.status === "INSUFFICIENT") evidenceOutcome = "未获得充分证据，Review Agent 停止自主判断。";
    appendTraceSummary(evidenceStep.body, evidence?.status === "SUFFICIENT" ? "证据充分" : "证据不足", evidenceOutcome, "evidence-outcome-card");

    if (evidenceCandidateReviews(data).length) renderEvidenceJudgmentDetails(evidenceStep.body, data);

    const records = make("details", "evidence-records");
    records.append(make("summary", "", "查看查证记录"));
    const recordsBody = make("div", "evidence-records-body");
    if (evidence?.tool_calls?.length) {
      for (const [index, item] of evidence.tool_calls.entries()) {
        const card = make("article", "trace-card feedback-card");
        const heading = make("div", "trace-card-heading");
        heading.append(make("strong", "", `第 ${index + 1} 次查证`));
        card.append(heading, make("span", "feedback-status", evidenceResultStatusLabels[item.result_status] || "已返回"));
        appendFact(card, "查询内容", item.query);
        recordsBody.append(card);
      }
    } else recordsBody.append(make("p", "trace-empty", "当前结果未返回查证行动记录。"));

    if (evidence?.verified_evidence?.length) {
      for (const item of evidence.verified_evidence) {
        const card = make("article", "trace-card evidence-card");
        card.append(make("p", "trace-card-index", "已接纳证据"));
        appendFact(card, "来源类型", item.provenance === "OFFICIAL_DOCS" ? "官方资料" : "已验证来源");
        appendFact(card, "依据结论", evidenceConclusion(item, data));
        if (isUrl(item.source_ref)) { const link = make("a", "evidence-link", "查看来源 →"); link.href = item.source_ref; link.target = "_blank"; link.rel = "noreferrer"; card.append(link); }
        recordsBody.append(card);
      }
    } else recordsBody.append(make("p", "trace-empty", "本轮没有被接纳为充分依据的证据。"));
    records.querySelector("summary").textContent = "查看 Review Agent 如何逐次调整查询";
    records.append(recordsBody);
    evidenceStep.body.append(records);
  }
  host.append(evidenceStep.step);

  const policy = traceStep(3, "可靠性策略");
  appendTraceSummary(policy.body, "模型判断可以信任到什么程度", policySummary(data.reliability_decisions), "policy-trace-card");
  host.append(policy.step);

  const route = traceStep(4, "最终处理");
  appendTraceSummary(route.body, data.final_route ? routeProductLabels[data.final_route.code] || data.final_route.label_zh : "尚未完成", finalRouteSummary(data), "route-trace-card");
  host.append(route.step);
}

function renderIncomplete(data) {
  const section = document.querySelector("#incomplete-section");
  const incomplete = !data.final_route || ["NEEDS_CONTEXT", "PROCESSING_ERROR", "OUT_OF_SCOPE"].includes(data.processing_status);
  section.hidden = !incomplete;
  if (incomplete) text("#incomplete-message", data.processing_status === "NEEDS_CONTEXT" ? "Review Agent 需要补充业务上下文后，才能生成可安全展示的审校结论。" : "当前 Case 尚未产生可安全展示的最终分诊。");
}

function renderResult(data, presentation = {}) {
  const route = data.final_route;
  document.querySelector("#result-hero").dataset.route = route?.code || "REVIEW_INCOMPLETE";
  text("#route-title", route ? routeProductLabels[route.code] || route.label_zh : "审校未完成");
  const displayCaseId = presentation.displayCaseId || data.display_case_id || shortCaseId(data.case_id);
  text("#case-id", displayCaseId);
  text("#processing-status", processingStatusLabels[data.processing_status] || "已完成");
  renderDrivers(data); renderCase(data); renderRisk(data.risk); renderReliability(data.reliability_decisions); renderDimensions(data.dimensions); renderEvidenceStatusSummary(data); renderAgentDetail(data); renderIncomplete(data);
  landing.hidden = true; architectureView.hidden = true; resultView.hidden = false; setActiveNavigation("demo"); window.scrollTo({ top: 0, behavior: "smooth" });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault(); if (!form.reportValidity()) return;
  submitButton.disabled = true; formStatus.textContent = "正在执行真实模型审校，请勿重复提交。模型与网络响应可能需要一定时间。";
  try {
    const values = Object.fromEntries(new FormData(form).entries());
    for (const key of ["brand_or_domain", "context_notes"]) values[key] = values[key].trim() || null;
    const response = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
    const data = await response.json(); if (!response.ok) throw new Error(data.error?.message || "请求失败"); renderReplayIdentity(null); renderResult(data);
  } catch (error) {
    renderReplayIdentity(null); renderResult({ processing_status: "PROCESSING_ERROR", final_route: null, route_reason_codes: [], dimensions: [], reliability_decisions: [], evidence: null, processing_error: { code: "REQUEST_FAILED", message: error.message }, case: null, risk: null });
  } finally { submitButton.disabled = false; formStatus.textContent = ""; }
});

for (const button of replayButtons) button.addEventListener("click", async () => {
  setReplayLoading(button);
  try {
    const response = await fetch(button.dataset.replayUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(`Replay fetch failed: ${response.status}`);
    const snapshot = await response.json();
    if (snapshot?.replay_metadata?.type !== "VERIFIED_REPLAY" || !snapshot.result) throw new Error("Invalid replay snapshot");
    renderReplayIdentity(snapshot.replay_metadata); renderResult(snapshot.result, { displayCaseId: snapshot.replay_metadata.display_case_id || button.dataset.displayCaseId });
  } catch {
    replayStatus.textContent = "示例案例加载失败，请稍后重试。";
  } finally {
    for (const replayButton of replayButtons) replayButton.disabled = false;
    document.querySelector(".replay-selector").setAttribute("aria-busy", "false");
  }
});

for (const button of viewSwitchButtons) button.addEventListener("click", () => {
  if (button.dataset.viewTarget === "architecture") showArchitecture();
  else showDemo();
});

for (const button of document.querySelectorAll(".new-case")) button.addEventListener("click", () => {
  renderReplayIdentity(null);
  setReplayLoading();
  showLandingTarget(document.querySelector("#verified-replays"));
});
