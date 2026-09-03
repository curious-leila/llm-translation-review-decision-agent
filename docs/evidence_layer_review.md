# 面向大模型译文的审校决策 Agent：证据层设计闭环复盘

> **总命题：证据层的目标不是“让模型更会搜”，而是把“什么时候需要查证、查什么、什么能算证据、什么时候证据够、谁有权停止、证据如何影响最终自动化权限”拆成可验证、可审计、可解释的产品决策链。**

---

## 1. 证据层总设计：取证权、判断权、放行权必须分开

**核心分论点：真正需要治理的不是“模型会不会找资料”，而是模型能被授予多大的自主权；因此取证权 ≠ 判断权 ≠ 放行权。**

### 情境

在翻译审校场景里，语言模型可以判断“这句话可能有术语问题”，也可以主动去找外部资料。但如果模型既负责提出问题、又负责找证据、再自己决定证据是否足够、最后还自己放行，就等于“模型给自己发通行证”。

### 任务

把整个证据链拆成不同职责，让每一层只拥有必要权限，并确保任一环节失败时都能安全退出，而不是继续自动化。

### 动作

当前架构将证据相关职责拆为：

- **证据需求门控**：判断当前问题是否需要外部世界；
- **动态证据查证器**：决定搜什么、怎么继续搜；
- **证据检索**：把自然语言查询映射到受控证据候选；
- **语义评估**：判断候选与当前问题是否相关；
- **规范证据准入**：用确定性规则判断候选有没有资格成为可信证据；
- **证据充分性判断**：判断当前未决问题是否已被可信证据覆盖；
- **停止规则**：证据充分后由规则接管停止权；
- **证据增强术语复评**：证据回流后重新做术语判断；
- **可靠性策略与最终路由**：最终决定自动通过、抽样复核或人工复核。



### 结果

系统形成了“模型负责不确定性探索，规则负责安全边界”的职责分层。即使模型找到候选，也不能直接把候选升级成可信证据，更不能直接决定最终放行。

### 产品意义

这条原则贯穿整个产品：  
**模型可以拥有探索权，但不能同时拥有证据资格认定权和最终放行权。**

---



## 2. 受控证据包（Evidence Pack）：先定义一个可验证的小世界，再谈 Agent 能力

**核心分论点：证据环境的第一目标不是覆盖所有知识，而是建立一个最小、受控、可冻结、可复现的证据世界，让系统行为可以被归因。**

### 情境

如果一开始就让 Agent 直接访问开放互联网，任何失败都可能同时来自网页变化、搜索引擎结果、抓取失败、证据质量、检索算法、模型判断或停止逻辑，无法判断到底是哪一层出了问题。

### 任务

为证据层建立一个足够小、但能覆盖关键产品行为的受控环境。

### 动作

冻结 Demo Evidence Pack v1，包含 Signal、PayPal、TENCEL 三个来源族：

- 12 条正向规范事实；
- 2 条负向控制；
- 共 14 个证据事实/控制项。

其中 TENCEL 包含：

- TEN-01：TENCEL™ → 天丝™；
- TEN-02：TENCEL™ Lyocell fibers → 天丝™莱赛尔纤维；
- TEN-03：TENCEL™ Modal fibers → 天丝™莫代尔纤维；
- TEN-04：TENCEL™ Studio → 天丝™工作室。

同时保留 Brooklinen、Flodesk 等负向控制，用于验证“看起来相关”不等于“可以作为规范证据”。

### 结果

证据包不是“知识库覆盖率数据集”，而是一个**机制验证环境**，用来验证四类行为：

1. 应当接受的证据能否进入系统；
2. 不应接受的证据能否被拒绝；
3. 超出覆盖范围时能否安全弃权；
4. 证据充分后能否及时停止。



### 产品意义

产品上最重要的不是“我有多少条资料”，而是：  
**在一个可控世界里，我能证明 Agent 的自主行为边界是正确的。**

---



## 3. 证据加载（Loader）：冻结事实必须原样进入运行时

**核心分论点：证据加载层的职责不是“理解证据”，而是把人工审核后冻结的证据包原样、可验证地读进系统。**

### 情境

如果加载阶段擅自改写、归一化或重新推断证据事实，那么后续即使检索和准入都正确，也无法证明运行时看到的内容就是当初冻结的内容。

### 任务

建立一个尽可能“笨”的加载层：只负责读取、校验和提供冻结证据，不参与证据判断。

### 动作

实现 Verified Demo Evidence Loader：

- 从冻结 artifact 中加载受控证据；
- 保持证据 ID、来源引用、规范事实、适用范围等字段；
- 不在 Loader 中做检索、准入或充分性判断；
- Loader 与 Retrieval、Admission 明确分层。



### 结果

证据来源与运行时之间形成了稳定的数据入口，后续任何命中、拒绝或停止都可以回溯到同一份冻结事实。

### 产品意义

Loader 的产品意义不是“工程分层好看”，而是：  
**先保证系统读到的事实没有被偷偷改变，后面的每一次产品判断才有审计价值。**

---



## 4. 证据需求门控（Evidence Need Gate）：决定 Agent 有没有“出场权”

**核心分论点：Agent 的安全边界不仅在 Agent 内部，“谁决定什么时候调用 Agent”本身也是自主权治理的一部分。**

### 情境

并不是所有翻译问题都需要外部证据。如果所有案例都进入 Agent，会增加成本、延迟和不必要的复杂度；但如果真正需要外部事实的案例被门控漏掉，后面的检索、准入、充分性和停止规则全部不会执行。

### 任务

让系统先判断：“这个判断是否必须依赖外部世界？”

### 动作

在四维评估之后加入 Post-Eval Control：

- Terminology 判断 `requires_external_evidence`；
- 其他维度标记 `unresolved_external_support`；
- 只有 Terminology 明确需要外部证据时才进入动态证据查证 Agent。

Gate v3 曾在开发集首次测试达到 100% 召回，但重复运行出现 80%–100% 的单轮波动。角色标签方案也做过只读/诊断实验，最终判定不值得继续扩大。

### 真实运行结果

同一个 MKT-020 在真实重复运行中出现过：

- 一次 Gate = TRUE，成功进入 Agent；
- 一次 Gate = FALSE，Evidence 直接为 null，最终 AUTO_PASS；
- 后续又出现 Gate = TRUE，再次进入 Agent。

这说明当前 Gate 是一个有运行波动的 LLM 语义判断器，而不是确定性规则。

### 产品意义

这暴露出一个比“Agent会不会搜”更重要的产品风险：

- **Gate 假阳性**：本来不用查，却启动 Agent，主要损失是成本和效率；
- **Gate 假阴性**：本来应该查，却没有启动 Agent，会绕过整个证据安全链，风险更高。

因此未来产品化方向应偏向：

- 召回优先；
- 对高风险规范术语增加确定性安全兜底；
- 不让一次随机的 LLM 判断拥有完全的“不查证权”。

当前阶段不再把 Gate 扩成新的工程子项目，而是把它明确记录为 Live 可靠性边界。

---



## 5. 原文术语契约（Exact-span Contract）：决定“查谁”之前，先把查证对象说清楚

**核心分论点：如果上游连“待查术语是谁”都没有定义清楚，后面的 Agent 搜得越积极，风险反而越大。**

### 情境

真实 MKT-020 运行中，Post-Eval 曾输出：
`COOL TENCEL™ (specifically the TENCEL™ brand component)`

这个输出从人类角度“意思差不多”，但下游 Admission 需要严格匹配冻结事实中的：
`TENCEL™`

于是 Retrieval 已经找到了 TEN 候选，Assessor 也认为相关，但 Admission 全部拒绝：

- TERM_MISMATCH；
- TERM_PAIR_NOT_ATTESTED。



### 任务

解决 LLM 自然语言输出与严格证据准入之间的语义契约错位，但不能通过放宽 Admission 来“迁就模型”。

### 动作

版本化升级 Post-Eval Prompt 到 v4：

- `term_candidate` 必须表示“最小、连续、逐字复制自 source_text 的待查术语”；
- 解释性信息放到 `evidence_need`；
- 加入简单的确定性“原文连续片段校验”：
  - 大小写严格；
  - 保留 ™ / ®；
  - 必须真实存在于 source_text；
  - 不自动纠正、不模糊抽取、不根据 Evidence Pack 反推。

如果校验失败：

- 不进入 Agent；
- tool_call_count = 0；
- 直接 ABSTAIN；
- 最终进入人工复核。



### 真实运行结果

后续真实 Live 中：

- `term_candidate = TENCEL™`；
- v4 Prompt hash 正确；
- `TENCEL™` 确实连续存在于原文；
- Evidence Loop 实际执行了 4 次工具调用。

因此 Prompt v4 + 原文连续片段契约已在真实 Live 中得到验证。

### 产品意义

这里没有把“Exact-span Validator”包装成复杂技术，而是一个非常简单的产品安全门：

**模型可以决定查什么，但必须先把查证对象定义清楚；如果连对象都不清楚，就不允许 Agent 继续搜。**

---



## 6. 动态证据查证器：环境反馈改变下一动作

**核心分论点：Agenticity 不来自“调用了模型”，而来自工具结果真正进入工作状态并改变下一动作。**

### 情境

如果每个案例都固定执行“搜官方文档 → 搜词表 → 搜记忆 → 总结”，本质上只是固定工作流，不需要 Agent。

### 任务

只在 Terminology 需要外部事实时，赋予一个受控的动态探索能力。

### 动作

当前 Agent 的可见动作空间被收缩为：

- `SEARCH_OFFICIAL_DOCS(query)`：唯一真实搜索工具；
- `STOP_SUFFICIENT`：证据充分后停止；
- `ABSTAIN`：证据不足或预算耗尽时弃权。

Agent 负责：

- 生成 query；
- 根据上一轮 HIT / MISS 改写下一轮 query；
- 决定继续搜索还是弃权。

Agent 不负责：

- 修改最终 severity；
- 决定证据是否具备规范资格；
- 决定最终 AUTO_PASS。



### 真实运行结果

MKT-020 的多个 Live Run 中，Agent 在连续 MISS 后改变了查询表达，证明“工具结果改变下一动作”的动态循环真实存在。

### 产品意义

当前产品不是聊天型 Agent，而是嵌入结构化审校工作流中的**动态证据查证 Agent**。  
它的自主权被限制在“不确定性探索”，而不是最终判断。

---



## 7. 证据检索（Retrieval）：从自由文本身份门控，收敛为术语锚定候选检索

**核心分论点：真实 Live 最终证明，Retrieval 的主要问题不是“少几个关键词”，而是自由文本 Query 被错误赋予了过多身份安全职责；最新实现已把“查谁”重新交给经过 Exact-span 校验的** `term_candidate`**，Query 只保留在合法候选范围内的探索/排序作用。**

### 7.1 早期真实失败：Evidence Pack 明明有 TEN-01，Agent 仍连续 MISS

第一轮真实 MKT-020 中，Evidence Pack 已包含 TENCEL 事实，但 Agent 的自然语言 Query 连续 4 次 MISS。

排查先后暴露：

1. trademark / NFKC 归一化边界问题；
2. “官方 / 中文名称”等意图词被误当成实体身份；
3. `兰精` 与 `lenzing` 的 authority alias 不一致；
4. “商标 / 中国 / 官方中文品牌名”等 scope / claim 表达被当成硬身份 token。

对应小修：

- `1f738b1 fix: support natural evidence search queries`
- `814d3d5 fix: separate retrieval identity from query intent`

这些修复保留了安全边界，没有退成 OR、fuzzy 或 substring。

### 7.2 关键架构发现：`term_candidate` 没丢，丢在 Evidence Loop → Tool 接口

只读审计确认：

`term_candidate` 一直存在于 `TerminologyEvidenceState`，Selector 也能看到；真正的丢失点是 Evidence Loop dispatch 仍只调用：

`tool(decision.query or "")`

因此旧 Tool / Retrieval 只拿到自由文本 `query`，没有拿到已经通过 Exact-span Contract 的 `term_candidate`。

这意味着旧 Retrieval 同时承担了两个职责：

1. Candidate Retrieval（候选召回）；
2. 从自由文本 Query 重新推断并强制验证“查谁”。

而这与既有架构重复：

- Exact-span 已经负责确定查证对象；
- Admission 已经负责证据资格。



### 7.3 最新实现：**术语锚定 + Query 导向的候选检索**

最终采用：

**术语锚定 + Query 导向的候选检索（Anchor-Constrained, Query-Guided Retrieval）**

责任链冻结为：

**原文术语契约（Exact-span） → 确定查谁**  
检索层（**Retrieval） → 在合法对象范围内找候选证据**  
语义评估（**Assessor） → 是否相关**  
证据准入（**Admission） → 是否有资格**  
充分性（**Sufficiency） → 是否足够**

具体实现：

- `term_candidate` 从 deterministic Evidence State 直接注入 `SEARCH_OFFICIAL_DOCS`；
- Tool interface 向后兼容为 `search_official_docs(query, *, term_candidate=None)`；
- exact anchor 只用 frozen positive fact 的 `source_term` 做完整 normalized equality；
- normalization 复用已有 trademark / NFKC / case / whitespace 规则；
- 只有 exact anchor 成功后，才允许同 `evidence_family` 的单向 descendant expansion；
- Query 只能影响合法 scope 内的排序/探索，不能扩大 scope；
- Assessor / Admission / Sufficiency / Stopping 均未放宽。

安全反例：

- `TENCEL™` → exact anchor TEN-01，合法 TEN scope；
- `TENCEL™ Studio` → TEN-04 only；
- `COOL TENCEL™` → MISS；
- `Save` → SIG-01 only；
- `pending` → PP-01 only；
- `Flodesk Studio` → MISS；
- TENCEL anchor + Flodesk/未知 Query 也不能跳出 TEN scope。

`d5bcbe370530fe2bae24cc812b710f400c7c5826 fix: anchor evidence retrieval to validated terms`

回归结果：

**207/207 tests PASS，**`git diff --check` **PASS。**

4 条历史真实 MKT-020 Query 在 `term_candidate=TENCEL™` 下均能 deterministic HIT，并包含 TEN-01。

### 7.4 Query 的真实产品意义：表达当前查证意图，而不是重新认证身份

最新 Agenticity 审计证明：

不同 Query 对 `term_candidate=TENCEL™` 返回的 candidate set 实际相同，只改变排序：

- Studio-oriented → TEN-01, TEN-04, TEN-02, TEN-03
- Lyocell-oriented → TEN-01, TEN-02, TEN-03, TEN-04
- official Chinese brand-form → TEN-01, TEN-02, TEN-03, TEN-04

全部 candidates 会进入 Assessor 和 Admission；当前没有 top-k、candidate-level early stop 或分页。因此：

- **Decision-level Agenticity：成立**
- **Retrieval-level Agenticity：不成立**
- 当前最准确定位：**Bounded Evidence Agent / 受控 Agentic Workflow**
- 不能宣称“Agent 通过多轮 Query 不断探索出新证据集合”。

Query 现在的真实意义是：

1. Agent 对“本轮想查什么”的行动表达；
2. 合法 anchor scope 内的候选排序信号；
3. ToolCall / Audit 的解释信息。

不再为了强化 Agent 标签增加 top-k、更多 Tool 或人为制造 Observation 差异。当前 Evidence Pack 本来就是一个小而可控的证据环境，不承担开放式 Web Research 的证明任务。

### 7.5 产品意义

这次修改真正修正的是**职责边界**，不是为了强行把 MKT-020 调绿：

> **已经确定“查谁”以后，检索层不应再靠 LLM 的整句自由文本重新猜“查谁”。**

同时接受一个真实边界：

> 当前 Agent 的自主权主要体现在受控决策循环，而不是开放式、多跳的 Retrieval exploration。

这比为了“看起来更 Agent”继续增加没有用户价值的机制更可信。

## 8. 语义评估（Assessor）：相关不等于有资格成为规范证据

**核心分论点：LLM 可以判断“这个候选和当前问题像不像”，但不能因为“相关”就把候选升级成可信规范证据。**

### 情境

第二次 MKT-020 Live 中，Retrieval 曾真实 HIT TEN-01 至 TEN-04，Assessor 对 4 个候选均给出：

- relevant = true；
- context_match = true。

但 Admission 最终全部拒绝，因为当时 `term_candidate` 仍是复合解释文本。

### 任务

保持“语义相关性”和“证据资格”分离。

### 动作

Assessor 只回答：

- 这个候选是否与当前问题相关；
- 上下文是否匹配。

它不能决定：

- 是否满足术语身份契约；
- 是否满足 locale / authority / source / claim scope；
- 是否可成为 verified evidence；
- 是否已经 sufficient。



### 结果

真实 Live 证明：即使 Assessor 认为 4 个候选都相关，Admission 仍然可以全部拒绝。

### 产品意义

这非常直接地证明了：
**LLM 的“看起来合理”不能替代产品的证据资格规则。**

---



## 9. 规范证据准入（Normative Evidence Admission）：找到候选不等于拿到可信证据

**核心分论点：Admission 的职责是回答“这条候选有没有资格用于当前未决问题”，而不是回答“它看起来像不像答案”。**

### 情境

如果 Retrieval HIT 就直接写入 verified_evidence，那么搜索召回和事实可信度会被混为一谈，任何宽松检索都会直接污染后续判断。

### 任务

建立严格的 Normative Evidence Admission（规范证据准入）安全门。

### 动作

准入概念上经过多道门：

- **term**：当前术语身份必须匹配注册事实；
- **locale**：语言 / 地区范围一致；
- **authority**：权威主体有效；
- **context**：当前 Case 与候选事实上下文匹配；
- **source**：来源必须属于冻结、允许的官方来源；
- **term-pair attestation**：原文和译文片段真实支撑冻结术语对；
- **claim / scenario / scope**：当前未决 Claim 必须落在同一规范事实范围内。

严格规则不会因为 Compound phrase（复合短语）含有一个已知子词就自动继承证据：

- `TENCEL™` 可以匹配 TEN-01；
- `COOL TENCEL™` 不能自动继承 `TENCEL™ → 天丝™`。



### 结果

真实运行曾出现：

- Retrieval HIT；
- Assessor positive；
- Admission 仍全部拒绝。

说明三层职责没有被偷懒合并。

### 产品意义

**Retrieved ≠ Admitted。**  
找到候选只是“有东西可看”，准入通过才意味着“这条东西有资格进入可信证据链”。

---



## 10. 证据单元与充分性（Evidence Unit / Sufficiency）：一条证据到底是什么，什么时候才算“够”

**核心分论点：Sufficiency 不能简单理解成“搜到一张网页”，它依赖一个被人工冻结、带明确适用范围、由来源链支撑的规范事实单元。**

### 情境

TEN-01 如果被描述成“搜到一个网页，所以证据够了”，会让产品显得非常草率。

### 任务

定义 Evidence Unit（证据单元）到底是什么，以及“一条 admitted evidence 就 sufficient”在什么条件下才成立。

### 动作

冻结定义：

**Evidence Unit = 一个经过人工批准、带明确 scope、由全部 recorded supporting sources 支撑的 scoped normative fact。**

TEN-01 不是网页，而是一个限定范围规范事实：

- source_term = TENCEL™；
- target_form = 天丝™；
- authority_scope = Lenzing / TENCEL 的中文品牌形式；
- locale = en→zh-CN；
- claim = official_chinese_brand_form；
- scenario = MARKETING_BRAND；
- supporting sources 包括英文官网、中文官网、第一方商标材料。

当前 strict Sufficiency 规则保持简单：

- verified evidence 非空；
- 无 conflict；
- 至少有一条当前策略下 admitted normative evidence；
- 该事实覆盖当前 unresolved claim。



### 边界

TEN-01 可以支持：
“在 Lenzing / TENCEL 的 zh-CN 语境中，天丝™是官方使用的中文品牌形式。”

但不能支持：

- 唯一、强制的官方中文名；
- 所有语境都必须替换；
- 整个 `COOL TENCEL™` 产品名应该如何处理。



### 产品意义

**Admitted ≠ Sufficient。**  
“有资格”只代表证据可以进入决策；“充分”还要求它真的覆盖当前未决问题。

---



## 11. 停止权（Stopping Ownership）：证据够了以后，不再把是否继续搜索交给模型

**核心分论点：需要不确定性探索时给模型自主权；一旦确定性充分条件成立，停止权必须由 Rule 接管。**

### 情境

历史 UI-003 中，第一次工具结果已经拿到足够证据，但旧逻辑仍允许 LLM 继续搜索，最终进行了 4 次工具调用后才弃权。

### 任务

解决 stopping ownership（停止权归属）错误：当系统已经能确定“证据够了”，不应继续让模型自由决定是否还要搜。

### 动作

增加确定性 stopping rule：

- verified_evidence 非空；
- 无 conflict；
- 至少存在符合条件的官方规范证据；
- 条件一旦满足，立即 `STOP_SUFFICIENT`。



### 结果

历史案例由：
4 calls → 1 call。

真正价值不是“成本减少 75%”，而是：
**Agent 行为终于服从 Evidence State，而不是服从模型继续探索的冲动。**

### 产品意义

这是“模型不能给自己发通行证”的另一面：
模型也不能在确定性安全条件已经成立后无限扩张自主行为。

---



## 12. 证据增强术语复评（NODE02A）：证据可以改变判断，但 Agent 不能直接改最终结论

**核心分论点：证据 Agent 只负责取证，证据必须重新进入独立判断层，不能由 Agent 直接篡改 severity。**

### 情境

如果 Agent 一旦找到证据就直接把 Terminology 改成 Neutral，本质上仍然是“搜证者自己判案”。

### 任务

让证据真正改变模型判断，同时保持角色分离。

### 动作

引入 NODE02A：
**证据增强术语复评**

它位于：
Evidence sufficient → NODE02A → Reliability Policy

NODE02A 接收 verified evidence 后重新做术语判断。Agent 本身不直接修改 severity。

### 结果

职责链变成：

- Agent：找证据；
- Admission / Sufficiency：判断证据资格和充分性；
- NODE02A：用可信证据重做术语判断；
- Policy / Route：决定自动化权限。



### 产品意义

**证据可以影响判断，但“谁找到证据”和“谁基于证据下判断”不能是同一个角色。**

---



## 13. 可靠性策略与最终路由（Reliability Policy / Route）：证据不是终点，自动化权限才是终点

**核心分论点：整个产品最终不是为了给出一个更漂亮的质量分，而是为了决定“模型应该被信任到什么程度”。**

### 情境

即使四维全部 Neutral，也不代表一定能 AUTO_PASS；如果关键判断仍依赖未解决的外部事实，系统仍应升级人工。

### 任务

把模型判断、证据状态和历史可靠性映射成具体自动化权限。

### 动作

Reliability Policy 使用：

- AUTO_TRUST；
- SAMPLE_AUDIT；
- HUMAN_VERIFY。

Route Aggregation 再映射到：

- AUTO_PASS；
- SAMPLE_POOL；
- HUMAN_REQUIRED。

任何：

- HUMAN_VERIFY；
- Major / Critical；
- 证据不足；
- unresolved external support；
都可以升级人工。



### 结果

真实 MKT-020 多次在证据不足时进入 HUMAN_REQUIRED，说明“模型本身觉得 Neutral”并不能绕过证据缺口。

### 产品意义

**评测的终点不是准确率，而是授予模型多大的自动化权限。**

---



## 14. 来源可追溯（Source Traceability）：可信事实还需要能解释“凭什么信”

**核心分论点：事实本身可信，不等于来源链展示已经足够；公开产品还需要区分“记录过来源”和“保存了原始文件”。**

### 情境

TEN-01 的冻结记录引用了多个第一方来源，其中包括 Lenzing/TENCEL 官方 PDF。但 repo 中并没有保存原始 PDF 字节、来源级冻结 hash 或完整的人审日志。

### 任务

在不篡改 frozen artifact、不假装保存过原始文件的前提下，提高来源可追溯性。

### 动作

新增完整 source traceability catalog：

- 登记全部 13 个 Demo Evidence Pack v1 来源文档；
- TEN-01 的 3 个来源做当前重新定位和验证；
- 其余来源标记 `NOT_REVERIFIED_THIS_ROUND`；
- 明确：
  - raw_copy_saved = false；
  - frozen_source_hash_available = false；
- 不把当前在线 hash 伪装成冻结期 hash；
- 不修改 frozen snapshot。



### 结果

Evidence Pack 回答“系统批准了什么事实”；Source Catalog 回答“这些事实来自哪里、当前还能不能追溯”。

### 产品意义

这体现一个重要可信设计：
**不能因为产品需要一个漂亮故事，就把“当前能重新找到”包装成“当时已经完整保存和审计”。**

---



## 15. Provider 失败：最新两次 Live 没有验到 Retrieval，而是死在 Post-Eval Provider

**核心分论点：最新 Anchor Retrieval commit 后的两次真实 acceptance 都在进入 Retrieval 之前被 Provider 故障截断，因此它们不能作为 Retrieval FAIL，也不能作为真实 Evidence Success。**

### 15.1 已知 Provider failure 类型

此前真实运行已经出现过：

- schema mismatch；
- `PROVIDER_EMPTY_CONTENT`；
- `PROVIDER_NETWORK_ERROR`。

系统统一 fail-closed：

- `STOP_PROCESSING`
- 不生成错误的 route
- 不把坏输出继续送入自动化链



### 15.2 Anchor Retrieval commit 后第一次 acceptance

Commit：

`d5bcbe370530fe2bae24cc812b710f400c7c5826`

Case：

`8f65e208-87be-4f77-84a7-9c454be8abd8`

结果：

- DeepSeek / `deepseek-v4-flash`
- 死在 `NODE-02-POST-EVAL-CONTROL`
- `PROVIDER_NETWORK_ERROR`
- Gate 未产生
- `term_candidate` 未产生
- NODE03 未启动
- Tool calls = 0
- Retrieval 未执行

因此这轮分类应是：

**OPERATIONALLY INCONCLUSIVE / Retrieval NOT TESTED**

不能把 Anchor Retrieval 写成 NO-GO。

### 15.3 手工终端 replacement run

Case：

`7ffef8c4-b3ed-47f6-89c9-874ffebbca7c`

结果：

- 同样死在 `NODE-02-POST-EVAL-CONTROL`
- `PROVIDER_EMPTY_CONTENT`
- Gate 未产生
- `term_candidate` 未产生
- NODE03 未启动
- Tool calls = 0
- Retrieval 未执行
- final route = null
- safe disposition = `STOP_PROCESSING`

这个 failure class 在 Anchor Retrieval commit 之前就曾出现，因此没有证据支持“本轮 Retrieval 修改引入了这个错误”。

### 15.4 当前产品判断

这两次 Run 证明的是：

**Public / Real-time Live Runtime 稳定性目前不足。**

它们没有证明：

- Anchor Retrieval 失败；
- TEN-01 不可达；
- `™` 导致错误；
- API key 无效。

上午历史 Live 已经真实跑过包含 `TENCEL™` 的相同 Case，并走到 Gate / NODE03 / Tool，因此 `™` 不是已知致命因素，Provider 也并非完全不可调用。

### 产品意义

真正的产品要求不是“Provider 永不失败”，而是：

1. Provider坏输出时安全停止；
2. 不把基础设施故障伪装成业务决策；
3. Demo公开版不要把稳定性赌在实时第三方 Provider 上。



## 16. 当前证据层最终验收结论：确定性机制 GO，实时成功 Case 仍缺失，Evidence 工程应 Freeze

**核心分论点：截至当前，Evidence Layer 已经证明安全机制和确定性 Retrieval contract 成立，但仍没有一条基于最新代码的真实 Live 成功证据闭环；继续重复 Live 已经主要是在赌 Provider，而不是验证新的产品假设。**

### 已通过

1. Evidence Pack / Loader 冻结；
2. Evidence Need Gate 有真实触发记录，但存在波动；
3. Exact-span Contract 已实现并真实通过；
4. `term_candidate` 字段契约已冻结；
5. Term-Anchored Retrieval 已正式实现并 commit；
6. 207/207 deterministic tests PASS；
7. 历史真实 MKT-020 Query 在新 Retrieval 下全部 deterministic HIT TEN-01；
8. `COOL TENCEL™` / `Flodesk Studio` 等安全反例通过；
9. Assessor 与 Admission 分层；
10. Admission 未为 MKT-020 放宽；
11. Evidence Unit / Sufficiency 定义冻结；
12. Stopping ownership 4→1 决策成立；
13. NODE02A 与 Agent 权限分离；
14. Reliability Policy / Route 仍掌握放行权；
15. Source Traceability 边界明确；
16. Provider / schema 错误均 fail-closed；
17. Evidence不足会 ABSTAIN / HUMAN_REQUIRED，而不是伪造成功。



### 尚未通过 / 未被证明

1. **最新** `d5bcbe3` **之后，没有真实 Live 走到 Retrieval。**
2. 因此最新 Anchor Retrieval 的真实 Provider acceptance 是 **NOT TESTED**，不是 FAIL。
3. 当前仍没有一条当前版本 MKT-020 的真实：
  `Gate → Agent → HIT TEN-01 → Admission → SUFFICIENT → STOP → NODE02A`
   成功闭环。
4. Retrieval-level Agenticity 未成立；Query 当前不会打开新的 candidate set。
5. Gate 和 Provider 都存在真实运行波动。
6. Public Live 不适合作为默认公开 Demo。



### 当前最终判定

- **Evidence Safety Closure：GO**
- **Deterministic Mechanism Validation：GO**
- **Anchor Retrieval deterministic validation：GO**
- **Anchor Retrieval real-live acceptance：NOT TESTED**
- **Decision-level Agenticity：GO（受控、窄域）**
- **Retrieval-level Agenticity：NO-GO**
- **Live Evidence Resolution：NOT PROVEN**
- **Public Live as Default Demo：NO-GO**



### 当前 Freeze 决策

**Evidence 工程现在停止。**

不再继续：

- modifier / alias patch；
- Query materiality patch；
- top-k；
- 新 Tool；
- 扩大 Evidence Pack；
- 放宽 Admission；
- 新 RAG / vector DB；
- 为了得到成功 Case 重复 Live；
- 把 Provider随机性当成后端功能继续修。

后续如果恢复 P1 工程，优先项才是：

1. Provider operational reliability；
2. 更正式的 structured Tool Contract；
3. 更丰富、可产生实质新 Observation 的 evidence environment。

当前阶段不做。

## 17. 证据层最重要的产品决策总表


| 层              | 核心问题          | 产品决策                         | 产品意义                  |
| -------------- | ------------- | ---------------------------- | --------------------- |
| Evidence Pack  | 如何控制变量        | 先冻结最小受控证据环境                  | 让失败可归因                |
| Loader         | 如何保证运行时事实未被改写 | 只加载，不判断                      | 保证审计可信                |
| Gate           | 什么时候调用 Agent  | 只在需要外部事实时触发                  | 控制成本与自主权，但需防假阴性       |
| Span Contract  | 到底查谁          | term_candidate 必须是原文连续片段     | 不让模糊对象进入检索            |
| Agent Loop     | 为什么需要 Agent   | 只有工具反馈改变下一动作才使用              | 自主权只用于不确定性探索          |
| Retrieval      | 如何触达候选        | 严格身份匹配，不用 OR / fuzzy         | 防止召回扩张污染证据            |
| Assessor       | 候选是否相关        | LLM 判断相关性                    | 让语义判断与安全规则分工          |
| Admission      | 候选是否有资格       | 确定性规范证据准入                    | Retrieved ≠ Admitted  |
| Evidence Unit  | 一条证据是什么       | 人工冻结、带 scope、由来源链支撑的规范事实     | 避免“一张网页=证据”           |
| Sufficiency    | 什么时候证据够       | admitted fact 必须覆盖当前未决 claim | Admitted ≠ Sufficient |
| Stopping       | 谁决定停止         | 充分后 Rule 接管                  | 避免 Agent 无限制继续探索      |
| NODE02A        | 证据如何改变判断      | 独立证据增强复评                     | 取证者不能自己判案             |
| Policy / Route | 最终是否自动化       | Rule 决定信任等级与最终路由             | 自动化权限才是评测终点           |
| Traceability   | 为什么相信证据       | 来源目录 + 明确保存边界                | 不夸大证据链完整性             |


---

### 产品意义

**结构化设计不是为了代码漂亮，而是为了让故障能够归因、产品行为能够解释。**

以及：

**需要不确定性判断时给模型有限自主权；证据资格、充分性停止和最终放行继续由受控机制掌握。**

## 19. 30 秒总结

> Review Agent不是一个“LLM 自动审校器”，而是一套受控的翻译审校决策机制。术语判断需要外部事实时， Agent 可以发起查证，但它不能自己决定证据是否可信，也不能给自己发通行证。把“查谁”收紧成 Exact-span Contract，把 Retrieval 改成由 validated term 锚定候选，再通过 Assessor、Admission、Sufficiency 和 Rule stopping 分层控制。真实运行还暴露了 Gate 和 Provider 波动。核心产品判断是：取证权、判断权和放行权必须分开。



