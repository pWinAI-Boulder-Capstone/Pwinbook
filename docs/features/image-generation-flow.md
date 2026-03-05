# Image generation flow (Chat with source)

This page describes **each step** of image generation when you use **Chat with source** and ask for an image (e.g. “draw a bar chart of my revenue”).

---

## Where it runs

- **UI:** Open a source → Chat with source → send a message that asks for an image.
- **Backend:** `open_notebook/graphs/source_chat.py` (graph + intent + refiner) and `open_notebook/utils/openrouter_image.py` (OpenRouter API).

---

## Step-by-step flow

### Step 1: Intent classification (LLM)

- **Input:** Your last message (e.g. “draw a bar chart of revenue”).
- **What happens:** A small LLM call with system prompt: “Reply with exactly one word: TEXT or IMAGE.”
- **Output:** Either `"text"` or `"image"`.
- **If TEXT:** Normal Q&A branch runs (no image).
- **If IMAGE:** Flow continues to Step 2.

**Code:** `classify_intent()` in `source_chat.py`; system prompt `CLASSIFY_INTENT_SYSTEM`.

---

### Step 2: Build source context

- **Input:** The current source (document) and its insights.
- **What happens:** `ContextBuilder` loads the source and formats it into one text block (title, content, insights, metadata).
- **Output:** A long string `formatted_context` (used in the next step).

**Code:** `ContextBuilder` + `_format_source_context()` in `source_chat.py`.

---

### Step 3: Refiner LLM (document + your request → one image prompt)

- **Input:**
  - Document content (from Step 2).
  - Your message (e.g. “draw a bar chart of my revenue”).
- **What happens:** An LLM is called with a system prompt that says: “Given the document and the user’s image request, write a **single, detailed prompt** for an image model. Include specific data from the document for charts/graphs. Output only the image prompt.”
- **Output:** One string: the **refined prompt** that will be sent to the image model (e.g. “A bar chart showing revenue for Q1: $X, Q2: $Y, …”).

**Code:** `get_refined_prompt()` in `call_source_image_agent()`; system prompt `IMAGE_PROMPT_REFINER_SYSTEM`.

**If the document doesn't have the data:** The refiner is instructed to use only data that appears in the document and never to invent numbers (e.g. GPA). If the document does not contain the information needed for the chart (e.g. no GPA/CGPA), the refiner outputs `[NO_RELEVANT_CONTENT]` plus a short message. The app then skips image generation and shows that message to the user instead of generating a graph with made-up data.

So: **the LLM does not generate the image.** It only turns “document + your request” into a **text prompt** that the image model will use in Step 4.

---

### Step 4: Image generation (OpenRouter)

- **Input:** The refined prompt from Step 3.
- **What happens:**
  - App reads the **default image model** (Models → Default Model Assignments → Image Generation Model).
  - Sends one request to **OpenRouter** `chat/completions` with `modalities=["image"]` (or `["image","text"]` for some models).
  - Request body: `{ "model": "<name>", "messages": [{ "role": "user", "content": "<refined_prompt>" }], "modalities": [...] }`.
- **Output:** Either a **data URL** string (e.g. `data:image/png;base64,...`) or an **error message** string.

**Code:** `generate_image()` in `open_notebook/utils/openrouter_image.py`.

---

### Step 5: Response to the UI

- The data URL (or error message) is put into an `AIMessage` and returned as the assistant reply.
- The frontend shows the image if the content is a data URL, or shows the error text.

---

## How to see what happens at each step

Logging was added so you can follow the flow in the **server logs** (the terminal where the API/backend runs).

1. Start the backend (e.g. run the API server).
2. In the app, open a source and use Chat with source.
3. Send a message that asks for an image (e.g. “generate a simple bar chart”).
4. Watch the server terminal for lines starting with `[Image flow]`:

- **Step 1:** `[Image flow] Step 1 – Intent classification: ... intent = 'image'`
- **Step 2:** `[Image flow] Step 2 – Source context built: N chars ...`
- **Step 3:** `[Image flow] Step 3 – Refiner LLM: ... Refined prompt (N chars): "..."` (this is what the LLM produced)
- **Step 4 (OpenRouter):** `[Image flow] OpenRouter: using model '...', prompt length N, prompt preview: "..."`
- **Step 4 (result):** `[Image flow] Step 4 – Image generated successfully` or `... returned error: ...`

If the refiner fails, you may see: `[Image flow] Step 3 (fallback) – Using user message as prompt: ...`.

---m

## Summary table

| Step | Who / what        | Input                          | Output                    |
|------|-------------------|---------------------------------|---------------------------|
| 1    | Intent LLM        | Your message                    | `"text"` or `"image"`     |
| 2    | ContextBuilder    | Source + insights              | Formatted document text   |
| 3    | Refiner LLM       | Document + your message        | Single image prompt text  |
| 4    | OpenRouter (image)| Refined prompt                 | Data URL or error string  |
| 5    | Frontend          | Data URL or error              | Show image or error       |

So: **the LLM is used twice** (intent + refiner); **the image is produced only by the image model** (via OpenRouter) in Step 4.
