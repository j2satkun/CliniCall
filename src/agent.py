# LiveKit Agent implementation
import logging
from typing_extensions import TypedDict

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.agents import function_tool
from livekit.plugins import (
    cartesia,
    deepgram,
    noise_cancellation,
    openai,
    silero,
)
from livekit.plugins.turn_detector.english import EnglishModel

from services import AddressValidator

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class AddressData(TypedDict):
    line1: str
    line2: str
    city: str
    state: str
    zip_code: str


class HealthcareAgent(Agent):
    def __init__(
        self, prompt_file_path: str = "src/healthcare_intake_prompt.md"
    ) -> None:
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            instructions = file.read().strip()
        super().__init__(instructions=instructions)

        self.session_id = None
        self.session_data = {}

        self.address_validator = AddressValidator()

    def set_session_id(self, session_id: str):
        self.session_id = session_id
        self.session_data = {"session_id": session_id}

    @function_tool()
    async def save_patient_data(self, field_name: str, field_value: str) -> dict:
        """Save patient data to session memory"""
        try:
            if not self.session_id:
                return {"success": False, "message": "Session not initialized"}

            self.session_data[field_name] = field_value

            logger.info(f"Saved {field_name}: {field_value}")

            return {"success": True, "message": f"Successfully saved {field_name}"}

        except Exception as e:
            logger.error(f"Error saving patient data: {e}")
            return {"success": False, "message": f"Error saving data: {str(e)}"}

    @function_tool()
    async def validate_address(self, address_data: AddressData) -> dict:
        """Validate address using HERE API"""
        try:
            is_valid, validated_address = await self.address_validator.validate(
                address_data
            )

            if is_valid:
                await self.save_patient_data(
                    "address_line1", validated_address["line1"]
                )
                await self.save_patient_data(
                    "address_line2", validated_address.get("line2", "")
                )
                await self.save_patient_data("city", validated_address["city"])
                await self.save_patient_data("state", validated_address["state"])
                await self.save_patient_data("zip_code", validated_address["zip_code"])

            return {
                "valid": is_valid,
                "message": (
                    "Address validated successfully"
                    if is_valid
                    else "Address needs correction"
                ),
                "validated_address": validated_address if is_valid else None,
            }
        except Exception as e:
            logging.error(f"Address validation error: {e}")
            return {"valid": False, "message": "Address validation service unavailable"}


async def entrypoint(ctx: agents.JobContext):
    healthcare_agent = HealthcareAgent()
    session_id = ctx.room.name
    healthcare_agent.set_session_id(session_id)

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(model="sonic-2"),
        vad=silero.VAD.load(),
        turn_detection=EnglishModel(),
    )

    await session.start(
        room=ctx.room,
        agent=healthcare_agent,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()

    await session.generate_reply(
        instructions=f"Greet the user and begin the healthcare intake process. Your session ID is {session_id}."
    )

    logger.info(f"Session {session_id} started, waiting for completion...")


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
