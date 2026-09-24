# Student Study Coach

Student Study Coach turns university lessons into reliable revision material: structured summaries, key formulas, problem-solving methods, exercises, corrections, self-tests, revision plans, and YAML lesson schemas.

It is designed for Algerian higher education and supports lessons in French, Arabic, or English. It can be used with Claude, ChatGPT/GPT, GitHub Copilot, or another assistant that can read Markdown files.

## Project Files

```text
student-study-coach/
├── SKILL.md       # Instructions for the AI study coach
├── extract.py     # Local PDF-to-Markdown extractor
└── README.md      # This guide
```

## Important Workflow

The project has two separate stages:

1. **Extract the PDF locally** with `extract.py`.
2. **Give the generated Markdown and metadata to the AI** for studying.

The AI should analyze prepared files. It should not invent extraction results or assume that unreadable PDF content is correct.

## Installation

Install Python 3.9 or newer, then install the PDF dependencies:

```bash
python -m pip install pymupdf pymupdf4llm
```

On Windows, `py -m pip` can be used instead of `python -m pip`.

## Extract a PDF

From the parent directory of `student-study-coach`, run:

```bash
python student-study-coach/extract.py path/to/lesson.pdf path/to/lesson_extracted --method auto
```

The command creates:

```text
lesson_extracted/
├── lesson.md       # Extracted lesson with YAML metadata
├── metadata.json   # PDF, page, outline, link, font, and image metadata
└── images/         # Extracted images, if present
```

The `--method auto` mode first uses `pymupdf4llm` for Markdown structure and falls back to basic PyMuPDF extraction if necessary.

### Useful Options

```bash
# Extract only pages 1 through 10
python student-study-coach/extract.py lesson.pdf lesson_extracted --pages 1-10 --method auto

# Use basic extraction for a problematic or scanned PDF
python student-study-coach/extract.py lesson.pdf lesson_extracted --method pymupdf

# Skip very small images such as icons
python student-study-coach/extract.py lesson.pdf lesson_extracted --min-image-size 100

# Display the extractor version
python student-study-coach/extract.py --version
```

## Use with Claude

Add `SKILL.md` to the Claude project or skills location, then provide `lesson.md` and `metadata.json`. Use a prompt such as:

```text
Use the Student Study Coach instructions in SKILL.md.

Analyze lesson.md and metadata.json. Read the complete lesson twice before answering.
I am a Licence 2 student in Algeria. The module is [module], specialty is [specialty],
and the lesson language is [French/Arabic/English].

Create a complete revision pack with:
- the lesson headline;
- essential exam and TD summary;
- definitions, theorems, formulas, and conditions;
- step-by-step problem-solving methods;
- exercises from easy to exam level;
- corrections after the exercises;
- a self-test without answers;
- a realistic revision plan.

Use only information supported by the lesson. Mark unknown information as "Non précisé".
```

## Use with ChatGPT or GPT

Upload `SKILL.md`, `lesson.md`, and `metadata.json` in the same conversation or project. Then use:

```text
You are a university study coach. Follow SKILL.md exactly.
Read the lesson twice: first for full coverage, second to verify every formula,
definition, exercise, and conclusion.

Prepare this lesson for an Algerian university exam. Keep the lesson's language,
preserve its notation, and do not invent missing content. Give the result under
the lesson headline with sections for objectives, essential summary, memorization,
methods, exercises, corrections, active recall, and revision plan.

Do not reveal the corrections until I attempt the exercises.
```

For a short first response, add: `Start with the summary and exercises only; wait for my request before showing corrections.`

## Use with GitHub Copilot

Open the project folder in VS Code and include `SKILL.md`, `lesson.md`, and `metadata.json` in the chat context. Use:

```text
Act as a careful Algerian university tutor and follow student-study-coach/SKILL.md.
Read the complete lesson twice before producing an answer. Create a structured
revision pack for [module] at [Licence/Master level]. Use French, Arabic, or English
according to the source. Cite page numbers from the extracted lesson where useful.
Separate source-grounded content from additional study advice.
```

## Lesson Schema Mode

Ask the AI to create a structured schema instead of a revision pack:

```text
Follow SKILL.md and output only the YAML lesson schema.
Read the lesson twice and set first_read_complete and second_read_verified to true
only after completing both passes. Fill module, level, specialty, semester, UE,
coefficient, objectives, prerequisites, concepts, formulas, problem types,
exercises, and revision fields only when supported by the source.
Use null, an empty list, or "Non précisé" instead of guessing.
```

## Practice Modes

### Tutor Mode

```text
Teach me this lesson gradually. Ask one question at a time, wait for my answer,
correct my reasoning, and increase the difficulty only when I understand the current step.
```

### Exam Mode

```text
Create a timed exam based only on this lesson. Do not show solutions. Ask me to submit
my work, then grade each answer, explain mistakes, and identify the concepts I should revise.
```

### Flashcard Mode

```text
Create concise active-recall flashcards from the lesson. Include definitions,
conditions of theorems, formula symbols, common traps, and one application question.
Do not turn every sentence into a card.
```

## Algerian University Context

When the information is available, provide:

- module, specialty, level, semester, and teaching language;
- UE type such as UEF, UEM, UED, or UET;
- coefficient and assessment context;
- course, TD, TP, and exam distinctions;
- gradual exercises suitable for Licence or Master study.

The AI must not guess an institution's official syllabus, grading scale, coefficient, or examination rules. Supply those details when they matter.

## Quality and Safety Checks

Before trusting an AI-generated revision pack, check that:

- the AI read the complete extracted lesson twice;
- formulas include their conditions and symbol meanings;
- important sections and figures were not silently omitted;
- exercises are solvable from the lesson or clearly labeled as extensions;
- corrections explain the method, not just the final answer;
- uncertain or unreadable PDF content is clearly identified;
- page references point to the extracted source.

The AI is a study assistant, not an official lecturer or source of university policy. Verify high-stakes academic requirements with your department or instructor.

## Troubleshooting

### `ModuleNotFoundError: pymupdf`

Install the dependencies again:

```bash
python -m pip install pymupdf pymupdf4llm
```

### The output is empty or too short

Try the fallback extractor:

```bash
python student-study-coach/extract.py lesson.pdf lesson_extracted --method pymupdf
```

If the PDF is scanned, it may require OCR before extraction.

### The AI gives a shallow summary

Provide both `lesson.md` and `metadata.json`, explicitly request two complete reading passes, and specify the module, level, specialty, language, and exam or TD goal.

### The PDF contains private student information

Remove names, student numbers, email addresses, and unrelated personal data before uploading the files to an external AI service.

## Recommended File Sharing

For an AI conversation, share:

1. `SKILL.md`
2. the generated lesson Markdown file
3. `metadata.json`
4. relevant files from `images/` when a diagram or table is needed

For large lessons, share one chapter or page range at a time and tell the AI which pages are included.
