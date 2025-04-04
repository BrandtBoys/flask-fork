import sys
from uuid import uuid4
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
import git
import os
import time
from tree_sitter import Parser
from tree_sitter_languages import get_language
import detect_language


repo = git.Repo(".")

#to accommodate test-environment: the test script manages branch name and creation
branch_id = uuid4()
branch_name = "Update-docs-" + str(branch_id)
repo.git.branch(branch_name)
repo.git.checkout(branch_name)

# Set the branch name in the GitHub Actions environment
with open(os.getenv('GITHUB_ENV'), "a") as env_file:
    env_file.write(f"BRANCH_NAME={branch_name}\n")

# Compare changes and find changed files
hcommit = repo.head.commit
# print(diff)
diff_files = list(hcommit.diff("HEAD~1"))

for file in diff_files:
    source_path = str(file.a_path)
    file_language = detect_language.detect_language(source_path)
    if not file_language:
            continue
    diff = enumerate(repo.git.diff("HEAD~1", "HEAD",source_path).splitlines())

    with open(source_path, "r") as f:
        source_code = f.read()

    # Extract changed line numbers
    changed_lines = set()
    for index, line in diff:
        if line.startswith("+"):
            changed_lines.add(index)
    print(f"this is change lines for {source_path}")
    print(changed_lines)
    
    # Tree-sitter parsing
    parser = Parser()
    language = get_language(file_language)
    parser.set_language(language)
    tree = parser.parse(bytes(source_code, "utf8"))
    root_node = tree.root_node

    # Extract all function which is in the diff
    code_startByte_pairs = []
    def find_code_startByte_pairs(node, changed_lines):
        # nonlocal code_startLine_pairs
        if node.type in ["function_definition"]:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            if any(line in changed_lines for line in range(start_line, end_line + 1)):
                code = source_code[node.start_byte:node.end_byte].strip()
                code_startByte_pairs.append((code,node.start_byte))
        for child in node.children:
            find_code_startByte_pairs(child, changed_lines)
    find_code_startByte_pairs(root_node, changed_lines)

    print(code_startByte_pairs)
    comment_startByte_pairs =[]
    for code, startByte in code_startByte_pairs:

        # Create prompt for LLM
        prompt = ChatPromptTemplate.from_template(
            """
            You are a documentation assistant.

            ## Instructions:
            - Given the code, make an descriptive comment of the function
            - follow best comment practice regrading to the file language
            - if file language is e.g. python use # or if java use //
            - Dont make anything else but a single comment

            ##file language:
            {file_language}

            ## Code:
            {code}

            Return only the comment:
            """
        )

        prompt_input = prompt.format(
            code = code,
            file_language = file_language
        )

        start = time.time()
        # the LLM does it work
        llm = ChatOllama(model="llama3.2", temperature=0.1)
        llm_response = llm.invoke(prompt_input)
        end = time.time()
        print(f"LLM took {end - start:.4f} seconds")
        print(llm_response.content)
        comment_startByte_pairs.append(((llm_response.content + "\n"), startByte))

    commented_code = bytearray(source_code.encode("utf-8"))
    for comment, startByte in reversed(comment_startByte_pairs):
        commented_code[startByte:startByte] = comment.encode()

    # Write changes to docs
    with open(source_path, "w") as f:
        f.write(commented_code.decode("utf-8"))

    # Add changes
    add_files = [source_path]
    repo.index.add(add_files)

# Commit changes
repo.index.commit("Updated inline documentation")

# Push changes
# try:
#     repo.create_remote("origin", url="git@github.com:BrandtBoyz/Bachelor")
# except git.exc.GitCommandError as e:
#     print(f"error: {e}")

repo.remotes.origin.push(refspec=f"{branch_name}:{branch_name}",set_upstream=True)

repo.__del__()
exit(0)