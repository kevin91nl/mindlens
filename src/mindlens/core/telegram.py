"""Telegram bot — natural language interface to MindLens."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

if TYPE_CHECKING:
    from mindlens.core.config import Config
    from mindlens.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram bot with workspace-aware routing and natural language interface."""

    def __init__(self, config: Config, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus

    async def _emit_event(self, topic: str, data: dict) -> None:
        """Emit an event to the event bus."""
        await self.event_bus.publish(Event(
            topic=topic,
            source="telegram",
            data=data,
        ))
        self._app: Application | None = None
        self._current_workspace: str = "HQ"  # Default context

    async def start(self) -> None:
        """Start the Telegram bot."""
        self._app = (
            Application.builder()
            .token(self.config.telegram_token)
            .build()
        )

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("status", self._handle_status))
        self._app.add_handler(CommandHandler("workspace", self._handle_workspace))
        self._app.add_handler(CommandHandler("help", self._handle_help))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._handle_audio))
        self._app.add_handler(MessageHandler(filters.VIDEO, self._handle_video))
        self._app.add_error_handler(self._handle_error)

        logger.info("Telegram bot starting...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=False)
        logger.info("Telegram bot started. Listening for messages from user %s", self.config.telegram_user_id)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")

    async def send_message(self, text: str, workspace: str | None = None) -> None:
        """Send a completed message to the user via Telegram."""
        if not self._app:
            logger.warning("Cannot send message: bot not started")
            return

        await self._app.bot.send_message(
            chat_id=self.config.telegram_user_id,
            text=self._format_for_telegram(text),
        )

    async def stream_message(self, chunks, workspace: str | None = None) -> str:
        """Stream chunks by editing one Telegram message at a safe cadence."""
        if not self._app:
            logger.warning("Cannot stream message: bot not started")
            return ""

        import time

        message = await self._app.bot.send_message(
            chat_id=self.config.telegram_user_id,
            text="⏳",
        )
        content = ""
        displayed = ""
        last_edit = 0.0

        async for chunk in chunks:
            content += chunk
            now = time.monotonic()
            if now - last_edit >= 1.0 and content != displayed:
                try:
                    await message.edit_text(self._format_for_telegram(content[:4096]))
                    displayed = content
                    last_edit = now
                except Exception as error:
                    logger.debug("Telegram stream edit skipped: %s", error)

        final = content or "No response generated."
        if final != displayed:
            try:
                await message.edit_text(self._format_for_telegram(final[:4096]))
            except Exception:
                await self._app.bot.send_message(
                    chat_id=self.config.telegram_user_id,
                    text=self._format_for_telegram(final[:4096]),
                )
        return content

    @staticmethod
    def _format_for_telegram(text: str) -> str:
        """Convert full Markdown to Telegram-compatible format.

        Telegram supports: *bold*, _italic_, `code`, ```blocks```, [links](url)
        Does NOT support: # headers, | tables, ---, **, __, ~~
        """
        import re

        # Strip any remaining thinking/reasoning blocks
        text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
        text = re.sub(r'<thinking>.*$', '', text, flags=re.DOTALL)

        # Headers → bold
        text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)

        # Tables → list format
        lines = text.splitlines()
        result = []
        in_table = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('|') and '|' in stripped[1:]:
                if stripped.replace('-', '').replace('|', '').replace(' ', '') == '':
                    # Table separator row — skip
                    in_table = True
                    continue
                if in_table:
                    # Table data row
                    cells = [c.strip() for c in stripped.split('|') if c.strip()]
                    if cells:
                        result.append('• ' + ' — '.join(cells))
                    continue
                # First table row — header
                cells = [c.strip() for c in stripped.split('|') if c.strip()]
                if cells:
                    result.append('*' + ' | '.join(cells) + '*')
                    in_table = True
                continue
            else:
                in_table = False
                result.append(line)

        text = '\n'.join(result)

        # Horizontal rules → blank line
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\*\*\*+$', '', text, flags=re.MULTILINE)

        # Fix double bold markers (Telegram uses single *)
        text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

        # Fix double italic markers
        text = re.sub(r'__(.+?)__', r'_\1_', text)

        # Strikethrough → remove (Telegram doesn't support ~~)
        text = re.sub(r'~~(.+?)~~', r'~\1~', text)

        # Clean up excessive blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def _is_authorized(self, update: Update) -> bool:
        """Check if the message is from the authorized user."""
        user_id = update.effective_user.id if update.effective_user else 0
        return user_id == self.config.telegram_user_id

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        if not self._is_authorized(update):
            await update.message.reply_text("Unauthorized.")
            return

        await update.message.reply_text(
            "🧠 MindLens is ready.\n\n"
            "I'm your AI-native holding company OS. "
            "You can talk to me naturally — I'll route your requests "
            "to the right workspace.\n\n"
            "Current workspace: [HQ]\n\n"
            "Try:\n"
            "• \"What's the status?\"\n"
            "• \"Switch to PhD\"\n"
            "• \"Summarize my latest papers\"\n"
            "• \"Create workspace Marketing\""
        )

    async def _handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command — show system status."""
        if not self._is_authorized(update):
            return

        events = self.event_bus.history(limit=10)
        event_summary = "\n".join(
            f"  • {e}" for e in events[-5:]
        ) if events else "  No recent events."

        await update.message.reply_text(
            f"📊 MindLens Status\n"
            f"Current workspace: [{self._current_workspace}]\n\n"
            f"Recent events:\n{event_summary}"
        )

    async def _handle_workspace(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /workspace command — switch workspace context."""
        if not self._is_authorized(update):
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                f"Current workspace: [{self._current_workspace}]\n"
                f"Available: HQ, PhD, Tuvia, RiskStudio"
            )
            return

        workspace = args[0].capitalize()
        self._current_workspace = workspace
        await update.message.reply_text(f"Switched to [{workspace}]. What do you need?")

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle natural language messages — route to appropriate agent."""
        if not self._is_authorized(update):
            logger.warning("Rejected Telegram message from user %s", update.effective_user.id if update.effective_user else None)
            return

        text = update.message.text
        logger.info("Received Telegram message in [%s]: %r", self._current_workspace, text)

        # Publish event for the Chief of Staff to process

        await self.event_bus.publish(Event(
            topic="telegram.message",
            source="telegram",
            data={
                "text": text,
                "workspace": self._current_workspace,
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
            },
        ))

    async def _handle_error(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Log Telegram handler failures without losing the update."""
        logger.exception("Telegram update handling failed", exc_info=context.error)

    async def _handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command with inline keyboard."""
        if not self._is_authorized(update):
            return

        keyboard = [
            [InlineKeyboardButton("📊 Status", callback_data="status"),
             InlineKeyboardButton("🔄 Workspace", callback_data="workspace")],
            [InlineKeyboardButton("📋 Issues", callback_data="issues"),
             InlineKeyboardButton("⏰ Taken", callback_data="tasks")],
            [InlineKeyboardButton("💬 Sessies", callback_data="sessions"),
             InlineKeyboardButton("🧠 Skills", callback_data="skills")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🧠 MindLens — Beschikbare acties:\n\n"
            "💬 Praat gewoon natuurlijk\n"
            "📊 /status — Systeemstatus\n"
            "🔄 /workspace — Wissel werkruimte\n"
            "❓ /help — Dit menu\n\n"
            "Je kunt ook foto's, documenten, audio en video sturen.",
            reply_markup=reply_markup,
        )

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        await query.answer()

        if not self._is_authorized(update):
            return

        action = query.data

        await self.event_bus.publish(Event(
            topic="telegram.message",
            source="telegram",
            data={
                "text": f"Toon {action}",
                "workspace": self._current_workspace,
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
            },
        ))

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle photo messages."""
        if not self._is_authorized(update):
            return

        photo = update.message.photo[-1]
        caption = update.message.caption or "Foto ontvangen"
        await self.event_bus.publish(Event(
            topic="telegram.media",
            source="telegram",
            data={
                "type": "photo",
                "caption": caption,
                "file_id": photo.file_id,
                "workspace": self._current_workspace,
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
            },
        ))

        await update.message.reply_text("📸 Foto ontvangen. Verwerken...")

    async def _handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle document/file messages."""
        if not self._is_authorized(update):
            return

        doc = update.message.document
        caption = update.message.caption or f"Document: {doc.file_name}"
        await self.event_bus.publish(Event(
            topic="telegram.media",
            source="telegram",
            data={
                "type": "document",
                "caption": caption,
                "file_id": doc.file_id,
                "file_name": doc.file_name,
                "mime_type": doc.mime_type,
                "workspace": self._current_workspace,
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
            },
        ))

        await update.message.reply_text(f"📄 Document ontvangen: {doc.file_name}. Verwerken...")

    async def _handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice/audio messages."""
        if not self._is_authorized(update):
            return

        audio = update.message.voice or update.message.audio
        await self.event_bus.publish(Event(
            topic="telegram.media",
            source="telegram",
            data={
                "type": "audio",
                "file_id": audio.file_id,
                "duration": getattr(audio, "duration", 0),
                "workspace": self._current_workspace,
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
            },
        ))

        await update.message.reply_text("🎤 Audio ontvangen. Verwerken...")

    async def _handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle video messages."""
        if not self._is_authorized(update):
            return

        video = update.message.video
        await self.event_bus.publish(Event(
            topic="telegram.media",
            source="telegram",
            data={
                "type": "video",
                "file_id": video.file_id,
                "duration": video.duration,
                "workspace": self._current_workspace,
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
            },
        ))

        await update.message.reply_text("🎬 Video ontvangen. Verwerken...")
