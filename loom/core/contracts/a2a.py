"""A2A 0.3.x subset: Agent Card, JSON-RPC envelopes, artifact references, LOOM error codes (spec/02 §5, spec/05 §8)."""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints

from loom.core.contracts.common import Contract

A2A_PROTOCOL_VERSION = "0.3.0"


class LoomErrorCode(IntEnum):
    CONTRACT_INVALID = -32001
    ARTIFACT_NOT_FOUND = -32002
    MODEL_UNAVAILABLE = -32003
    TIMEOUT = -32004
    FORBIDDEN_EFFECT = -32005
    # JSON-RPC 2.0 standard codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class AgentSkill(Contract):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    name: str
    description: str
    tags: list[str] = []


class LoomCardExtension(Contract):
    input_contract: str
    output_contract: str
    trust: Literal["first_party", "plugin"]
    graph_view: Literal["mesh", "safety", "player", "full"] | None = None


class AgentCapabilities(Contract):
    streaming: bool = False
    pushNotifications: bool = False


class AgentCard(Contract):
    model_config = ConfigDict(extra="allow", populate_by_name=True)  # other A2A fields are tolerated

    protocolVersion: str = A2A_PROTOCOL_VERSION
    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]
    description: str
    url: str
    version: str
    capabilities: AgentCapabilities = AgentCapabilities()
    defaultInputModes: list[str] = ["application/json"]
    defaultOutputModes: list[str] = ["application/json"]
    skills: list[AgentSkill] = Field(min_length=1)
    x_loom: LoomCardExtension = Field(alias="x-loom")


class ArtifactRef(Contract):
    """`{"$ref": "loom://graph/<video_id>@<sha>", "view": "mesh"}` — passed instead of inline graphs."""

    ref: Annotated[str, StringConstraints(pattern=r"^loom://[a-z_]+/[A-Za-z0-9_\-]+(@sha256:[0-9a-f]{64})?$")] = Field(
        alias="$ref"
    )
    view: Literal["mesh", "safety", "player", "full"] | None = None


class DataPart(Contract):
    kind: Literal["data"] = "data"
    data: dict[str, Any]


class Message(Contract):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    kind: Literal["message"] = "message"
    role: Literal["user", "agent"]
    messageId: str
    parts: list[DataPart] = Field(min_length=1, max_length=1)
    metadata: dict[str, Any] = {}


class MessageSendParams(Contract):
    model_config = ConfigDict(extra="allow")
    message: Message


TaskState = Literal["submitted", "working", "completed", "failed", "canceled"]


class TaskStatus(Contract):
    state: TaskState
    message: str | None = None


class Task(Contract):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    kind: Literal["task"] = "task"
    id: str
    status: TaskStatus
    artifacts: list[DataPart] = []
    error: dict[str, Any] | None = None


class TaskQueryParams(Contract):
    model_config = ConfigDict(extra="allow")
    id: str


class JsonRpcError(Contract):
    code: int
    message: str
    data: Any = None


class JsonRpcRequest(Contract):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: str
    params: dict[str, Any] = {}


class JsonRpcResponse(Contract):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: dict[str, Any] | None = None
    error: JsonRpcError | None = None
