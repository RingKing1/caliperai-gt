"""
Pydantic schemas for AI Chatbot API.
Request/response validation for chat endpoints.
"""
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageRole(StrEnum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatFeedback(StrEnum):
    """User feedback on assistant responses."""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"



class ChatBaseSchema(BaseModel):
    """Base schema with common configuration."""
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
    )



class ChatContext(ChatBaseSchema):
    """
    Context about user's current state in the application.
    Sent with each message to provide contextual assistance.
    """
    page: str | None = Field(
        None,
        description="Current page path, e.g., '/editor/3d/scene-123'",
        examples=["/editor/3d/abc123", "/tasks", "/projects/xyz"]
    )
    view: str | None = Field(
        None,
        description="Current view mode",
        examples=["3d", "2d", "bev", "fusion"]
    )
    active_tool: str | None = Field(
        None,
        description="Currently active annotation tool",
        examples=["box", "polygon", "ai_segment", "cuboid"]
    )
    selected_annotation_id: UUID | None = Field(
        None,
        description="ID of currently selected annotation"
    )
    task_id: UUID | None = Field(
        None,
        description="ID of current task being worked on"
    )
    project_id: UUID | None = Field(
        None,
        description="ID of current project"
    )
    scene_id: UUID | None = Field(
        None,
        description="ID of current scene"
    )
    frame_index: int | None = Field(
        None,
        description="Current frame index in scene"
    )



class SendMessageRequest(ChatBaseSchema):
    """Request body for sending a chat message."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The user's message to the AI assistant"
    )
    context: ChatContext | None = Field(
        None,
        description="Current UI context for contextual assistance"
    )
    session_id: UUID | None = Field(
        None,
        description="Existing session ID. If None, creates a new session"
    )


class FeedbackRequest(ChatBaseSchema):
    """Request body for submitting message feedback."""
    feedback: ChatFeedback = Field(
        ...,
        description="User's feedback on the assistant response"
    )



class MessageResponse(ChatBaseSchema):
    """Single chat message response."""
    id: UUID = Field(..., description="Message ID")
    role: ChatMessageRole = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    created_at: datetime = Field(..., description="Message timestamp")
    context: dict[str, Any] | None = Field(
        None,
        description="Context at time of message"
    )
    model_used: str | None = Field(
        None,
        description="LLM model used for assistant responses"
    )
    feedback: ChatFeedback | None = Field(
        None,
        description="User feedback if provided"
    )


class ChatSessionResponse(ChatBaseSchema):
    """Chat session with messages."""
    session_id: UUID = Field(..., description="Session ID")
    title: str | None = Field(None, description="Session title")
    created_at: datetime = Field(..., description="Session creation time")
    updated_at: datetime = Field(..., description="Last activity time")
    message_count: int = Field(0, description="Number of messages in session")


class ChatHistoryResponse(ChatBaseSchema):
    """Full chat history for a session."""
    session_id: UUID = Field(..., description="Session ID")
    title: str | None = Field(None, description="Session title")
    messages: list[MessageResponse] = Field(
        default_factory=list,
        description="List of messages in chronological order"
    )
    created_at: datetime = Field(..., description="Session creation time")


class SuggestionResponse(ChatBaseSchema):
    """Contextual question suggestions."""
    suggestions: list[str] = Field(
        default_factory=list,
        description="Suggested questions based on current context"
    )


class StreamMessageResponse(ChatBaseSchema):
    """
    Response for streaming message endpoint.
    Returns metadata about the created messages for client state update.
    """
    session_id: UUID = Field(..., description="Session ID")
    user_message_id: UUID = Field(..., description="Created user message ID")
    assistant_message_id: UUID = Field(..., description="Created assistant message ID")



class SSETokenEvent(ChatBaseSchema):
    """Server-sent event for streaming token."""
    type: str = Field("token", description="Event type")
    content: str = Field(..., description="Token content")


class SSECompleteEvent(ChatBaseSchema):
    """Server-sent event for stream completion."""
    type: str = Field("complete", description="Event type")
    session_id: UUID = Field(..., description="Session ID")
    user_message_id: UUID = Field(..., description="User message ID")
    assistant_message_id: UUID = Field(..., description="Assistant message ID")
    model_used: str = Field(..., description="Model used for response")
    tokens_used: int | None = Field(None, description="Total tokens used")
    latency_ms: int = Field(..., description="Response latency in milliseconds")


class SSEErrorEvent(ChatBaseSchema):
    """Server-sent event for errors."""
    type: str = Field("error", description="Event type")
    error: str = Field(..., description="Error message")



class ChatSessionListResponse(ChatBaseSchema):
    """List of chat sessions."""
    sessions: list[ChatSessionResponse] = Field(
        default_factory=list,
        description="List of user's chat sessions"
    )
    total: int = Field(0, description="Total number of sessions")
