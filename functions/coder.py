import os
import json
from dotenv import load_dotenv
load_dotenv()

from .aider_mod.aider.io import InputOutput
from .aider_mod.aider.models import Model
from .aider_mod.aider.repomap import RepoMap
import re

from openai import OpenAI


def make_query(query, chat, map, cwd):
    q = "Based on the following context:\n" + json.dumps(chat) + f" and the current folder tree(which shows the different files and relevant classes, can be used to analyze/edit existing codebase) : {map}\nAnswer and Code the following query:\n" + query + "Use {cwd} as the current working directory."
    return q

class Coder():
    def __init__(self, project_name, custom_instructions=""):
        import interpreter
        self.chat = []
        self.history = []
        self.errors = 0
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.model = "gpt-4o"
        self.openai = OpenAI(api_key=self.openai_api_key)
        self.interpreter = interpreter.interpreter
        self.interpreter.llm.api_key = self.openai_api_key
        self.interpreter.llm.model = self.model
        self.interpreter.llm.temperature = 0
        self.interpreter.auto_run = True
        self.interpreter.llm.context_window = 4096
        self.interpreter.llm.max_tokens = 1024
        self.repo_map = ""
        self.project_name = project_name
        folder = os.path.join(os.getcwd(), "data")
        self.path = os.path.join(folder, project_name)
        # self.interpreter.chat(f"Check if the directory {self.path} exists. If not create the directory")
        if not os.path.exists(self.path):
            os.makedirs(self.path)
            print(f"Directory created: {self.path}")
        else:
            print(f"Directory already exists: {self.path}")

        ci = f"Very Important : Your working directory is {self.path}, no work is to be done outside this folder including repo clones, and saving files! Not following this will cause panalty! Run all pip install commands as pip install -y [package_name]. Write end-to-end code in proper code format, not as text."
        self.interpreter.custom_instructions = ci + custom_instructions  + f"Write code in {self.path} in new files. Do not write cli commands or any other information."
        self.load_history()
        print("path : ",self.path)

    def make_query(self, query, context):
        q = "Based on the following context:\n" + context + "\n\nWrite and execute code for the query:\n" + query
        return q
    
    def add_chat(self, chat):
        self.chat.append(chat)

    def add_history(self, chunk):
        self.history.append(chunk)

    def save_history(self):
        with open(os.path.join(self.path, "history.json"), "w") as f:
            json.dump(self.history, f)

    def load_history(self):
        if not os.path.exists(os.path.join(self.path, "history.json")):
            with open(os.path.join(self.path, "history.json"), "w") as f:
                json.dump([], f)
        with open(os.path.join(self.path, "history.json"), "r") as f:
            self.history = json.load(f)

    def code(self, query, context):
        self.get_repo_map()
        q = make_query(query, context, self.repo_map, self.path)
        temp = ""
        messages = []
        for chunk in self.interpreter.chat(q, stream=True, display=True):
            if(type(chunk) == str):
                pass
            self.add_history(chunk)
            messages.append(chunk)
            if 'start' in chunk:
                key = chunk["type"]
            elif 'end' in chunk:
                # if(key=="code"):
                #     content = temp
                #     # append to file code.py
                #     with open(os.path.join(self.path, "code.py"), "a") as f:
                #         f.write(content)
                yield json.dumps({key:temp}).encode("utf-8") + b"\n"
                temp = ""
            else:
                if 'format' in chunk and chunk["format"] == "active_line":
                    pass
                if 'content' in chunk:
                    if(type(chunk['content'])==dict):
                        chunk = chunk['content']
                    if "key" == "console" and chunk["format"] == "output" and "Error" in chunk["content"]:
                        self.errors += 1
                        if self.errors > 2:
                            self.interpreter.chat("Too many errors. Exiting.")
                            self.summary = "Got errors while writing code, here is a summary of what was done.\n" + self.generate_summary(self.parse_output(messages)) + "Recommend calling Web Search."
                            yield json.dumps({"exit":True}).encode("utf-8") + b"\n"
                            break
                    temp += str(chunk["content"])
        # print("Message : ",messages)
        self.interpreter.chat(f"If any, write the code from your history in a new file that does not already exist in the {self.path} directory with open, else skip. Use proper formatting and no '\n's")
        self.save_history()
        self.summary = self.generate_summary(self.parse_output(messages))

    def parse_output(self, messages):
        response = {"code":[], "output":[], "message":[]} # code, console, message
        for message in messages:
            try:
                # if message["type"] == "code":
                #     response["code"].append(message["content"])
                # if message["type"] == "console":
                #     response["output"].append(message["content"])
                if message["type"] == "message":
                    response["message"].append(message["content"])
            except:
                pass
        return response
    
    def generate_summary(self, parsed_output):
        code = parsed_output["code"]
        output = parsed_output["output"]
        message = parsed_output["message"]
        prompt = f"""
        Given the following Open Interpreter Response, summarise its initial plan, the actions taken and the conclusion in concise points.
        Code Output:
        {output}
        Interpreter Code:
        {code}
        Interpreter Message:
        {message}
        Write in plain text.
        """
        summary = self.openai.chat.completions.create(
            model = "gpt-4o",
            messages = [
                {"role": "system", "content": prompt}
            ],
            temperature = 0.7
        )
        return summary.choices[0].message.content
    
    def get_repo_map(self):
        model = Model("gpt-4o")
        io = InputOutput()
        dir =  os.path.join(os.getcwd(), "data", self.project_name)
        files = []
        excl = [
            r'^\.',
            r'^\.git*',
            r'^__pycache__',
            r'history.json'
        ]

        for root, _, file in os.walk(dir):
            for f in file:
                full_path = os.path.join(root, f)
                path_components = os.path.normpath(full_path).split(os.sep)
                if not any(re.search(pattern, component) for component in path_components for pattern in excl):
                    files.append(full_path)
        repoMap = RepoMap(main_model=model, root=dir, io=io)
        self.repo_map = repoMap.get_repo_map([],files)
        print("Repo Map : ",self.repo_map)

    
if __name__ == "__main__":
    c = Coder("1")
    sample_message = {
        {"role": "assistant", "type": "code", "format": "python", "start": True},
        {"role": "assistant", "type": "code", "format": "python", "content": "34"},
        {"role": "assistant", "type": "code", "format": "python", "content": " /"},
        {"role": "assistant", "type": "code", "format": "python", "content": " "},
        {"role": "assistant", "type": "code", "format": "python", "content": "24"},
        {"role": "assistant", "type": "code", "format": "python", "end": True}
    }
