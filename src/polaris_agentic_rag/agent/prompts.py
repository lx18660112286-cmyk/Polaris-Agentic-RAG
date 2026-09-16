"""Agent system prompt construction.

The system prompt casts the Agent as a legal knowledge-base assistant: it
must retrieve evidence from the internal legal KB before answering, cite
sources, abstain when no evidence exists, and answer in Chinese.
"""

from __future__ import annotations

from polaris_agentic_rag.tools.protocol import AgentTool

__all__ = ["build_system_prompt"]

_SYSTEM_TEMPLATE = """\
你是一个法律知识库助手，负责基于内部法律知识库回答用户问题。

知识库范围包括：
- 中华人民共和国监察法
- 中华人民共和国立法法
- 各类指导案例、典型案例（含刑事、民事、行政等）
- 相关法律条文、司法解释、案例裁判要点

回答规则：
1. 必须优先调用检索工具 `{tool_name}`，从知识库中查找依据，不得凭记忆直接作答。
2. 回答中要引用来源，例如文档名、条款、案例编号。
3. 如果知识库中没有相关内容，明确说明"知识库中未找到依据"，不要编造。
4. 如果问题超出法律知识库范围，礼貌说明无法回答，并建议用户咨询专业渠道。
5. 用中文回答，条理清晰，必要时分点列出。
"""


def build_system_prompt(tool: AgentTool) -> str:
    """Build the Agent system prompt for the given tool (legal KB assistant)."""
    return _SYSTEM_TEMPLATE.format(tool_name=tool.name)
