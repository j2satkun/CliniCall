# LiveKit Agent implementation
from datetime import datetime, timedelta
import json
import logging
from typing import List, Dict, Any
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
        self,
        prompt_file_path: str = "src/healthcare_intake_prompt.md",
        providers_file_path: str = "providers.json",
    ) -> None:
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            instructions = file.read().strip()
        super().__init__(instructions=instructions)

        self.session_id = None
        self.session_data = {}

        self.address_validator = AddressValidator()

        with open(providers_file_path, "r", encoding="utf-8") as f:
            self.providers = json.load(f)

    def set_session_id(self, session_id: str):
        self.session_id = session_id
        self.session_data = {"session_id": session_id}

    def _find_next_available_slot(self, provider_name: str = None) -> Dict[str, Any]:
        """Find the next available appointment slot within a week"""
        today = datetime.now()

        providers_to_check = self.providers
        if provider_name:
            providers_to_check = [
                p for p in self.providers if provider_name.lower() in p["name"].lower()
            ]

        for i in range(1, 8):
            date = today + timedelta(days=i)
            day_name = date.strftime("%A")

            for provider in providers_to_check:
                for schedule_item in provider["schedule"]:
                    if schedule_item["day"] == day_name:
                        return {
                            "provider": provider["name"],
                            "date": date.strftime("%Y-%m-%d"),
                            "time": schedule_item["start"],
                            "day_of_week": day_name,
                            "formatted_date": date.strftime("%B %d, %Y"),
                            "formatted_time": datetime.strptime(
                                schedule_item["start"], "%H:%M"
                            ).strftime("%I:%M %p"),
                        }

        return None

    @function_tool()
    async def get_next_appointment(
        self, provider_preference: str = ""
    ) -> Dict[str, Any]:
        """Get the next available appointment, optionally for a specific provider"""
        try:
            next_slot = self._find_next_available_slot(
                provider_preference if provider_preference else None
            )

            if not next_slot:
                return {
                    "success": False,
                    "message": "No appointments available in the next week",
                }

            return {
                "success": True,
                "appointment": next_slot,
                "message": f"Next available: {next_slot['provider']} on {next_slot['formatted_date']} at {next_slot['formatted_time']}",
            }

        except Exception as e:
            logger.error(f"Error getting next appointment: {e}")
            return {
                "success": False,
                "message": f"Error finding appointments: {str(e)}",
            }

    @function_tool()
    async def book_next_appointment(
        self, provider_preference: str = ""
    ) -> Dict[str, Any]:
        """Book the next available appointment"""
        try:
            next_slot = self._find_next_available_slot(
                provider_preference if provider_preference else None
            )

            if not next_slot:
                return {"success": False, "message": "No appointments available"}

            await self.save_patient_data("appointment_provider", next_slot["provider"])
            await self.save_patient_data("appointment_date", next_slot["date"])
            await self.save_patient_data("appointment_time", next_slot["time"])

            return {
                "success": True,
                "appointment": next_slot,
                "message": f"Booked with {next_slot['provider']} on {next_slot['formatted_date']} at {next_slot['formatted_time']}",
            }

        except Exception as e:
            logger.error(f"Error booking appointment: {e}")
            return {"success": False, "message": f"Error booking appointment: {str(e)}"}

    @function_tool()
    async def get_provider_options(self) -> Dict[str, Any]:
        """Get list of available providers"""
        try:
            provider_list = []
            for provider in self.providers:
                next_slot = self._find_next_available_slot(provider["name"])
                if next_slot:
                    provider_list.append(
                        {
                            "name": provider["name"],
                            "next_available": f"{next_slot['formatted_date']} at {next_slot['formatted_time']}",
                        }
                    )

            return {"success": True, "providers": provider_list}

        except Exception as e:
            logger.error(f"Error getting providers: {e}")
            return {
                "success": False,
                "message": f"Error getting provider list: {str(e)}",
            }

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


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
