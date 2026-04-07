"""PremiumCrew — high-capability tasks routed to Claude/Gemini APIs."""
from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class PremiumCrew(BaseFalkensteinCrew):
    def __init__(
        self,
        task_description,
        event_bus,
        chat_id=None,
        vault_context="",
        tools=None,
        llm_model="anthropic/claude-sonnet-4-20250514",
        fc_llm=None,
    ):
        super().__init__("premium", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent("premium", self.llm_model, self.fc_llm, self.tools)
        task = Task(
            description=self.task_description,
            expected_output=self.task_configs["default"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
