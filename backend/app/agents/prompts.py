"""各阶段提示词。

约定：模型输出直接作为产物正文（Markdown / unified diff），不一致时由人工在审批里改。
"""

from __future__ import annotations

from app.agents.state import PipelineState

SYSTEM_BASE = """你是一名资深全栈架构师，正在参与一条受人工审批约束的软件开发流水线。
规则：
1. 只输出本阶段要求的产物，不要寒暄、不要复述任务。
2. 中文输出；技术名词保留英文（API、DTO、SSE 等）。
3. 不确定的信息要写进「待澄清问题」，不要编造事实。
4. 不要声称你执行过命令或测试——你只能产出文档与 diff 草案。
"""


def _context(state: PipelineState) -> str:
    parts: list[str] = []
    agents_md = (state.get("agents_md") or "").strip()
    if agents_md:
        parts.append(f"\n## 项目规范（AGENTS.md，必须遵守）\n{agents_md}\n")

    skills = state.get("skill_index") or []
    if skills:
        blocks = []
        for skill in skills:
            name = str(skill.get("name") or "")
            description = str(skill.get("description") or "")
            entry = str(skill.get("entry") or "").strip()
            block = f"### {name}\n{description}"
            if entry:
                block += f"\n\n{entry}"
            blocks.append(block)
        parts.append("\n## 可用技能（命中场景时按其中的步骤执行）\n" + "\n\n".join(blocks) + "\n")
    return "".join(parts)


def _feedback(state: PipelineState) -> str:
    feedback = (state.get("focus_feedback") or "").strip()
    if not feedback:
        return ""
    return f"\n## 上一轮人工意见（本次必须逐条落实）\n{feedback}\n"


def analysis_prompt(state: PipelineState) -> tuple[str, str]:
    user = f"""## 原始需求
{state.get("raw_requirement", "")}
{_context(state)}{_feedback(state)}
请输出结构化需求文档，Markdown，章节固定：
## 功能点
（编号列表，每条一句话描述可验证的行为）
## 验收标准
（每条用 Given/When/Then 或「输入→期望输出」表达）
## 边界条件
（空值、并发、权限、超限、失败重试等）
## 待澄清问题
（没有就写「无」）
"""
    return SYSTEM_BASE, user


def design_prompt(state: PipelineState) -> tuple[str, str]:
    user = f"""## 已确认的需求文档
{state.get("analysis_doc", "")}
{_context(state)}{_feedback(state)}
请输出系统设计文档，Markdown，章节固定：
## 模块划分
## 接口定义
（HTTP 方法、路径、请求/响应字段、错误码）
## 数据模型
（表/字段/类型/约束；必要时给索引）
## 关键流程
（用 ```mermaid 画 flowchart 或 sequenceDiagram）
## 风险与取舍
"""
    return SYSTEM_BASE, user


def coding_prompt(state: PipelineState) -> tuple[str, str]:
    user = f"""## 设计文档
{state.get("design_doc", "")}
{_context(state)}{_feedback(state)}
当前阶段没有仓库访问权，**只产出一份 unified diff 草案**（git diff 格式），要求：
- 每个文件一个 `diff --git a/... b/...` 段；
- 改动要能直接说明意图，不要贴整文件；
- 需要新增依赖、迁移、配置的地方，在 diff 后用 `## 附注` 说明。
输出只包含 diff 与附注，不要解释过程。"""
    return SYSTEM_BASE, user


def coding_sandbox_prompt(state: PipelineState) -> tuple[str, str]:
    user = f"""## 设计文档
{state.get("design_doc", "")}
{_context(state)}{_feedback(state)}
你在一个**隔离的 git 工作区**里，可以直接改代码并跑测试。可用工具：
- `sandbox_list_files` / `sandbox_read_file`：先了解仓库现状（不要盲改）
- `sandbox_write_file`：写入完整文件内容（覆盖）
- `sandbox_run_command`：执行白名单命令（pytest -q、pnpm test、ruff check 等）
- `sandbox_git_diff`：查看当前改动

工作流要求：
1. 先看目录结构与关键文件；
2. 按设计文档改代码；
3. 跑测试/静态检查，失败就修，最多反复几轮；
4. 最终回答写清楚：改了哪些文件、测试结果、遗留问题（不要贴大段 diff，执行器会用 git diff 收集）。
"""
    return SYSTEM_BASE, user


def review_prompt(state: PipelineState) -> tuple[str, str]:
    user = f"""## 设计文档
{state.get("design_doc", "")}

## 待评审的代码 Diff
{state.get("code_diff", "")}
{_context(state)}{_feedback(state)}
请输出 PR 评审意见，Markdown，章节固定：
## 结论
（通过 / 不通过，一句话）
## 问题清单
（按严重级别：阻断 / 重要 / 建议；每条给 文件:位置、问题、修改建议）
## 缺失的测试
（列出必须补的用例）
"""
    return SYSTEM_BASE, user
