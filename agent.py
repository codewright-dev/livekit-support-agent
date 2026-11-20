"""AeroFlow T2 voice support agent on LiveKit Agents.

Run:  python agent.py console   (talk in your terminal)
      python agent.py dev       (connect to your LiveKit project; call via SIP or the Agents Playground)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from livekit import api
from livekit.agents import Agent, AgentSession, JobContext, RoomInputOptions, RunContext, WorkerOptions, cli, function_tool, get_job_context
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from support_agent.desk import SupportDesk, within_support_hours
from support_agent.retrieval import ManualIndex

load_dotenv()
log = logging.getLogger("aeroflow-agent")

MANUAL = Path(__file__).parent / "manual" / "aeroflow-t2.md"
TRANSFER_NUMBER = os.getenv("TRANSFER_NUMBER", "")

INSTRUCTIONS = """You are Max, the phone support agent for AeroFlow, makers of the T2 smart thermostat.

How you speak: this is a voice call. One or two short sentences per turn, one question at a time, plain words.
Never read lists longer than three steps at once; give a step, check the caller is ready, then continue.

How you help:
- For any product question, call search_manual first and answer only from what it returns.
- If search_manual returns NOT_IN_MANUAL, say you don't have that information and offer a ticket or a human agent.
- Troubleshoot step by step. Before any wiring step, remind the caller to switch off power at the breaker.
- For warranty or refund questions, collect the serial number (starts with AF-T2, six digits) and purchase date, then call check_warranty.
- If the issue isn't solved after the manual's steps, or the caller asks, create a ticket with create_ticket and read back the ticket number slowly.
- Use transfer_to_human when the caller asks for a person, is upset, or there's a safety concern (burning smell, sparks, smoke: tell them to switch off power at the breaker first).

Never invent specifications, prices or policies. Never ask for payment details."""


class SupportAgent(Agent):
    def __init__(self, desk: SupportDesk) -> None:
        super().__init__(instructions=INSTRUCTIONS)
        self.desk = desk

    @function_tool()
    async def search_manual(self, context: RunContext, question: str) -> str:
        """Look up the AeroFlow T2 support manual.

        Args:
            question: The caller's question in plain words, e.g. "blinking amber light" or "error E3".
        """
        return self.desk.search_manual(question)

    @function_tool()
    async def check_warranty(self, context: RunContext, serial_number: str, purchase_date: str) -> dict:
        """Check warranty and refund eligibility.

        Args:
            serial_number: Serial from the back of the unit, like AF-T2-123456.
            purchase_date: Purchase date as YYYY-MM-DD.
        """
        return self.desk.check_warranty(serial_number, purchase_date)

    @function_tool()
    async def create_ticket(self, context: RunContext, name: str, callback_number: str, issue: str, priority: str = "normal") -> dict:
        """Open a support ticket so a technician follows up.

        Args:
            name: Caller's full name.
            callback_number: Phone number to call back.
            issue: Short summary of the problem and what was already tried.
            priority: "low", "normal" or "urgent" (urgent = no heating or cooling).
        """
        return self.desk.create_ticket(name, callback_number, issue, priority)

    @function_tool()
    async def transfer_to_human(self, context: RunContext) -> str:
        """Transfer the call to a human support agent."""
        if not within_support_hours(datetime.now(timezone.utc)):
            return "Human agents are offline (Mon-Fri 8 AM-8 PM Eastern). Offer to create a ticket for a call back instead."
        if not TRANSFER_NUMBER:
            return "Transfers are not configured. Offer to create a ticket instead."
        job = get_job_context()
        caller = next((p for p in job.room.remote_participants.values() if p.identity.startswith("sip_")), None)
        if caller is None:
            return "This caller is not on a phone line, so a transfer isn't possible. Offer a ticket instead."
        await context.session.say("Sure, I'm connecting you to a colleague now. Please hold.", allow_interruptions=False)
        await job.api.sip.transfer_sip_participant(
            api.TransferSIPParticipantRequest(
                room_name=job.room.name,
                participant_identity=caller.identity,
                transfer_to=f"tel:{TRANSFER_NUMBER}",
                play_dialtone=False,
            )
        )
        return "Transferred."


async def entrypoint(ctx: JobContext) -> None:
    desk = SupportDesk(ManualIndex.from_file(MANUAL))
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(model="gpt-4o-mini", temperature=0.3),
        tts=cartesia.TTS(),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )
    await session.start(
        room=ctx.room,
        agent=SupportAgent(desk),
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVCTelephony()),
    )
    await session.generate_reply(instructions="Greet the caller as Max from AeroFlow support and ask how you can help with their T2 thermostat.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
