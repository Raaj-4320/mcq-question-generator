import os
import requests
import json
from nltk.tokenize import sent_tokenize
from nltk.data import find
import nltk
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    after_this_request,
)
from openai import OpenAI
from docx import Document

app = Flask(__name__)


def ensure_punkt_downloaded():
    """
    Ensure that the NLTK 'punkt' tokenizer is downloaded.
    If not, download it.
    """
    try:
        find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")


# Call the function to ensure 'punkt' is downloaded
ensure_punkt_downloaded()


def search_wikipedia(topic):
    """
    Search Wikipedia for the given topic and return the search results.

    Parameters:
    topic (str): The topic to search for on Wikipedia.

    Returns:
    list: A list of search results containing Wikipedia page titles.
    """
    search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={topic}&format=json"
    response = requests.get(search_url)
    search_results = response.json()
    return search_results["query"]["search"]


def get_wikipedia_extract(title, length="full"):
    """
    Get the extract of a Wikipedia page given its title.

    Parameters:
    title (str): The title of the Wikipedia page.
    length (str): The length of the extract ('full', 'medium', or 'intro').

    Returns:
    str: The cleaned extract of the Wikipedia page.
    """
    endpoint = "https://en.wikipedia.org/w/api.php"

    if length == "full":
        exchars = 1000
        params = {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "extracts",
            "exchars": exchars,
            "explaintext": True,
        }
    elif length == "medium":
        exsentences = 10
        params = {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "extracts",
            "exsentences": exsentences,
            "explaintext": True,
        }
    else:
        params = {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
        }

    response = requests.get(endpoint, params=params)
    data = response.json()
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    extract = page.get("extract", "No extract found.")

    sentences = sent_tokenize(extract)

    if sentences and sentences[-1].endswith("..."):
        sentences.pop()

    cleaned_extract = " ".join(sentences)

    return cleaned_extract


def get_mcqs(extracts, numofquestions, intensity):
    """
    Generate multiple choice questions (MCQs) from the given text using OpenAI API.

    Parameters:
    extracts (str): The text to generate questions from.
    numofquestions (int): The number of questions to generate.
    intensity (str): The complexity of the questions ('Easy', 'Medium', 'Hard').

    Returns:
    tuple: A tuple containing the result string, list of questions, choices, and correct answers.
    """

    client = OpenAI(api_key="")  # Replace with your actual OpenAI API key

    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "you are a good teacher who sets a good exam papers",
            },
            {
                "role": "user",
                "content": f'create {numofquestions} numbers of multiple choice questions of this given text in double quotes =========== "{extracts}" ============ with complexity {intensity}, create {numofquestions} numbers of question, and mention all answers the with the questions with ABCD labels. Please do not explain the ansnwer, just return whatever is written in the options and the exact answer not more not less, give the answer with its respected label from ABCD and whatever written in that option of the answer. Give this output in json format. Make sure you create exact {numofquestions} numbers of questions.',
            },
        ],
    )

    qa_data = completion.choices[0].message.content

    # Load JSON data into a Python dictionary
    data = json.loads(qa_data)

    # Create a dictionary with the desired format
    cleaned_data = [
        {
            "question": item["question"],
            "choices": item["options"],
            "correct_answer": item["answer"],
        }
        for item in data["questions"]
    ]

    result = ""
    questions = []
    choices = []
    correct_answers = []

    for i in range(len(cleaned_data)):
        question = cleaned_data[i]["question"]
        choices_dict = cleaned_data[i]["choices"]
        correct_answer = cleaned_data[i]["correct_answer"]

        questions.append(question)
        choices.append(choices_dict)
        correct_answers.append(correct_answer)

        result += f"Question {i + 1}\n"
        result += question + "\n"

        for label, choice in choices_dict.items():
            result += f"{label} : {choice}\n"

        result += f"Correct Answer: {correct_answer}\n\n"

    print("Number of questions ==== ", numofquestions)
    print(len(correct_answers))

    return result, questions, choices, correct_answers


@app.route("/download/<filename>")
def download_file(filename):
    """
    Route to download the specified file.

    Parameters:
    filename (str): The name of the file to download.

    Returns:
    Response: The file to be downloaded.
    """

    @after_this_request
    def remove_file(response):
        try:
            os.remove(filename)
        except Exception as error:
            print(f"Error removing or closing file handle: {error}")
        return response

    return send_file(
        filename,
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.route("/")
def index():
    """
    Route to render the index page.

    Returns:
    Response: The rendered index page.
    """
    return render_template("index.html")


@app.route("/topicname", methods=["POST"])
def topicname():
    """
    Route to handle the form submission for generating MCQs from a Wikipedia topic.

    Returns:
    Response: JSON response containing the generated MCQs and related information.
    """
    topic_name = request.form.get("topicName")
    num_questions = request.form.get("numQuestions")
    intensity = request.form.get("intensity")

    if not topic_name or not num_questions or not intensity:
        return jsonify({"error": "Please complete all fields"})

    search_results = search_wikipedia(topic_name)
    titles = [result["title"] for result in search_results]

    extracts = {}
    for title in titles:
        extract = get_wikipedia_extract(title, length="full")
        extracts[title] = extract

    result, questions, choices, correct_answers = get_mcqs(
        " ".join(extracts.values()), num_questions, intensity
    )

    filename = create_file(result)

    return jsonify(
        {
            "topic_name": topic_name,
            "num_questions": num_questions,
            "intensity": intensity,
            "related_names": titles,
            "extracts": extracts,
            "mcq_result": result,
            "questions": questions,
            "choices": choices,
            "correct_answers": correct_answers,
            "file_url": f"/download/{filename}",
        }
    )


@app.route("/owncontent", methods=["POST"])
def owncontent():
    """
    Route to handle the form submission for generating MCQs from user-provided content.

    Returns:
    Response: JSON response containing the generated MCQs and related information.
    """
    own_content = request.form.get("ownContent")
    num_questions = request.form.get("numQuestionsOwn")
    intensity = "Easy"  # Hardcoded intensity for user-provided content

    if not own_content or not num_questions or not intensity:
        return jsonify({"error": "Please complete all fields"})

    result, questions, choices, correct_answers = get_mcqs(
        own_content, num_questions, intensity
    )

    filename = create_file(result)

    return jsonify(
        {
            "num_questions": num_questions,
            "intensity": intensity,
            "mcq_result": result,
            "questions": questions,
            "choices": choices,
            "correct_answers": correct_answers,
            "file_url": f"/download/{filename}",
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
