"""OpsCrew — manages servers, deploys apps, monitors systems."""
from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class OpsCrew(BaseFalkensteinCrew):
    def __init__(
        self,
        task_description,
        event_bus,
        chat_id=None,
        vault_context="",
        tools=None,
        llm_model="ollama_chat/gemma4:e4b",
        fc_llm=None,
    ):
        super().__init__("ops", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent("ops", self.llm_model, self.fc_llm, self.tools)
        task = Task(
            description=self.task_description,
            expected_output=self.task_configs["ops_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
