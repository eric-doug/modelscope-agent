from .prompt import PromptGenerator

MRKL_DEFAULT_SYSTEM_TEMPLATE = """Answer the following questions as best you can. You have access to the following tools: `

<tool_list>"""

MRKL_DEFAULT_INSTRUCTION_TEMPLATE = """Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [<tool_names>]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can be repeated zero or more times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!
"""

MRKL_DEFAULT_USER_TEMPLATE = """Question: <user_input>\n"""

MRKL_DEFAULT_EXEC_TEMPLATE = """Observation: <exec_result>\nThought:"""


class MrklPromptGenerator(PromptGenerator):

    def __init__(self,
                 system_template=MRKL_DEFAULT_SYSTEM_TEMPLATE,
                 instruction_template=MRKL_DEFAULT_INSTRUCTION_TEMPLATE,
                 user_template=MRKL_DEFAULT_USER_TEMPLATE,
                 exec_template=MRKL_DEFAULT_EXEC_TEMPLATE,
                 assistant_template='',
                 sep='\n\n',
                 prompt_max_length=10000):
        super().__init__(system_template, instruction_template, user_template,
                         exec_template, assistant_template, sep,
                         prompt_max_length)

    def init_prompt(self, task, tool_list, knowledge_list):
        prompt = super().init_prompt(task, tool_list, knowledge_list)
        tool_names = [f'\'{str(tool.name)}\'' for tool in tool_list]
        tool_names = ','.join(tool_names)
        prompt = prompt.replace('<tool_names>', tool_names)
        self.prompt = prompt
        return self.prompt