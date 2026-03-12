# Image generation and editing flow

This document explains how image features currently work in both:

- **Chat with source**
- **Chat with notebook**

It also covers **image editing** (for example: "add the sun to the previous image", "remove the title from the above image", "make the background darker").

---

## Quick overview

In both chat experiences, the flow follows the same high-level pattern:

1. Classify the user intent (`TEXT`, `IMAGE`, or `IMAGE_EDIT`).
2. Build context from the selected scope (single source or notebook context).
3. Ask an LLM to write a refined image prompt.
4. Call OpenRouter image API.
5. Return the result as an AI message.
6. Frontend renders image if content starts with `data:image/...`.

---


## Flow A: Chat with source -> Generate image


### 1) Intent classification

- The latest user message is classified as `TEXT`, `IMAGE`, or `IMAGE_EDIT`.
- If `TEXT`, it goes to the normal source Q&A path.
- If `IMAGE`, it runs source image generation.
- If `IMAGE_EDIT`, it runs source image editing flow.

Code: `classify_intent()` and graph routing in `source_chat.py`.

### 2) Build source context

- Context is built from the selected source (and insights).
- Context is formatted into one text block for the refiner model.

Code: `ContextBuilder` usage and `_format_source_context()` in `source_chat.py`.

### 3) Refine user request into one image prompt

- The refiner model receives:
  - source context
  - user request
- It returns one detailed prompt suitable for an image model.

Code: `get_refined_prompt()` in `call_source_image_agent()`.

### 4) No-relevant-content guard

- If context does not contain what is needed, refiner returns `[NO_RELEVANT_CONTENT] ...`.
- System returns a normal text reply instead of generating a fake or invented chart/image.

### 5) Generate image with OpenRouter

- The refined prompt is sent to `generate_image()`.
- Response is either:
  - a data URL (`data:image/...`) on success
  - an error string on failure

### 6) Return to frontend

- Backend places output into an `AIMessage`.
- Frontend chat renderer displays image when message content is a data URL.

UI rendering code: `frontend/src/components/source/ChatPanel.tsx`.

---

## Flow B: Chat with notebook -> Generate image


Flow is conceptually the same as source chat, with one key difference:

- The context comes from notebook-scoped sources/notes selected by the user.

Detailed behavior:

1. Intent is classified (`TEXT`, `IMAGE`, `IMAGE_EDIT`).
2. Notebook context is formatted by `_format_notebook_context(...)`.
3. Refiner model produces a single image prompt.
4. If `[NO_RELEVANT_CONTENT]` appears, return a text explanation and skip generation.
5. `generate_image(...)` is called.
6. Result is stored as AI message and shown in shared `ChatPanel`.

Code references:

- `classify_intent_notebook()`
- `call_notebook_image_agent()`
- graph routing in `open_notebook/graphs/chat.py`

---

## Flow C: Image editing (both source and notebook chat)

Image edit is available in both chat modes through intent `IMAGE_EDIT`.

### Typical user messages

- "Add a sun in the sky"
- "Remove the chart title"
- "Make the colors pastel"
- "Keep everything same, but replace the lion with a tiger"

### Step-by-step edit logic

1. Locate the last generated image in chat history (last AI message with `data:image/...`).
2. Try **pixel edit** first:
   - send original image + instruction to `edit_image(...)`.
3. If pixel edit fails (or model cannot edit images), fallback to **edit-by-reprompt**:
   - use previous prompt + user change request
   - generate a new refined prompt
   - call `generate_image(...)` again.
4. Return edited image (data URL) or clear error message.

Code references:

- Source chat: `call_source_image_edit_agent()` in `open_notebook/graphs/source_chat.py`
- Notebook chat: `call_notebook_image_edit_agent()` in `open_notebook/graphs/chat.py`
- OpenRouter edit utility: `edit_image()` in `open_notebook/utils/openrouter_image.py`
