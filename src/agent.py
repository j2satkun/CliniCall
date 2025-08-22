# LiveKit Agent implementation
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import (
    cartesia,
    deepgram,
    noise_cancellation,
    openai,
    silero,
)
from livekit.plugins.turn_detector.english import EnglishModel

load_dotenv()


class HealthcareAgent(Agent):
    def __init__(
        self, prompt_file_path: str = "src/healthcare_intake_prompt.md"
    ) -> None:
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            instructions = file.read().strip()
        super().__init__(instructions=instructions)


async def entrypoint(ctx: agents.JobContext):
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(model="sonic-2"),
        vad=silero.VAD.load(),
        turn_detection=EnglishModel(),
    )

    healthcare_agent = HealthcareAgent()

    await session.start(
        room=ctx.room,
        agent=healthcare_agent,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()

    await session.generate_reply(
        instructions="Greet the user and begin the healthcare intake process."
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
