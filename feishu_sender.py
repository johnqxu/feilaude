import json
import logging

from lark_oapi import Client as LarkClient
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

logger = logging.getLogger(__name__)

MAX_SEGMENT_LEN = 2000


class FeishuSender:
    def __init__(self, app_id: str, app_secret: str):
        self.client = LarkClient.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .build()
        logger.info("飞书客户端初始化完成")

    def send_message(self, open_id: str, text: str):
        """Send plain text message (for status updates and errors)."""
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        content_json = '{"text":"' + escaped + '"}'

        request = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .content(content_json)
                .msg_type("text")
                .receive_id(open_id)
                .build()
            ) \
            .build()

        response = self.client.im.v1.message.create(request)
        if not response.success():
            logger.error("飞书消息发送失败：code=%s, msg=%s", response.code, response.msg)
        else:
            logger.info("飞书消息发送成功：open_id=%s, 长度=%d", open_id, len(text))

    def send_card(self, open_id: str, text: str, title: str = "Claude 回复"):
        """Send interactive card with markdown content, splitting long text into multiple cards."""
        segments = _split_text(text, MAX_SEGMENT_LEN)

        for i, segment in enumerate(segments):
            card_title = title if i == 0 else f"{title}（续）"
            self._send_single_card(open_id, segment, card_title)

    def _send_single_card(self, open_id: str, text: str, title: str):
        """Send a single interactive card."""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title}
            },
            "elements": [
                {"tag": "markdown", "content": text}
            ]
        }
        content_json = json.dumps(card, ensure_ascii=False)

        request = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .content(content_json)
                .msg_type("interactive")
                .receive_id(open_id)
                .build()
            ) \
            .build()

        response = self.client.im.v1.message.create(request)
        if not response.success():
            logger.error("飞书卡片发送失败：code=%s, msg=%s", response.code, response.msg)
        else:
            logger.info("飞书卡片发送成功：open_id=%s, 标题=%s, 长度=%d", open_id, title, len(text))


def _split_text(text: str, max_len: int) -> list[str]:
    """Split text into segments of at most max_len characters.

    Prefers splitting at paragraph boundaries (\\n\\n).
    Protects code blocks: if a split point falls inside an unclosed ```,
    the closing marker is appended to the segment and prepended to the next.
    """
    if len(text) <= max_len:
        return [text]

    segments = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            segments.append(remaining)
            break

        # Find a split point near max_len, preferring \n\n
        split_pos = _find_split_point(remaining, max_len)

        segment = remaining[:split_pos]

        # Code block protection: check if we're splitting inside a code block
        segment, remainder_after = _protect_code_blocks(segment, remaining[split_pos:])

        segments.append(segment)
        remaining = remainder_after

    return segments


def _find_split_point(text: str, max_len: int) -> int:
    """Find the best split point at or before max_len, preferring paragraph boundaries."""
    # Look for \n\n from max_len backwards
    search_start = max(0, max_len - 500)
    best_pos = text.rfind("\n\n", search_start, max_len)

    if best_pos > 0:
        return best_pos + 2  # split after the \n\n

    # Fallback: look for single \n
    best_pos = text.rfind("\n", search_start, max_len)
    if best_pos > 0:
        return best_pos + 1

    # Last resort: hard cut at max_len
    return max_len


def _protect_code_blocks(segment: str, remainder: str) -> tuple[str, str]:
    """If segment has an unclosed code block, close it and reopen in remainder."""
    # Count triple-backtick occurrences
    count = segment.count("```")
    if count % 2 == 0:
        # All code blocks are properly closed
        return segment, remainder

    # Odd number means unclosed code block — close it
    return segment + "\n```\n", "```\n" + remainder
