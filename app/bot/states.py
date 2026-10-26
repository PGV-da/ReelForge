"""
ReelForge FSM States.

Defines the aiogram StatesGroup for the interactive verification workflow.
Each state corresponds to a point in the conversation where the bot is
waiting for specific user input.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class VerificationStates(StatesGroup):
    """
    Finite State Machine states for the Reel verification workflow.

    State Flow:
        (idle) → waiting_approval → [
            → editing_caption → waiting_approval
            → editing_thumbnail → waiting_approval
            → publishing → (idle)
            → discarded → (idle)
        ]
    """

    # Bot has sent the preview and is awaiting button interaction
    waiting_approval = State()

    # Admin pressed "Edit Caption" — waiting for new caption text
    editing_caption = State()

    # Admin pressed "Set Thumbnail Timestamp" — waiting for timestamp or image
    editing_thumbnail = State()

    # Publishing is in progress (prevents duplicate button presses)
    publishing = State()
