"""WebDesignCrew — two-agent pipeline: designer then coder."""
from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class WebDesignCrew(BaseFalkensteinCrew):
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
        super().__init__("web_design", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        # Designer gets no tools; coder gets the tools list.
        web_designer = self._make_agent("web_designer", self.llm_model, self.fc_llm, [])
        web_coder = self._make_agent("web_coder", self.llm_model, self.fc_llm, self.tools)

        design_task = Task(
            description=self.task_description,
            expected_output="Detailed UI/UX design specification with layout, color scheme, and component descriptions.",
            agent=web_designer,
        )
        implement_task = Task(
            description="Implement the design specification as working HTML/CSS/JS code.",
            expected_output=self.task_configs["code_task"]["expected_output"],
            agent=web_coder,
            context=[design_task],
        )
        return Crew(
            agents=[web_designer, web_coder],
            tasks=[design_task, implement_task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
