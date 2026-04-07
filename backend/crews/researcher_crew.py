"""ResearcherCrew — researches topics and stores results in Obsidian."""
from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class ResearcherCrew(BaseFalkensteinCrew):
    def __init__(
        self,
        task_description,
        event_bus,
        chat_id=None,
        vault_context="",
        tools=None,
        llm_model="ollama_chat/gemma4:26b",
        fc_llm="ollama_chat/gemma4:e4b",
    ):
        super().__init__("researcher", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent("researcher", self.llm_model, self.fc_llm, self.tools)
        description = (
            self.task_description
            + "\n\nSpeichere das Ergebnis in der Obsidian-Wissensbasis unter dem passenden Ordner."
        )
        task = Task(
            description=description,
            expected_output=self.task_configs["research_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
